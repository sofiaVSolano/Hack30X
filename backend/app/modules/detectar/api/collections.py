"""Recolecciones reales y protegidas.

- ``POST /recolecciones`` es SÍNCRONO: la respuesta llega cuando la recolección terminó y
  quedó registrada en SQLite. Devuelve 201 con el estado real (``ok``, ``partial`` o
  ``failed``); un 201 no implica éxito: el cliente debe leer ``estado``.
- ``GET /recolecciones/{run_id}`` (E5) es de solo lectura y devuelve lo registrado, sin
  reconstruir datos que no se guardaron (por ejemplo, las observaciones repetidas que
  informa el POST no se almacenan y por eso no aparecen aquí).
"""

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.api.dependencies import (
    get_collection_service,
    get_session_factory,
    require_admin,
)
from app.modules.detectar.api.errors import DetectarError, FieldError
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.connectors.params import (
    GDELT_MAX_LOOKBACK_DAYS,
    GdeltParams,
    WikimediaParams,
)
from app.modules.detectar.ingestion.collection import (
    CollectionInProgressError,
    CollectionReport,
    CollectionService,
    SourceNotEnabledError,
    source_availability,
)
from app.modules.detectar.storage.models import (
    CollectionStatus,
    DataMode,
    Source,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository
from app.modules.detectar.timeutil import format_utc

logger = logging.getLogger(__name__)

collections_router = APIRouter(tags=["detectar"])

CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
RUN_ID_PATTERN = r"^run_[0-9a-f]{32}$"


class WikimediaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    articulos: list[str] = Field(min_length=1, max_length=100)
    desde: date
    hasta: date
    # Sin valor: se usan los proyectos de DETECTAR_WIKIMEDIA_PROJECTS.
    proyectos: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def _check(self) -> "WikimediaRequest":
        self.to_params()  # valida títulos, proyectos y fechas con las reglas del conector
        return self

    def to_params(self) -> WikimediaParams:
        try:
            return WikimediaParams(
                articles=tuple(self.articulos),
                start=self.desde,
                end=self.hasta,
                projects=tuple(self.proyectos or ()),
            )
        except ValidationError as exc:
            raise ValueError("; ".join(err["msg"] for err in exc.errors())) from None


class GdeltRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminos: list[str] = Field(min_length=1, max_length=20)
    desde: date
    hasta: date
    # Idioma original de los artículos (filtro "sourcelang:" de GDELT).
    idioma_fuente: Literal["spanish", "english", "portuguese"] | None = None
    # País de los MEDIOS que publican (no de la audiencia). Sin valor: sin filtro.
    paises_medios: list[str] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> "GdeltRequest":
        self.to_params()
        return self

    def to_params(self) -> GdeltParams:
        try:
            return GdeltParams(
                terms=tuple(self.terminos),
                start=self.desde,
                end=self.hasta,
                source_language=self.idioma_fuente,
                source_countries=tuple(self.paises_medios or ()),
            )
        except ValidationError as exc:
            raise ValueError("; ".join(err["msg"] for err in exc.errors())) from None


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuentes: list[Source] = Field(min_length=1, max_length=len(Source))
    # Solo para google_trends_rss. Sin valor: se usan los países configurados.
    paises: list[CountryCode] | None = Field(default=None, min_length=1, max_length=30)
    # Obligatorio si y solo si se solicita wikimedia.
    wikimedia: WikimediaRequest | None = None
    # Obligatorio si y solo si se solicita gdelt.
    gdelt: GdeltRequest | None = None

    @field_validator("fuentes", "paises")
    @classmethod
    def _no_duplicates(cls, value: list | None) -> list | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Hay valores repetidos")
        return value


class SourceError(BaseModel):
    codigo: str
    detalle: str | None


class SourceResult(BaseModel):
    fuente: Source
    estado: SourceRunStatus
    observaciones_nuevas: int
    observaciones_repetidas: int
    llamadas_http: int
    error: SourceError | None


class CollectionResponse(BaseModel):
    run_id: str
    data_mode: Literal["real"]
    sincrono: Literal[True]
    estado: CollectionStatus
    inicio: str
    fin: str
    paises: list[str]
    fuentes: list[SourceResult]


class StoredSourceResult(BaseModel):
    fuente: Source
    estado: SourceRunStatus
    observaciones_nuevas: int
    llamadas_http: int
    inicio: str | None
    fin: str | None
    error: SourceError | None


class CollectionDetail(BaseModel):
    run_id: str
    data_mode: DataMode
    estado: CollectionStatus
    creado: str
    inicio: str | None
    fin: str | None
    fuentes_solicitadas: list[str]
    paises: list[str]
    # Parámetros registrados de la solicitud; null en recolecciones anteriores a E5.
    parametros: dict[str, object] | None
    fuentes: list[StoredSourceResult]


def _error(code: str | None, detail: str | None) -> SourceError | None:
    return SourceError(codigo=code, detalle=detail) if code else None


def _optional_utc(moment: datetime | None) -> str | None:
    return format_utc(moment) if moment else None


def _response(report: CollectionReport) -> CollectionResponse:
    return CollectionResponse(
        run_id=report.run_id,
        data_mode="real",
        sincrono=True,
        estado=report.status,
        inicio=format_utc(report.started_at),
        fin=format_utc(report.finished_at),
        paises=list(report.countries),
        fuentes=[
            SourceResult(
                fuente=source.source,
                estado=source.status,
                observaciones_nuevas=source.inserted,
                observaciones_repetidas=source.ignored,
                llamadas_http=source.http_calls,
                error=_error(source.error_code, source.error_detail),
            )
            for source in report.sources
        ],
    )


def _validation_error(code: str, detail: str, field: str, message: str) -> DetectarError:
    return DetectarError(
        code=code,
        status=422,
        title="Parámetros inválidos",
        detail=detail,
        errors=[FieldError(campo=field, mensaje=message)],
    )


def _check_wikimedia(body: CollectionRequest, settings: DetectarSettings) -> WikimediaParams | None:
    wants_wikimedia = Source.WIKIMEDIA in body.fuentes
    if body.wikimedia is None:
        if wants_wikimedia:
            raise _validation_error(
                "missing_parameters",
                "Wikimedia requiere artículos y un intervalo de fechas.",
                "body.wikimedia",
                "obligatorio con la fuente wikimedia",
            )
        return None
    if not wants_wikimedia:
        raise _validation_error(
            "parameters_not_applicable",
            "Se enviaron parámetros de Wikimedia sin solicitar esa fuente.",
            "body.wikimedia",
            "solo aplica a la fuente wikimedia",
        )
    params = body.wikimedia.to_params()
    if params.end >= datetime.now(UTC).date():
        raise _validation_error(
            "invalid_interval",
            "hasta debe ser anterior a hoy (UTC): el día en curso todavía no está cerrado.",
            "body.wikimedia.hasta",
            "fecha no cerrada",
        )
    if params.days > settings.wikimedia_max_days:
        raise _validation_error(
            "invalid_interval",
            f"El intervalo máximo es de {settings.wikimedia_max_days} días.",
            "body.wikimedia",
            "intervalo demasiado largo",
        )
    if len(params.articles) > settings.wikimedia_max_articles:
        raise _validation_error(
            "too_many_articles",
            f"Se admiten como máximo {settings.wikimedia_max_articles} artículos.",
            "body.wikimedia.articulos",
            "demasiados artículos",
        )
    not_allowed = [p for p in params.projects if p not in settings.wikimedia_projects]
    if not_allowed:
        raise _validation_error(
            "project_not_allowed",
            f"Proyectos no configurados: {', '.join(not_allowed)}",
            "body.wikimedia.proyectos",
            "solo se admiten los proyectos de DETECTAR_WIKIMEDIA_PROJECTS",
        )
    return params


def _check_gdelt(body: CollectionRequest, settings: DetectarSettings) -> GdeltParams | None:
    wants_gdelt = Source.GDELT in body.fuentes
    if body.gdelt is None:
        if wants_gdelt:
            raise _validation_error(
                "missing_parameters",
                "GDELT requiere términos y un intervalo de fechas.",
                "body.gdelt",
                "obligatorio con la fuente gdelt",
            )
        return None
    if not wants_gdelt:
        raise _validation_error(
            "parameters_not_applicable",
            "Se enviaron parámetros de GDELT sin solicitar esa fuente.",
            "body.gdelt",
            "solo aplica a la fuente gdelt",
        )
    params = body.gdelt.to_params()
    today = datetime.now(UTC).date()
    if params.end >= today:
        raise _validation_error(
            "invalid_interval",
            "hasta debe ser anterior a hoy (UTC).",
            "body.gdelt.hasta",
            "fecha no cerrada",
        )
    if (today - params.start).days > GDELT_MAX_LOOKBACK_DAYS:
        raise _validation_error(
            "invalid_interval",
            f"GDELT solo cubre los últimos 3 meses: desde debe estar dentro de los últimos "
            f"{GDELT_MAX_LOOKBACK_DAYS} días.",
            "body.gdelt.desde",
            "fuera de la ventana de GDELT",
        )
    if len(params.queries()) > settings.gdelt_max_requests:
        raise _validation_error(
            "too_many_requests_needed",
            f"Términos x países de medios supera {settings.gdelt_max_requests} solicitudes.",
            "body.gdelt",
            "reduzca términos o países",
        )
    return params


def validate_collection_request(
    body: CollectionRequest, settings: DetectarSettings
) -> tuple[list[Source], list[str], WikimediaParams | None, GdeltParams | None]:
    """Validación de una solicitud de recolección (E10: compartida con ``trend_hunter``).

    Lanza ``DetectarError`` 422 con el mismo formato que ``POST /recolecciones``.
    """
    reasons = source_availability(settings)
    not_enabled = [f"{s.value} ({reasons[s]})" for s in body.fuentes if reasons[s] is not None]
    if not_enabled:
        raise _validation_error(
            "source_not_enabled",
            "Fuentes no habilitadas: " + "; ".join(not_enabled),
            "body.fuentes",
            "fuente no habilitada",
        )

    wants_trends = Source.GOOGLE_TRENDS_RSS in body.fuentes
    if body.paises and not wants_trends:
        raise _validation_error(
            "parameters_not_applicable",
            "paises solo aplica a google_trends_rss.",
            "body.paises",
            "no aplica a las fuentes solicitadas",
        )
    countries = list(body.paises) if body.paises else (list(settings.countries) if wants_trends else [])
    not_allowed = [country for country in countries if country not in settings.countries]
    if not_allowed:
        raise _validation_error(
            "country_not_allowed",
            f"Países no configurados: {', '.join(not_allowed)}",
            "body.paises",
            "solo se admiten los países de DETECTAR_COUNTRIES",
        )
    if len(countries) > settings.max_countries_per_request:
        raise _validation_error(
            "too_many_countries",
            f"Se admiten como máximo {settings.max_countries_per_request} países por solicitud.",
            "body.paises",
            "demasiados países",
        )
    wikimedia = _check_wikimedia(body, settings)
    gdelt = _check_gdelt(body, settings)

    return list(body.fuentes), countries, wikimedia, gdelt


@collections_router.post(
    "/recolecciones",
    status_code=201,
    response_model=CollectionResponse,
    dependencies=[Depends(require_admin)],
)
async def start_collection(
    body: CollectionRequest,
    settings: Annotated[DetectarSettings, Depends(get_settings)],
    service: Annotated[CollectionService, Depends(get_collection_service)],
) -> CollectionResponse:
    sources, countries, wikimedia, gdelt = validate_collection_request(body, settings)

    try:
        report = await service.collect(sources, countries, wikimedia=wikimedia, gdelt=gdelt)
    except SourceNotEnabledError as exc:
        raise _validation_error(
            "source_not_enabled", str(exc), "body.fuentes", "fuente no habilitada"
        ) from None
    except CollectionInProgressError:
        raise DetectarError(
            code="collection_in_progress",
            status=409,
            title="Recolección en curso",
            detail="Ya hay una recolección real en curso; inténtelo cuando termine.",
        ) from None
    except Exception as exc:  # noqa: BLE001 - se responde un error genérico sin detalles internos
        logger.error("Error inesperado en POST /recolecciones: %s", type(exc).__name__)
        raise DetectarError(
            code="internal_error",
            status=500,
            title="Error interno",
            detail="La recolección no pudo completarse y quedó registrada como fallida.",
        ) from None
    return _response(report)


@collections_router.get(
    "/recolecciones/{run_id}",
    response_model=CollectionDetail,
    dependencies=[Depends(require_admin)],
)
def get_collection(
    run_id: Annotated[str, Path(pattern=RUN_ID_PATTERN)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Literal["real", "simulated"], Query()] = "real",
) -> CollectionDetail:
    """Solo lectura: devuelve la recolección y lo registrado para cada fuente."""
    with session_factory() as session:
        repo = DetectarRepository(session)
        run = repo.get_collection_run(run_id, data_mode=data_mode)
        if run is None:
            raise DetectarError(
                code="not_found",
                status=404,
                title="Recolección no encontrada",
                detail="No existe una recolección con ese identificador y data_mode.",
            )
        source_runs = repo.list_source_runs(run_id, data_mode=data_mode)
        return CollectionDetail(
            run_id=run.id,
            data_mode=run.data_mode,
            estado=run.status,
            creado=format_utc(run.created_at),
            inicio=_optional_utc(run.started_at),
            fin=_optional_utc(run.finished_at),
            fuentes_solicitadas=list(run.requested_sources),
            paises=list(run.requested_countries),
            parametros=run.request_params,
            fuentes=[
                StoredSourceResult(
                    fuente=source_run.source,
                    estado=source_run.status,
                    observaciones_nuevas=source_run.items,
                    llamadas_http=source_run.http_calls,
                    inicio=_optional_utc(source_run.started_at),
                    fin=_optional_utc(source_run.finished_at),
                    error=_error(source_run.error_code, source_run.error_detail),
                )
                for source_run in source_runs
            ],
        )


# --- E6: listado de recolecciones (solo lectura) -------------------------------------

MAX_PAGE_SIZE = 100
MAX_OFFSET = 10_000


class SourceSummary(BaseModel):
    fuente: Source
    estado: SourceRunStatus
    observaciones_nuevas: int
    codigo_error: str | None


class CollectionSummary(BaseModel):
    run_id: str
    data_mode: DataMode
    estado: CollectionStatus
    creado: str
    inicio: str | None
    fin: str | None
    fuentes_solicitadas: list[str]
    paises: list[str]
    fuentes: list[SourceSummary]


class CollectionPage(BaseModel):
    data_mode: DataMode
    estado: CollectionStatus | None
    total: int
    limite: int
    desplazamiento: int
    items: list[CollectionSummary]


@collections_router.get(
    "/recolecciones",
    response_model=CollectionPage,
    dependencies=[Depends(require_admin)],
)
def list_collections(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Literal["real", "simulated"], Query()] = "real",
    estado: Annotated[CollectionStatus | None, Query()] = None,
    limite: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> CollectionPage:
    """Solo lectura. Un modo por consulta: nunca mezcla datos reales y simulados."""
    with session_factory() as session:
        repo = DetectarRepository(session)
        runs = repo.list_collection_runs(
            data_mode=data_mode, status=estado, limit=limite, offset=desplazamiento
        )
        total = repo.count_collection_runs(data_mode=data_mode, status=estado)
        by_run = repo.list_source_runs_for([run.id for run in runs], data_mode=data_mode)
        return CollectionPage(
            data_mode=DataMode(data_mode),
            estado=estado,
            total=total,
            limite=limite,
            desplazamiento=desplazamiento,
            items=[
                CollectionSummary(
                    run_id=run.id,
                    data_mode=run.data_mode,
                    estado=run.status,
                    creado=format_utc(run.created_at),
                    inicio=_optional_utc(run.started_at),
                    fin=_optional_utc(run.finished_at),
                    fuentes_solicitadas=list(run.requested_sources),
                    paises=list(run.requested_countries),
                    fuentes=[
                        SourceSummary(
                            fuente=source_run.source,
                            estado=source_run.status,
                            observaciones_nuevas=source_run.items,
                            codigo_error=source_run.error_code,
                        )
                        for source_run in by_run[run.id]
                    ],
                )
                for run in runs
            ],
        )
