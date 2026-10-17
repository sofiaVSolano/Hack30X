"""Repositorio de almacenamiento de DETECTAR.

Toda lectura y escritura exige ``data_mode`` como argumento obligatorio y filtra por él.
No existe ninguna operación que devuelva datos reales y simulados mezclados.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.modules.detectar.storage.models import (
    CollectionRun,
    CollectionStatus,
    CollectionTrigger,
    CountryBasis,
    DataMode,
    Granularity,
    LanguageBasis,
    RawObservation,
    Source,
    SourceRun,
    SourceRunStatus,
    SubjectType,
    Unit,
)

MAX_LIST_LIMIT = 10_000
ERROR_DETAIL_MAX_LENGTH = 500

_FINAL_COLLECTION_STATUSES = frozenset(
    {CollectionStatus.OK, CollectionStatus.PARTIAL, CollectionStatus.FAILED}
)


class InvalidDataModeError(ValueError):
    pass


def require_data_mode(value: object) -> DataMode:
    if isinstance(value, DataMode):
        return value
    if isinstance(value, str):
        try:
            return DataMode(value)
        except ValueError:
            pass
    raise InvalidDataModeError(f"data_mode inválido: {value!r}; use 'real' o 'simulated'")


class _AnyCountry:
    def __repr__(self) -> str:
        return "ANY_COUNTRY"


# Valor por defecto del filtro de país: sin filtrar. Pasar ``None`` filtra ``country IS NULL``.
ANY_COUNTRY: Final = _AnyCountry()


class ObservationIn(BaseModel):
    """Observación original tal como la entrega un conector, antes de guardarla."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Source
    metric_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    unit: Unit
    value: float | None = None
    value_text: str | None = Field(default=None, min_length=1, max_length=64)
    observed_at: AwareDatetime
    period_start: AwareDatetime
    period_end: AwareDatetime | None = None
    # Fecha de publicación original que informa la fuente (no es la hora de consulta).
    source_published_at: AwareDatetime | None = None
    granularity: Granularity
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    country_basis: CountryBasis = CountryBasis.NONE
    language: str | None = Field(default=None, min_length=2, max_length=35)
    language_basis: LanguageBasis = LanguageBasis.NONE
    subject_type: SubjectType
    subject_ref: str = Field(min_length=1, max_length=500)
    source_url: str | None = None
    raw_excerpt: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "ObservationIn":
        if self.source is Source.YOUTUBE:
            raise ValueError("Las observaciones de YouTube no se almacenan")
        if self.value is None and self.value_text is None:
            raise ValueError("Se requiere value o value_text")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("value debe ser un número finito")
        if self.period_end is not None and self.period_end < self.period_start:
            raise ValueError("period_end no puede ser anterior a period_start")
        if (self.country is None) != (self.country_basis is CountryBasis.NONE):
            raise ValueError("country y country_basis deben indicarse juntos")
        if (self.language is None) != (self.language_basis is LanguageBasis.NONE):
            raise ValueError("language y language_basis deben indicarse juntos")
        return self


@dataclass(frozen=True)
class InsertResult:
    inserted: int
    ignored: int


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class DetectarRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Recolecciones ---------------------------------------------------------

    def create_collection_run(
        self,
        *,
        data_mode: DataMode | str,
        trigger: CollectionTrigger,
        requested_sources: Sequence[Source],
        requested_countries: Sequence[str],
        created_at: datetime,
        status: CollectionStatus = CollectionStatus.QUEUED,
        started_at: datetime | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> CollectionRun:
        status = CollectionStatus(status)
        if status not in (CollectionStatus.QUEUED, CollectionStatus.RUNNING):
            raise ValueError("Una recolección nueva solo puede estar en cola o en curso")
        if (status is CollectionStatus.RUNNING) != (started_at is not None):
            raise ValueError("started_at es obligatorio en curso y no aplica en cola")
        run = CollectionRun(
            id=_new_id("run"),
            data_mode=require_data_mode(data_mode),
            trigger=CollectionTrigger(trigger),
            status=status,
            requested_sources=[Source(source).value for source in requested_sources],
            requested_countries=list(requested_countries),
            created_at=created_at,
            started_at=started_at,
            request_params=request_params,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def finish_collection_run(
        self,
        run_id: str,
        *,
        data_mode: DataMode | str,
        status: CollectionStatus,
        finished_at: datetime,
    ) -> CollectionRun:
        """Cierra una recolección en curso con su estado final real."""
        status = CollectionStatus(status)
        if status not in _FINAL_COLLECTION_STATUSES:
            raise ValueError(f"Estado final inválido: {status.value!r}")
        run = self.get_collection_run(run_id, data_mode=data_mode)
        if run is None:
            raise LookupError(f"No existe la recolección {run_id!r} con ese data_mode")
        if run.status is not CollectionStatus.RUNNING:
            raise ValueError(f"Solo se cierra una recolección en curso (estado: {run.status.value!r})")
        run.status = status
        run.finished_at = finished_at
        self._session.flush()
        return run

    def get_collection_run(self, run_id: str, *, data_mode: DataMode | str) -> CollectionRun | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(CollectionRun).where(CollectionRun.id == run_id, CollectionRun.data_mode == mode)
        )

    def list_collection_runs(
        self,
        *,
        data_mode: DataMode | str,
        status: CollectionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CollectionRun]:
        """Más recientes primero; orden estable por id ante fechas iguales."""
        if offset < 0:
            raise ValueError("offset no puede ser negativo")
        stmt = self._collection_filter(data_mode, status)
        stmt = (
            stmt.order_by(CollectionRun.created_at.desc(), CollectionRun.id)
            .limit(_check_limit(limit))
            .offset(offset)
        )
        return list(self._session.scalars(stmt))

    def count_collection_runs(
        self, *, data_mode: DataMode | str, status: CollectionStatus | None = None
    ) -> int:
        stmt = self._collection_filter(data_mode, status)
        return int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    def _collection_filter(self, data_mode: DataMode | str, status: CollectionStatus | None):
        mode = require_data_mode(data_mode)
        stmt = select(CollectionRun).where(CollectionRun.data_mode == mode)
        if status is not None:
            stmt = stmt.where(CollectionRun.status == CollectionStatus(status))
        return stmt

    # --- Ejecuciones por fuente ------------------------------------------------

    def add_source_run(
        self,
        *,
        collection_run_id: str,
        data_mode: DataMode | str,
        source: Source,
        mode: str,
        status: SourceRunStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        http_calls: int = 0,
        items: int = 0,
        estimated_cost_usd: float = 0.0,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> SourceRun:
        data_mode = require_data_mode(data_mode)
        if self.get_collection_run(collection_run_id, data_mode=data_mode) is None:
            raise LookupError(
                f"No existe la recolección {collection_run_id!r} con data_mode={data_mode.value!r}"
            )
        source_run = SourceRun(
            id=_new_id("srn"),
            collection_run_id=collection_run_id,
            data_mode=data_mode,
            source=Source(source),
            mode=mode,
            status=SourceRunStatus(status),
            started_at=started_at,
            finished_at=finished_at,
            http_calls=http_calls,
            items=items,
            estimated_cost_usd=estimated_cost_usd,
            error_code=error_code,
            error_detail=error_detail[:ERROR_DETAIL_MAX_LENGTH] if error_detail else None,
        )
        self._session.add(source_run)
        self._session.flush()
        return source_run

    def set_source_run_items(
        self, source_run_id: str, items: int, *, data_mode: DataMode | str
    ) -> SourceRun:
        """Actualiza el número de observaciones nuevas guardadas por una ejecución."""
        if items < 0:
            raise ValueError("items no puede ser negativo")
        source_run = self.get_source_run(source_run_id, data_mode=data_mode)
        if source_run is None:
            raise LookupError(f"No existe la ejecución {source_run_id!r} con ese data_mode")
        source_run.items = items
        self._session.flush()
        return source_run

    def get_source_run(self, source_run_id: str, *, data_mode: DataMode | str) -> SourceRun | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(SourceRun).where(SourceRun.id == source_run_id, SourceRun.data_mode == mode)
        )

    def list_source_runs_for(
        self, collection_run_ids: Sequence[str], *, data_mode: DataMode | str
    ) -> dict[str, list[SourceRun]]:
        """Ejecuciones por fuente de varias recolecciones en una sola consulta."""
        mode = require_data_mode(data_mode)
        grouped: dict[str, list[SourceRun]] = {run_id: [] for run_id in collection_run_ids}
        if not grouped:
            return grouped
        stmt = (
            select(SourceRun)
            .where(SourceRun.collection_run_id.in_(grouped), SourceRun.data_mode == mode)
            .order_by(SourceRun.collection_run_id, SourceRun.source)
        )
        for source_run in self._session.scalars(stmt):
            grouped[source_run.collection_run_id].append(source_run)
        return grouped

    def list_source_runs(self, collection_run_id: str, *, data_mode: DataMode | str) -> list[SourceRun]:
        mode = require_data_mode(data_mode)
        stmt = (
            select(SourceRun)
            .where(SourceRun.collection_run_id == collection_run_id, SourceRun.data_mode == mode)
            .order_by(SourceRun.source)
        )
        return list(self._session.scalars(stmt))

    # --- Observaciones originales ----------------------------------------------

    def add_observations(
        self,
        source_run_id: str,
        observations: Iterable[ObservationIn],
        *,
        data_mode: DataMode | str,
        dataset_id: str | None = None,
    ) -> InsertResult:
        """Inserta observaciones ignorando las que ya existen (clave de idempotencia)."""
        mode = require_data_mode(data_mode)
        if mode is DataMode.SIMULATED and not dataset_id:
            raise ValueError("Las observaciones simuladas requieren dataset_id")
        if mode is DataMode.REAL and dataset_id is not None:
            raise ValueError("Las observaciones reales no llevan dataset_id")

        source_run = self.get_source_run(source_run_id, data_mode=mode)
        if source_run is None:
            raise LookupError(
                f"No existe la ejecución {source_run_id!r} con data_mode={mode.value!r}"
            )

        inserted = ignored = 0
        for observation in observations:
            if observation.source is not source_run.source:
                raise ValueError(
                    f"La observación de {observation.source.value!r} no corresponde a la "
                    f"ejecución de {source_run.source.value!r}"
                )
            stmt = (
                sqlite_insert(RawObservation)
                .values(
                    source_run_id=source_run_id,
                    data_mode=mode,
                    dataset_id=dataset_id,
                    **observation.model_dump(),
                )
                .on_conflict_do_nothing()
            )
            if self._session.execute(stmt).rowcount:
                inserted += 1
            else:
                ignored += 1
        return InsertResult(inserted=inserted, ignored=ignored)

    def list_observations(
        self,
        *,
        data_mode: DataMode | str,
        source: Source | None = None,
        metric_key: str | None = None,
        country: str | None | _AnyCountry = ANY_COUNTRY,
        subject_ref: str | None = None,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
        limit: int = 1000,
    ) -> list[RawObservation]:
        mode = require_data_mode(data_mode)
        stmt = select(RawObservation).where(RawObservation.data_mode == mode)
        if source is not None:
            stmt = stmt.where(RawObservation.source == Source(source))
        if metric_key is not None:
            stmt = stmt.where(RawObservation.metric_key == metric_key)
        if country is None:
            stmt = stmt.where(RawObservation.country.is_(None))
        elif not isinstance(country, _AnyCountry):
            stmt = stmt.where(RawObservation.country == country)
        if subject_ref is not None:
            stmt = stmt.where(RawObservation.subject_ref == subject_ref)
        if period_from is not None:
            stmt = stmt.where(RawObservation.period_start >= period_from)
        if period_to is not None:
            stmt = stmt.where(RawObservation.period_start < period_to)
        stmt = stmt.order_by(RawObservation.period_start, RawObservation.id).limit(_check_limit(limit))
        return list(self._session.scalars(stmt))


def _check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise ValueError(f"limit debe estar entre 1 y {MAX_LIST_LIMIT}")
    return limit
