"""Agentes de la oficina: lectura (E6) y solicitud de ejecuciones (E10).

Las lecturas combinan las definiciones declarativas con las ejecuciones registradas en
``agent_runs``; no ejecutan agentes ni derivan actividad de temporizadores.
``POST /agentes/{agent_id}/ejecuciones`` (E10) ejecuta, mediante el coordinador, solo
tareas del mapa fijo ``agents/tasks.py``; ver ``docs/e10-oficina-agentes.md``.

Distingue tres hechos independientes:

- ``definido``: el agente existe en el registro declarativo (siempre verdadero aquí);
- ``implementado``: su tarea está disponible (``implementation_status == available``);
- ``ejecutado``: existe al menos una ejecución registrada en el ``data_mode`` consultado.
"""

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import AgentBusyError, AgentCoordinator
from app.modules.detectar.agents.definitions import (
    AgentDefinition,
    ImplementationStatus,
)
from app.modules.detectar.agents.registry import AgentRegistry, default_registry
from app.modules.detectar.agents.scheduler import AgentScheduler
from app.modules.detectar.agents.tasks import (
    CollectionPlan,
    SupervisorParams,
    TrendHunterParams,
)
from app.modules.detectar.api.collections import (
    CollectionRequest,
    validate_collection_request,
)
from app.modules.detectar.api.dependencies import (
    get_agent_coordinator,
    get_agent_scheduler,
    get_session_factory,
    require_admin,
)
from app.modules.detectar.api.errors import DetectarError, FieldError
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import AgentRun, AgentRunStatus, DataMode
from app.modules.detectar.timeutil import format_utc

logger = logging.getLogger(__name__)

agents_router = APIRouter(tags=["detectar"])

AGENT_ID_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"

# Actividad derivada SOLO del estado de la última ejecución registrada.
_ACTIVITY = {
    AgentRunStatus.PENDING: "pendiente",
    AgentRunStatus.RUNNING: "en_curso",
    AgentRunStatus.COMPLETED: "completada",
    AgentRunStatus.FAILED: "fallida",
    AgentRunStatus.BLOCKED: "bloqueada",
}
Activity = Literal["sin_ejecuciones", "pendiente", "en_curso", "completada", "fallida", "bloqueada"]


def get_agent_registry() -> AgentRegistry:
    return default_registry()


class AgentRunOut(BaseModel):
    id: str
    agente: str
    data_mode: DataMode
    estado: AgentRunStatus
    disparador: str
    solicitado: str
    inicio: str | None
    fin: str | None
    resultado: dict[str, object] | None
    codigo_error: str | None
    detalle_error: str | None


class AgentOut(BaseModel):
    id: str
    nombre: str
    descripcion: str
    responsabilidad: str
    alcance: str
    colabora_con: list[str]
    fuentes_permitidas: list[str]
    herramientas_permitidas: list[str]
    estado_implementacion: str
    estado_asignacion: str
    preguntas_abiertas: list[str]
    frecuencia_minutos: int | None
    definido: bool
    implementado: bool
    ejecutado: bool
    actividad: Activity
    ultima_ejecucion: AgentRunOut | None


class AgentList(BaseModel):
    data_mode: DataMode
    agentes: list[AgentOut]


class AgentRunList(BaseModel):
    agente: str
    data_mode: DataMode
    limite: int
    ejecuciones: list[AgentRunOut]


def _run_out(run: AgentRun) -> AgentRunOut:
    """Acepta una fila de ``agent_runs`` o un ``AgentRunView`` del coordinador."""
    return AgentRunOut(
        id=run.id,
        agente=run.agent_id,
        data_mode=run.data_mode,
        estado=run.status,
        disparador=run.trigger.value,
        solicitado=format_utc(run.requested_at),
        inicio=format_utc(run.started_at) if run.started_at else None,
        fin=format_utc(run.finished_at) if run.finished_at else None,
        resultado=run.result,
        codigo_error=run.error_code,
        detalle_error=run.error_detail,  # ya almacenado sin secretos
    )


def _schedules(registry: AgentRegistry, settings: DetectarSettings) -> dict[str, int | None]:
    try:
        resolved = registry.resolve_schedules(settings.agent_schedules)
    except ValueError:
        logger.error("DETECTAR_AGENT_SCHEDULES no es válida")
        raise DetectarError(
            code="invalid_configuration",
            status=500,
            title="Configuración inválida",
            detail="La configuración de frecuencias de agentes no es válida.",
        ) from None
    return {k: int(v.total_seconds() // 60) if v else None for k, v in resolved.items()}


def _agent_out(
    definition: AgentDefinition, last: AgentRun | None, frequency: int | None
) -> AgentOut:
    return AgentOut(
        id=definition.id,
        nombre=definition.name,
        descripcion=definition.description,
        responsabilidad=definition.responsibility,
        alcance=definition.scope.value,
        colabora_con=sorted(m.value for m in definition.collaborates_with),
        fuentes_permitidas=sorted(s.value for s in definition.allowed_sources),
        herramientas_permitidas=sorted(t.value for t in definition.allowed_tools),
        estado_implementacion=definition.implementation_status.value,
        estado_asignacion=definition.assignment_status.value,
        preguntas_abiertas=list(definition.open_questions),
        frecuencia_minutos=frequency,
        definido=True,
        implementado=definition.implementation_status is ImplementationStatus.AVAILABLE,
        ejecutado=last is not None,
        actividad=_ACTIVITY[last.status] if last else "sin_ejecuciones",
        ultima_ejecucion=_run_out(last) if last else None,
    )


@agents_router.get("/agentes", response_model=AgentList, dependencies=[Depends(require_admin)])
def list_agents(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
    settings: Annotated[DetectarSettings, Depends(get_settings)],
    data_mode: Annotated[Literal["real", "simulated"], Query()] = "real",
) -> AgentList:
    frequencies = _schedules(registry, settings)
    with session_factory() as session:
        runs = AgentRunRepository(session)
        return AgentList(
            data_mode=DataMode(data_mode),
            agentes=[
                _agent_out(
                    definition,
                    runs.latest(definition.id, data_mode=data_mode),
                    frequencies[definition.id],
                )
                for definition in registry.all()
            ],
        )


@agents_router.get(
    "/agentes/{agent_id}/ejecuciones",
    response_model=AgentRunList,
    dependencies=[Depends(require_admin)],
)
def list_agent_runs(
    agent_id: Annotated[str, Path(pattern=AGENT_ID_PATTERN)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
    data_mode: Annotated[Literal["real", "simulated"], Query()] = "real",
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentRunList:
    try:
        registry.get(agent_id)
    except LookupError:
        raise DetectarError(
            code="not_found",
            status=404,
            title="Agente no encontrado",
            detail="No existe un agente con ese identificador.",
        ) from None
    with session_factory() as session:
        runs = AgentRunRepository(session).list_runs(
            data_mode=data_mode, agent_id=agent_id, limit=limite
        )
        return AgentRunList(
            agente=agent_id,
            data_mode=DataMode(data_mode),
            limite=limite,
            ejecuciones=[_run_out(run) for run in runs],
        )


# --- E10: solicitud de ejecuciones -------------------------------------------------------


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Literal["real", "simulated"]  # obligatorio: nunca se infiere
    parametros: dict[str, Any] = Field(default_factory=dict)


class TrendHunterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fecha_referencia: date
    # Mismo contrato que POST /recolecciones. Sin valor: solo procesa datos ya guardados.
    recoleccion: CollectionRequest | None = None


class SupervisorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limite_por_agente: int = Field(default=20, ge=1, le=100)


def _invalid_parameters(detail: str, errors: list[FieldError] | None = None) -> DetectarError:
    return DetectarError(
        code="invalid_parameters",
        status=422,
        title="Parámetros inválidos",
        detail=detail,
        errors=errors or [FieldError(campo="body.parametros", mensaje=detail)],
    )


def _parse(model: type[BaseModel], raw: dict[str, Any]) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise _invalid_parameters(
            "Los parámetros no son válidos para este agente.",
            [
                FieldError(
                    campo=".".join(["body", "parametros", *(str(p) for p in err["loc"])]),
                    mensaje=err["msg"],
                )
                for err in exc.errors()
            ],
        ) from None


def _internal_params(agent_id: str, body: AgentRunRequest, settings: DetectarSettings) -> dict[str, Any]:
    """Valida el contrato público (español) y lo traduce a los parámetros de la tarea."""
    if agent_id == "trend_hunter":
        request = _parse(TrendHunterRequest, body.parametros)
        if request.fecha_referencia >= datetime.now(UTC).date():
            raise _invalid_parameters("fecha_referencia debe ser un día cerrado (anterior a hoy en UTC).")
        plan = None
        if request.recoleccion is not None:
            if body.data_mode != "real":
                raise _invalid_parameters("Solo se puede recolectar en modo real.")
            sources, countries, wikimedia, gdelt = validate_collection_request(request.recoleccion, settings)
            plan = CollectionPlan(
                sources=tuple(sources), countries=tuple(countries), wikimedia=wikimedia, gdelt=gdelt
            )
        return TrendHunterParams(as_of=request.fecha_referencia, collection=plan).model_dump(mode="json")
    if agent_id == "supervisor":
        request = _parse(SupervisorRequest, body.parametros)
        return SupervisorParams(per_agent_limit=request.limite_por_agente).model_dump(mode="json")
    if body.parametros:
        raise _invalid_parameters("Este agente no tiene tarea implementada y no admite parámetros.")
    return {}


@agents_router.post(
    "/agentes/{agent_id}/ejecuciones",
    status_code=201,
    response_model=AgentRunOut,
    dependencies=[Depends(require_admin)],
)
async def start_agent_run(
    agent_id: Annotated[str, Path(pattern=AGENT_ID_PATTERN)],
    body: AgentRunRequest,
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
    settings: Annotated[DetectarSettings, Depends(get_settings)],
    coordinator: Annotated[AgentCoordinator, Depends(get_agent_coordinator)],
) -> AgentRunOut:
    """Ejecuta el agente de forma SÍNCRONA y devuelve la ejecución registrada.

    201 no implica éxito: ``estado`` puede ser ``completed``, ``failed`` o ``blocked``.
    """
    try:
        registry.get(agent_id)
    except LookupError:
        raise DetectarError(
            code="not_found",
            status=404,
            title="Agente no encontrado",
            detail="No existe un agente con ese identificador.",
        ) from None
    params = _internal_params(agent_id, body, settings)
    try:
        run = await coordinator.start(agent_id, data_mode=body.data_mode, params=params)
    except AgentBusyError:
        raise DetectarError(
            code="agent_busy",
            status=409,
            title="Agente ocupado",
            detail="El agente ya tiene una ejecución activa registrada.",
        ) from None
    except Exception as exc:  # noqa: BLE001 - p. ej. error de persistencia: sin detalles internos
        logger.error("Error inesperado al ejecutar el agente %s: %s", agent_id, type(exc).__name__)
        raise DetectarError(
            code="internal_error",
            status=500,
            title="Error interno",
            detail="No se pudo registrar o completar la ejecución del agente.",
        ) from None
    return _run_out(run)


# --- E11: estado del programador (solo lectura) -------------------------------------------


class ScheduledAgentOut(BaseModel):
    agente: str
    programado: bool
    motivo_omision: str | None
    frecuencia_minutos: int | None
    data_mode: DataMode | None


class SchedulerStatusOut(BaseModel):
    habilitado: bool
    en_ejecucion: bool
    intervalo_tick_segundos: float
    umbral_abandono_segundos: int
    agentes: list[ScheduledAgentOut]
    ultimo_tick: dict[str, object] | None


def get_scheduler_for_status() -> AgentScheduler:
    """Programador compartido; una configuración inválida se responde como error estructurado."""
    try:
        return get_agent_scheduler()
    except ValueError:
        raise DetectarError(
            code="invalid_configuration",
            status=500,
            title="Configuración inválida",
            detail="La configuración del programador o de las frecuencias no es válida.",
        ) from None


@agents_router.get(
    "/agentes/programador",
    response_model=SchedulerStatusOut,
    dependencies=[Depends(require_admin)],
)
def scheduler_status(
    settings: Annotated[DetectarSettings, Depends(get_settings)],
    scheduler: Annotated[AgentScheduler, Depends(get_scheduler_for_status)],
) -> SchedulerStatusOut:
    """Solo lectura: plan de programación, motivos de omisión y último tick en memoria."""
    scheduled = {entry.agent_id: entry for entry in scheduler.plan.entries}
    agents = []
    for agent_id in [*scheduled, *scheduler.plan.skipped]:
        entry = scheduled.get(agent_id)
        agents.append(
            ScheduledAgentOut(
                agente=agent_id,
                programado=entry is not None,
                motivo_omision=scheduler.plan.skipped.get(agent_id),
                frecuencia_minutos=int(entry.interval.total_seconds() // 60) if entry else None,
                data_mode=entry.data_mode if entry else None,
            )
        )
    return SchedulerStatusOut(
        habilitado=settings.scheduler_enabled,
        en_ejecucion=scheduler.running,
        intervalo_tick_segundos=settings.scheduler_tick_seconds,
        umbral_abandono_segundos=settings.agent_abandon_after_seconds,
        agentes=sorted(agents, key=lambda a: a.agente),
        ultimo_tick=scheduler.last_tick.as_dict() if scheduler.last_tick else None,
    )
