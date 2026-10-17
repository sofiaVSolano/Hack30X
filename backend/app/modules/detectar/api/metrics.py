"""Métricas por tema y fuente (E8).

Todas las rutas exigen el token administrativo. Las lecturas no calculan ni escriben;
el cálculo ocurre solo con ``POST /metricas/calculos``, con modo y fecha explícitos.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.api.dependencies import get_session_factory, require_admin
from app.modules.detectar.api.errors import DetectarError, FieldError
from app.modules.detectar.metrics.definitions import (
    BY_KEY,
    DEFINITIONS,
    PARAMS,
    RULES_VERSION,
)
from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.storage.metrics import MetricRepository
from app.modules.detectar.storage.models import (
    DataMode,
    MetricStatus,
    MetricUnit,
    MetricValue,
    Source,
)
from app.modules.detectar.timeutil import format_utc

metrics_router = APIRouter(tags=["detectar"], dependencies=[Depends(require_admin)])

Mode = Literal["real", "simulated"]
TOPIC_PATTERN = r"^tpc_[0-9a-f]{16}$"


class DefinitionsOut(BaseModel):
    version: str
    parametros: dict[str, object]
    metricas: list[dict[str, str]]


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode  # obligatorio
    fecha_referencia: date  # último día cerrado incluido (as_of)
    temas: list[Annotated[str, Field(pattern=TOPIC_PATTERN)]] | None = Field(
        default=None, min_length=1, max_length=100
    )


class CalculationResult(BaseModel):
    data_mode: DataMode
    fecha_referencia: date
    version: str
    valores_escritos: int
    por_estado: dict[str, int]
    por_metrica: dict[str, int]
    observaciones_omitidas: dict[str, int]


class MetricOut(BaseModel):
    tema_id: str
    data_mode: DataMode
    fuente: Source
    ambito: str
    metrica: str
    unidad: MetricUnit
    valor: float | None
    estado: MetricStatus
    motivo: str | None
    ventana_dias: int
    periodo_inicio: str
    periodo_fin: str
    fecha_referencia: str
    calculado: str
    version: str
    fuente_validada: bool
    observaciones_usadas: int
    detalles: dict[str, object]


class MetricPage(BaseModel):
    data_mode: DataMode
    total: int
    limite: int
    desplazamiento: int
    items: list[MetricOut]


def _metric_out(value: MetricValue) -> MetricOut:
    return MetricOut(
        tema_id=value.topic_id,
        data_mode=value.data_mode,
        fuente=value.source,
        ambito=value.scope,
        metrica=value.metric_key,
        unidad=value.unit,
        valor=value.value,
        estado=value.status,
        motivo=value.reason,
        ventana_dias=value.window_days,
        periodo_inicio=format_utc(value.period_start),
        periodo_fin=format_utc(value.period_end),
        fecha_referencia=value.as_of.date().isoformat(),
        calculado=format_utc(value.computed_at),
        version=value.rules_version,
        fuente_validada=value.source_validated,
        observaciones_usadas=int(value.inputs.get("observation_count", 0)),
        detalles=value.details,
    )


@metrics_router.get("/metricas/definiciones", response_model=DefinitionsOut)
def definitions() -> DefinitionsOut:
    return DefinitionsOut(
        version=RULES_VERSION,
        parametros=dict(PARAMS),
        metricas=[d.as_dict() for d in DEFINITIONS],
    )


@metrics_router.post("/metricas/calculos", response_model=CalculationResult)
def calculate(
    body: CalculationRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> CalculationResult:
    """Calcula y guarda las métricas de la fecha indicada. Síncrono e idempotente."""
    if body.fecha_referencia >= datetime.now(UTC).date():
        raise DetectarError(
            code="invalid_reference_date",
            status=422,
            title="Fecha no cerrada",
            detail="fecha_referencia debe ser anterior a hoy (UTC).",
            errors=[FieldError(campo="body.fecha_referencia", mensaje="día no cerrado")],
        )
    with session_factory() as session, session.begin():
        report = MetricsService(session).compute(
            data_mode=body.data_mode, as_of=body.fecha_referencia, topic_ids=body.temas
        )
    return CalculationResult(
        data_mode=report.data_mode,
        fecha_referencia=report.as_of,
        version=report.rules_version,
        valores_escritos=report.written,
        por_estado=dict(report.by_status),
        por_metrica=dict(report.by_metric),
        observaciones_omitidas=dict(report.skipped_observations),
    )


@metrics_router.get("/metricas", response_model=MetricPage)
def list_metrics(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    tema_id: Annotated[str | None, Query(pattern=TOPIC_PATTERN)] = None,
    fuente: Annotated[Source | None, Query()] = None,
    metrica: Annotated[str | None, Query(max_length=64)] = None,
    estado: Annotated[MetricStatus | None, Query()] = None,
    fecha_referencia: Annotated[date | None, Query()] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> MetricPage:
    """Solo lectura: devuelve lo calculado; nunca calcula."""
    if metrica is not None and metrica not in BY_KEY:
        raise DetectarError(
            code="unknown_metric",
            status=422,
            title="Métrica desconocida",
            detail="Consulte /metricas/definiciones.",
            errors=[FieldError(campo="query.metrica", mensaje="no existe")],
        )
    filters = {
        "data_mode": data_mode,
        "topic_id": tema_id,
        "source": fuente,
        "metric_key": metrica,
        "status": estado,
        "as_of": fecha_referencia,
    }
    with session_factory() as session:
        repo = MetricRepository(session)
        values = repo.list_values(**filters, limit=limite, offset=desplazamiento)
        return MetricPage(
            data_mode=DataMode(data_mode),
            total=repo.count_values(**filters),
            limite=limite,
            desplazamiento=desplazamiento,
            items=[_metric_out(v) for v in values],
        )
