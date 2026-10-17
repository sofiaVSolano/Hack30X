"""Tareas deterministas de la oficina (E10): ``trend_hunter`` y ``supervisor``.

Sin modelos de lenguaje. Cada tarea solo reutiliza servicios existentes y devuelve lo que
esos servicios informan. Ver ``docs/e10-oficina-agentes.md``.

Solo las tareas de ``TASKS`` pueden ejecutarse; el cliente nunca elige funciones.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date
from functools import partial
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import AgentTask, AgentTaskContext
from app.modules.detectar.agents.definitions import ImplementationStatus
from app.modules.detectar.agents.registry import AgentRegistry
from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.connectors.params import GdeltParams, WikimediaParams
from app.modules.detectar.ingestion.collection import (
    CollectionReport,
    CollectionService,
)
from app.modules.detectar.metrics.definitions import RULES_VERSION as METRICS_VERSION
from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.stages.rules import PARAMS as STAGE_PARAMS
from app.modules.detectar.stages.rules import RULES_VERSION as STAGES_VERSION
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRunStatus,
    CollectionStatus,
    DataMode,
    Source,
    SourceRunStatus,
    TrendStage,
)
from app.modules.detectar.timeutil import format_utc
from app.modules.detectar.topics.linker import TopicLinker

NORMALIZATION_BATCH = 5000
NORMALIZATION_MAX_BATCHES = 20

FIXED_LIMITATIONS = (
    f"Reglas de etapas {STAGES_VERSION} provisionales y no calibradas.",
    "La etapa 'saturada' no se asigna: no hay datos de oferta de contenido.",
)
GDELT_LIMITATION = "GDELT no está validada con la fuente real: sus métricas tienen source_validated=false."


class TaskObjectiveError(RuntimeError):
    """La tarea no pudo cumplir su objetivo; el detalle explica por qué."""


# --- parámetros internos (la API traduce el contrato público en español) -------------------


class CollectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sources: tuple[Source, ...] = Field(min_length=1)
    countries: tuple[str, ...] = ()
    wikimedia: WikimediaParams | None = None
    gdelt: GdeltParams | None = None


class TrendHunterParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: date
    collection: CollectionPlan | None = None


class SupervisorParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    per_agent_limit: int = Field(default=20, ge=1, le=100)


@dataclass(frozen=True)
class TaskDependencies:
    session_factory: sessionmaker[Session]
    collection_service: CollectionService
    registry: AgentRegistry
    clock: Clock = utc_now


# --- trend_hunter -------------------------------------------------------------------------


def _collection_summary(report: CollectionReport) -> dict[str, Any]:
    return {
        "ejecutada": True,
        "run_id": report.run_id,
        "estado": report.status.value,
        "fuentes": {
            s.source.value: {
                "estado": s.status.value,
                "observaciones_nuevas": s.inserted,
                "observaciones_repetidas": s.ignored,
                "llamadas_http": s.http_calls,
                "codigo_error": s.error_code,
            }
            for s in report.sources
        },
    }


async def run_trend_hunter(deps: TaskDependencies, context: AgentTaskContext) -> dict[str, Any]:
    params = TrendHunterParams.model_validate(context.params)
    mode = context.data_mode
    if params.as_of >= deps.clock().astimezone(UTC).date():
        raise ValueError("fecha_referencia debe ser un día cerrado (anterior a hoy en UTC)")
    if params.collection is not None and mode is not DataMode.REAL:
        raise ValueError("Solo se puede recolectar en modo real: los conectores producen datos reales")

    limitations: list[str] = []
    steps: dict[str, Any] = {}
    involves_gdelt = False

    # 1. Recolección (opcional).
    if params.collection is None:
        steps["recoleccion"] = {"ejecutada": False, "motivo": "no solicitada: se procesan datos ya guardados"}
    else:
        plan = params.collection
        involves_gdelt = Source.GDELT in plan.sources
        report = await deps.collection_service.collect(
            plan.sources, plan.countries, wikimedia=plan.wikimedia, gdelt=plan.gdelt
        )
        steps["recoleccion"] = _collection_summary(report)
        if report.status is CollectionStatus.FAILED:
            raise TaskObjectiveError(
                f"collection_failed: la recolección {report.run_id} falló en todas las fuentes"
            )
        failed = [s.source.value for s in report.sources if s.status is not SourceRunStatus.OK]
        if failed:
            limitations.append(f"Fuentes con fallos o resultados parciales: {', '.join(failed)}.")

    # 2. Normalización por lotes (cada lote en su transacción).
    processed = created = 0
    by_status: Counter[str] = Counter()
    pending = False
    for batch in range(NORMALIZATION_MAX_BATCHES):
        with deps.session_factory() as session, session.begin():
            report = TopicLinker(session, clock=deps.clock).process(data_mode=mode, limit=NORMALIZATION_BATCH)
        processed += report.processed
        created += report.topics_created
        by_status.update(report.by_status)
        if report.processed < NORMALIZATION_BATCH:
            break
        pending = batch == NORMALIZATION_MAX_BATCHES - 1
    steps["normalizacion"] = {
        "procesadas": processed,
        "temas_creados": created,
        "por_estado": dict(by_status),
        "pendientes": pending,
    }
    if pending:
        limitations.append("Quedaron observaciones sin normalizar: se alcanzó el máximo de lotes.")
    if by_status.get("needs_review"):
        limitations.append(f"{by_status['needs_review']} vínculos requieren revisión humana.")

    # 3. Métricas.
    with deps.session_factory() as session, session.begin():
        metrics = MetricsService(session, clock=deps.clock).compute(data_mode=mode, as_of=params.as_of)
    steps["metricas"] = {
        "version": METRICS_VERSION,
        "valores_escritos": metrics.written,
        "por_estado": dict(metrics.by_status),
        "por_metrica": dict(metrics.by_metric),
    }
    involves_gdelt = involves_gdelt or any(key.startswith("gdelt_") for key in metrics.by_metric)
    if not metrics.by_status.get("ok"):
        limitations.append("Ninguna métrica pudo calcularse con datos suficientes para esa fecha.")

    # 4. Clasificación.
    with deps.session_factory() as session, session.begin():
        stages = ClassificationService(session, clock=deps.clock).classify(data_mode=mode, as_of=params.as_of)
    steps["clasificacion"] = {
        "version": STAGES_VERSION,
        "calibrada": bool(STAGE_PARAMS["calibrated"]),
        "creadas": stages.created,
        "sin_cambios": stages.unchanged,
        "reemplazadas": stages.superseded,
        "por_etapa": dict(stages.by_stage),
    }
    supported = {k: v for k, v in stages.by_stage.items() if k != TrendStage.DATOS_INSUFICIENTES.value}
    if not supported:
        limitations.append("Ningún tema tiene una etapa sostenida por evidencia suficiente.")
    if involves_gdelt:
        limitations.append(GDELT_LIMITATION)

    return {
        "agente": context.agent_id,
        "version_resumen": "trend_hunter-v1",
        "data_mode": mode.value,
        "fecha_referencia": params.as_of.isoformat(),
        "estado_objetivo": "con_limitaciones" if limitations else "completo",
        "pasos": steps,
        "limitaciones": [*limitations, *FIXED_LIMITATIONS],
    }


# --- supervisor -----------------------------------------------------------------------------


async def run_supervisor(deps: TaskDependencies, context: AgentTaskContext) -> dict[str, Any]:
    params = SupervisorParams.model_validate(context.params)
    mode = context.data_mode
    agents: dict[str, Any] = {}
    totals: Counter[str] = Counter()
    without_runs: list[str] = []
    with deps.session_factory() as session:
        repo = AgentRunRepository(session)
        for definition in deps.registry.all():
            if definition.id == context.agent_id:
                continue  # no se supervisa a sí mismo: su propia ejecución sigue en curso
            runs = repo.list_runs(data_mode=mode, agent_id=definition.id, limit=params.per_agent_limit)
            counts = Counter(run.status.value for run in runs)
            totals.update(counts)
            last = runs[0] if runs else None
            if last is None:
                without_runs.append(definition.id)
            agents[definition.id] = {
                "definido": True,
                "implementado": definition.implementation_status is ImplementationStatus.AVAILABLE,
                "ejecuciones_consideradas": len(runs),
                "conteo_por_estado": {status.value: counts.get(status.value, 0) for status in AgentRunStatus},
                "ultima_ejecucion": None
                if last is None
                else {
                    "id": last.id,
                    "estado": last.status.value,
                    "solicitado": format_utc(last.requested_at),
                    "fin": format_utc(last.finished_at) if last.finished_at else None,
                    "codigo_error": last.error_code,
                },
            }
    limitations = [
        f"Solo se consideran las últimas {params.per_agent_limit} ejecuciones de cada agente.",
        "El supervisor no se incluye a sí mismo.",
        "Resumen supervisor-v1 provisional: el formato consolidado está pendiente de acordar con el equipo.",
    ]
    return {
        "agente": context.agent_id,
        "version_resumen": "supervisor-v1",
        "data_mode": mode.value,
        "sin_actividad_registrada": not totals,
        "agentes": agents,
        "agentes_sin_ejecuciones": without_runs,
        "totales_por_estado": {status.value: totals.get(status.value, 0) for status in AgentRunStatus},
        "limitaciones": limitations,
    }


# --- registro fijo de tareas ---------------------------------------------------------------

TASK_PARAMS: dict[str, type[BaseModel]] = {
    "trend_hunter": TrendHunterParams,
    "supervisor": SupervisorParams,
}


def build_tasks(deps: TaskDependencies) -> dict[str, AgentTask]:
    """Mapa fijo id -> tarea. Es la única forma de ejecutar código desde la API."""
    return {
        "trend_hunter": partial(run_trend_hunter, deps),
        "supervisor": partial(run_supervisor, deps),
    }
