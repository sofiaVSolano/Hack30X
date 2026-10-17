"""Recolección manual de datos reales.

Flujo (síncrono: la llamada termina cuando la recolección termina):

1. crea la recolección en estado ``running`` (transacción propia, visible enseguida);
2. ejecuta los conectores con el ejecutor aislado de E3 y el cliente HTTP compartido;
3. registra cada fuente y sus observaciones con ``record_connector_result``;
4. cierra la recolección con su estado real: ``ok`` si todas las fuentes respondieron,
   ``failed`` si todas fallaron, ``partial`` en cualquier otro caso.

Si algo inesperado ocurre después del paso 1, la recolección se cierra como ``failed``:
nunca queda en curso ni aparece como exitosa.

Concurrencia: un ``asyncio.Lock`` impide dos recolecciones simultáneas en el proceso, y
una comprobación en SQLite rechaza iniciar si hay otra recolección real en curso
reciente (por ejemplo, de otro proceso). Una recolección en curso más antigua que
``stale_after`` se considera abandonada y se cierra como ``failed``.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.base import (
    BaseConnector,
    Clock,
    ConnectorQuery,
    ConnectorResult,
    utc_now,
)
from app.modules.detectar.connectors.gdelt import GdeltDocConnector
from app.modules.detectar.connectors.google_trends_rss import GoogleTrendsRssConnector
from app.modules.detectar.connectors.http import HttpClient, HttpSettings
from app.modules.detectar.connectors.params import GdeltParams, WikimediaParams
from app.modules.detectar.connectors.wikimedia import WikimediaPageviewsConnector
from app.modules.detectar.ingestion.recording import record_connector_result
from app.modules.detectar.ingestion.runner import run_connectors
from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    DataMode,
    Source,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository, InsertResult

logger = logging.getLogger(__name__)

ConnectorFactory = Callable[[HttpClient, DetectarSettings], Mapping[Source, BaseConnector]]


class CollectionInProgressError(RuntimeError):
    pass


class SourceNotEnabledError(ValueError):
    pass


def default_connectors(
    client: HttpClient, settings: DetectarSettings
) -> dict[Source, BaseConnector]:
    """Conectores reales: Google Trends RSS (E4), Wikimedia Pageviews (E5) y GDELT (E6)."""
    return {
        Source.GOOGLE_TRENDS_RSS: GoogleTrendsRssConnector(
            client, enabled=settings.gtr_mode == "on", default_countries=settings.countries
        ),
        Source.WIKIMEDIA: WikimediaPageviewsConnector(
            client,
            enabled=settings.wikimedia_mode == "on",
            contact=settings.http_contact,
            default_projects=settings.wikimedia_projects,
            max_days=settings.wikimedia_max_days,
            max_articles=settings.wikimedia_max_articles,
        ),
        Source.GDELT: GdeltDocConnector(
            client,
            enabled=settings.gdelt_mode == "on",
            max_requests=settings.gdelt_max_requests,
            min_interval_seconds=settings.gdelt_min_interval_seconds,
        ),
    }


def source_availability(settings: DetectarSettings) -> dict[Source, str | None]:
    """Motivo por el que cada fuente no puede usarse; ``None`` si está habilitada."""
    reasons: dict[Source, str | None] = {
        source: "sin conector real en esta versión" for source in Source
    }
    reasons[Source.GOOGLE_TRENDS_RSS] = None if settings.gtr_mode == "on" else "desactivada"
    if settings.wikimedia_mode != "on":
        reasons[Source.WIKIMEDIA] = "desactivada (DETECTAR_WIKIMEDIA_MODE)"
    elif not settings.http_contact:
        reasons[Source.WIKIMEDIA] = "falta DETECTAR_HTTP_CONTACT"
    else:
        reasons[Source.WIKIMEDIA] = None
    reasons[Source.GDELT] = None if settings.gdelt_mode == "on" else "desactivada (DETECTAR_GDELT_MODE)"
    return reasons


def enabled_sources(settings: DetectarSettings) -> frozenset[Source]:
    return frozenset(s for s, reason in source_availability(settings).items() if reason is None)


@dataclass(frozen=True)
class SourceReport:
    source: Source
    status: SourceRunStatus
    inserted: int
    ignored: int
    http_calls: int
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True)
class CollectionReport:
    run_id: str
    status: CollectionStatus
    started_at: datetime
    finished_at: datetime
    countries: tuple[str, ...]
    sources: tuple[SourceReport, ...]


def aggregate_status(statuses: Sequence[SourceRunStatus]) -> CollectionStatus:
    if not statuses:
        return CollectionStatus.FAILED
    if all(status is SourceRunStatus.OK for status in statuses):
        return CollectionStatus.OK
    if all(status is SourceRunStatus.FAILED for status in statuses):
        return CollectionStatus.FAILED
    return CollectionStatus.PARTIAL


class CollectionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: DetectarSettings,
        *,
        connector_factory: ConnectorFactory = default_connectors,
        http_transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = utc_now,
        stale_after: timedelta = timedelta(minutes=30),
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._connector_factory = connector_factory
        self._transport = http_transport
        self._clock = clock
        self._stale_after = stale_after
        self._lock = asyncio.Lock()

    async def collect(
        self,
        sources: Sequence[Source],
        countries: Sequence[str],
        *,
        wikimedia: WikimediaParams | None = None,
        gdelt: GdeltParams | None = None,
        trigger: CollectionTrigger = CollectionTrigger.MANUAL,
    ) -> CollectionReport:
        sources = tuple(dict.fromkeys(Source(s) for s in sources))
        if not sources:
            raise SourceNotEnabledError("No se indicó ninguna fuente")
        reasons = source_availability(self._settings)
        not_enabled = {s: reasons[s] for s in sources if reasons[s] is not None}
        if not_enabled:
            raise SourceNotEnabledError(
                "Fuentes no habilitadas: "
                + "; ".join(f"{s.value} ({why})" for s, why in sorted(not_enabled.items()))
            )
        if (Source.WIKIMEDIA in sources) != (wikimedia is not None):
            raise ValueError("Los parámetros de Wikimedia solo y siempre acompañan a esa fuente")
        if (Source.GDELT in sources) != (gdelt is not None):
            raise ValueError("Los parámetros de GDELT solo y siempre acompañan a esa fuente")
        countries = tuple(countries) if Source.GOOGLE_TRENDS_RSS in sources else ()
        # Sin await entre la comprobación y la adquisición: es atómico en asyncio.
        if self._lock.locked():
            raise CollectionInProgressError("Ya hay una recolección en curso en este proceso")
        async with self._lock:
            request_params = {
                "paises": list(countries),
                "wikimedia": wikimedia.model_dump(mode="json") if wikimedia else None,
                "gdelt": gdelt.model_dump(mode="json") if gdelt else None,
            }
            run_id, started_at = self._open_run(sources, countries, trigger, request_params)
            try:
                results = await self._run(sources, countries, wikimedia, gdelt)
                return self._record(run_id, started_at, countries, results)
            except BaseException:
                logger.error("La recolección %s falló de forma inesperada", run_id)
                self._close_as_failed(run_id)
                raise

    # --- pasos ----------------------------------------------------------------

    def _open_run(
        self,
        sources: Sequence[Source],
        countries: Sequence[str],
        trigger: CollectionTrigger,
        request_params: dict[str, object],
    ) -> tuple[str, datetime]:
        with self._session_factory() as session, session.begin():
            repo = DetectarRepository(session)
            now = self._clock()
            for running in repo.list_collection_runs(
                data_mode=DataMode.REAL, status=CollectionStatus.RUNNING, limit=100
            ):
                if running.started_at and now - running.started_at < self._stale_after:
                    raise CollectionInProgressError(
                        f"La recolección {running.id} sigue en curso"
                    )
                logger.warning("Cerrando como fallida la recolección abandonada %s", running.id)
                repo.finish_collection_run(
                    running.id, data_mode=DataMode.REAL, status=CollectionStatus.FAILED, finished_at=now
                )
            run = repo.create_collection_run(
                data_mode=DataMode.REAL,
                trigger=trigger,
                requested_sources=sources,
                requested_countries=countries,
                created_at=now,
                status=CollectionStatus.RUNNING,
                started_at=now,
                request_params=request_params,
            )
            return run.id, run.started_at

    async def _run(
        self,
        sources: Sequence[Source],
        countries: Sequence[str],
        wikimedia: WikimediaParams | None,
        gdelt: GdeltParams | None,
    ) -> list[ConnectorResult]:
        http_settings = HttpSettings.from_settings(self._settings)
        async with HttpClient(http_settings, transport=self._transport) as client:
            available = self._connector_factory(client, self._settings)
            connectors = [available[source] for source in sources]
            return await run_connectors(
                connectors,
                ConnectorQuery(countries=tuple(countries), wikimedia=wikimedia, gdelt=gdelt),
                timeout_seconds=self._settings.connector_timeout_seconds,
            )

    def _record(
        self,
        run_id: str,
        started_at: datetime,
        countries: Sequence[str],
        results: Sequence[ConnectorResult],
    ) -> CollectionReport:
        reports: list[SourceReport] = []
        with self._session_factory() as session, session.begin():
            repo = DetectarRepository(session)
            for result in results:
                source_run, inserted = record_connector_result(
                    repo, collection_run_id=run_id, result=result, mode="on", data_mode=DataMode.REAL
                )
                reports.append(_source_report(source_run.status, result, inserted))
            status = aggregate_status([r.status for r in reports])
            run = repo.finish_collection_run(
                run_id, data_mode=DataMode.REAL, status=status, finished_at=self._clock()
            )
            return CollectionReport(
                run_id=run_id,
                status=run.status,
                started_at=started_at,
                finished_at=run.finished_at,
                countries=tuple(countries),
                sources=tuple(reports),
            )

    def _close_as_failed(self, run_id: str) -> None:
        try:
            with self._session_factory() as session, session.begin():
                repo = DetectarRepository(session)
                run = repo.get_collection_run(run_id, data_mode=DataMode.REAL)
                if run is not None and run.status is CollectionStatus.RUNNING:
                    repo.finish_collection_run(
                        run_id,
                        data_mode=DataMode.REAL,
                        status=CollectionStatus.FAILED,
                        finished_at=self._clock(),
                    )
        except Exception:  # noqa: BLE001 - no ocultar el error original
            logger.error("No se pudo cerrar como fallida la recolección %s", run_id)


def _source_report(
    status: SourceRunStatus, result: ConnectorResult, inserted: InsertResult
) -> SourceReport:
    return SourceReport(
        source=result.source,
        status=status,
        inserted=inserted.inserted,
        ignored=inserted.ignored,
        http_calls=result.http_calls,
        error_code=result.error.code if result.error else None,
        error_detail=result.error.detail if result.error else None,
    )
