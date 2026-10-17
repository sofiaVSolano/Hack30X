"""Clasificación por etapas (E9).

Todas las rutas exigen el token administrativo. La consulta lee lo persistido y nunca
clasifica; la clasificación ocurre solo con ``POST /clasificaciones/calculos``.
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.api.dependencies import get_session_factory, require_admin
from app.modules.detectar.api.errors import DetectarError, FieldError
from app.modules.detectar.stages.rules import (
    METRICS_RULES_VERSION,
    PARAMS,
    RULES_VERSION,
    SOURCE_CAPABILITIES,
    STAGE_DEFINITIONS,
    STAGE_METRICS,
    params_sha256,
)
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.classifications import ClassificationRepository
from app.modules.detectar.storage.models import (
    ClassificationEvidence,
    DataMode,
    EvidenceRole,
    RulesVersion,
    Source,
    TrendClassification,
    TrendStage,
)
from app.modules.detectar.timeutil import format_utc

classifications_router = APIRouter(tags=["detectar"], dependencies=[Depends(require_admin)])

Mode = Literal["real", "simulated"]
TOPIC_PATTERN = r"^tpc_[0-9a-f]{16}$"


class RulesOut(BaseModel):
    version: str
    version_metricas: str
    provisional: bool
    calibrado: bool
    parametros: dict[str, object]
    parametros_sha256: str
    registrada: bool
    etapas: dict[str, str]
    capacidades_por_fuente: dict[str, list[str]]
    metricas_usadas: dict[str, list[str]]


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode
    fecha_referencia: date
    temas: list[Annotated[str, Field(pattern=TOPIC_PATTERN)]] | None = Field(default=None, min_length=1, max_length=100)


class CalculationResult(BaseModel):
    data_mode: DataMode
    fecha_referencia: date
    version: str
    creadas: int
    sin_cambios: int
    reemplazadas: int
    por_etapa: dict[str, int]


class EvidenceOut(BaseModel):
    fuente: Source
    rol: EvidenceRole
    fuente_validada: bool
    etapa_propuesta: TrendStage | None
    motivo: str
    ambitos: list[dict[str, object]]


class ClassificationOut(BaseModel):
    id: int
    tema_id: str
    data_mode: DataMode
    etapa: TrendStage
    motivo: str | None
    fecha_referencia: str
    calculado: str
    version: str
    version_metricas: str
    calibrado: bool
    reemplazada: str | None
    evidencia: list[EvidenceOut]
    metricas_consideradas: list[dict[str, object]]
    explicacion: dict[str, object]


class ClassificationPage(BaseModel):
    data_mode: DataMode
    total: int
    limite: int
    desplazamiento: int
    items: list[ClassificationOut]


def _out(row: TrendClassification, evidence: list[ClassificationEvidence]) -> ClassificationOut:
    return ClassificationOut(
        id=row.id,
        tema_id=row.topic_id,
        data_mode=row.data_mode,
        etapa=row.stage,
        motivo=row.reason,
        fecha_referencia=row.as_of.date().isoformat(),
        calculado=format_utc(row.computed_at),
        version=row.rules_version,
        version_metricas=row.metrics_rules_version,
        calibrado=row.calibrated,
        reemplazada=format_utc(row.superseded_at) if row.superseded_at else None,
        evidencia=[
            EvidenceOut(
                fuente=e.source,
                rol=e.role,
                fuente_validada=e.source_validated,
                etapa_propuesta=e.proposed_stage,
                motivo=e.reason,
                ambitos=e.scopes,
            )
            for e in evidence
        ],
        metricas_consideradas=row.metrics_considered,
        explicacion=row.explanation,
    )


@classifications_router.get("/clasificaciones/reglas", response_model=RulesOut)
def rules(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> RulesOut:
    with session_factory() as session:
        # rules_versions es común a ambos modos: no contiene datos reales ni simulados.
        registered = session.get(RulesVersion, RULES_VERSION)
    return RulesOut(
        version=RULES_VERSION,
        version_metricas=METRICS_RULES_VERSION,
        provisional=not PARAMS["calibrated"],
        calibrado=bool(PARAMS["calibrated"]),
        parametros=dict(PARAMS),
        parametros_sha256=params_sha256(),
        registrada=registered is not None,
        etapas={stage.value: text for stage, text in STAGE_DEFINITIONS.items()},
        capacidades_por_fuente={s.value: [st.value for st in stages] for s, stages in SOURCE_CAPABILITIES.items()},
        metricas_usadas={s.value: list(keys) for s, keys in STAGE_METRICS.items()},
    )


@classifications_router.post("/clasificaciones/calculos", response_model=CalculationResult)
def calculate(
    body: CalculationRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> CalculationResult:
    """Clasifica con las métricas E8 persistidas de esa fecha. Síncrono e idempotente."""
    if body.fecha_referencia >= datetime.now(UTC).date():
        raise DetectarError(
            code="invalid_reference_date",
            status=422,
            title="Fecha no cerrada",
            detail="fecha_referencia debe ser anterior a hoy (UTC).",
            errors=[FieldError(campo="body.fecha_referencia", mensaje="día no cerrado")],
        )
    with session_factory() as session, session.begin():
        report = ClassificationService(session).classify(
            data_mode=body.data_mode, as_of=body.fecha_referencia, topic_ids=body.temas
        )
    return CalculationResult(
        data_mode=report.data_mode,
        fecha_referencia=report.as_of,
        version=report.rules_version,
        creadas=report.created,
        sin_cambios=report.unchanged,
        reemplazadas=report.superseded,
        por_etapa=dict(report.by_stage),
    )


@classifications_router.get("/clasificaciones", response_model=ClassificationPage)
def list_classifications(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    tema_id: Annotated[str | None, Query(pattern=TOPIC_PATTERN)] = None,
    fuente: Annotated[Source | None, Query()] = None,
    etapa: Annotated[TrendStage | None, Query()] = None,
    version: Annotated[str | None, Query(max_length=40)] = None,
    fecha_referencia: Annotated[date | None, Query()] = None,
    incluir_reemplazadas: Annotated[bool, Query()] = False,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> ClassificationPage:
    """Solo lectura. ``fuente`` filtra por fuentes que aportaron evidencia (no excluidas)."""
    filters = {
        "data_mode": data_mode,
        "topic_id": tema_id,
        "source": fuente,
        "stage": etapa,
        "rules_version": version,
        "as_of": fecha_referencia,
        "include_superseded": incluir_reemplazadas,
    }
    with session_factory() as session:
        repo = ClassificationRepository(session)
        rows = repo.list_classifications(**filters, limit=limite, offset=desplazamiento)
        evidence = repo.evidence_for([r.id for r in rows], data_mode=data_mode)
        return ClassificationPage(
            data_mode=DataMode(data_mode),
            total=repo.count_classifications(**filters),
            limite=limite,
            desplazamiento=desplazamiento,
            items=[_out(r, evidence.get(r.id, [])) for r in rows],
        )
