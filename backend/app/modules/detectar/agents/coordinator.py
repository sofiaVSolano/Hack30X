"""Interfaz de coordinación de agentes y una implementación local mínima.

``AgentCoordinator`` es el contrato que usará la oficina: iniciar tareas, registrar
ejecuciones y consultar estados reales. ``LocalAgentCoordinator`` lo implementa en el
mismo proceso, sin colas, sin programador y sin modelos de lenguaje:

- solo ejecuta una tarea cuando alguien llama a ``start``;
- si el agente no tiene tarea implementada, la ejecución queda ``blocked`` con el motivo;
- una tarea que lanza una excepción, devuelve un resultado inválido o excede el tiempo
  queda ``failed``; nunca aparece como completada.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.definitions import (
    AgentDefinition,
    ImplementationStatus,
)
from app.modules.detectar.agents.registry import AgentRegistry
from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.logsafety import redact
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    DataMode,
)
from app.modules.detectar.storage.repository import require_data_mode

logger = logging.getLogger(__name__)


class AgentTaskContext(BaseModel):
    """Lo que recibe una tarea. Debe leer y escribir datos solo con este ``data_mode``."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    data_mode: DataMode
    params: dict[str, Any]
    requested_at: AwareDatetime


AgentTask = Callable[[AgentTaskContext], Awaitable[dict[str, Any]]]


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    agent_id: str
    data_mode: DataMode
    trigger: AgentRunTrigger
    status: AgentRunStatus
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error_code: str | None
    error_detail: str | None


class AgentState(StrEnum):
    """Estado observable de un agente, derivado de su última ejecución real."""

    IDLE = "idle"  # sin ejecución activa (nunca ejecutado o la última terminó bien)
    RUNNING = "running"  # hay una ejecución pendiente o en curso
    FAILED = "failed"  # la última ejecución falló
    BLOCKED = "blocked"  # la última ejecución no pudo realizarse


_STATE_BY_LAST_STATUS = {
    AgentRunStatus.PENDING: AgentState.RUNNING,
    AgentRunStatus.RUNNING: AgentState.RUNNING,
    AgentRunStatus.COMPLETED: AgentState.IDLE,
    AgentRunStatus.FAILED: AgentState.FAILED,
    AgentRunStatus.BLOCKED: AgentState.BLOCKED,
}


class AgentStatusView(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentDefinition
    data_mode: DataMode
    state: AgentState
    has_runs: bool
    last_run: AgentRunView | None
    schedule_minutes: int | None


class AgentBusyError(RuntimeError):
    pass


class AgentCoordinator(Protocol):
    async def start(
        self,
        agent_id: str,
        *,
        data_mode: DataMode | str,
        trigger: AgentRunTrigger = AgentRunTrigger.MANUAL,
        params: dict[str, Any] | None = None,
    ) -> AgentRunView: ...

    def get_run(self, run_id: str, *, data_mode: DataMode | str) -> AgentRunView | None: ...

    def list_runs(
        self, *, data_mode: DataMode | str, agent_id: str | None = None, limit: int = 50
    ) -> list[AgentRunView]: ...

    def agent_status(self, agent_id: str, *, data_mode: DataMode | str) -> AgentStatusView: ...


class LocalAgentCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: AgentRegistry,
        *,
        tasks: Mapping[str, AgentTask] | None = None,
        schedules_minutes: Mapping[str, int] | None = None,
        task_timeout_seconds: float = 300.0,
        clock: Clock = utc_now,
    ) -> None:
        if task_timeout_seconds <= 0:
            raise ValueError("task_timeout_seconds debe ser positivo")
        self._session_factory = session_factory
        self._registry = registry
        self._tasks = dict(tasks or {})
        unknown = set(self._tasks) - set(registry.ids)
        if unknown:
            raise ValueError(f"Tareas para agentes desconocidos: {sorted(unknown)}")
        # Se valida al construir para no descubrir configuraciones inválidas más tarde.
        schedules = registry.resolve_schedules(schedules_minutes or {})
        self._schedule_minutes = {
            agent_id: int(delta.total_seconds() // 60) if delta else None
            for agent_id, delta in schedules.items()
        }
        self._task_timeout = task_timeout_seconds
        self._active: set[str] = set()
        self._clock = clock

    # --- consultas -------------------------------------------------------------

    @property
    def task_timeout_seconds(self) -> float:
        return self._task_timeout

    def active_run_ids(self) -> frozenset[str]:
        """Ejecuciones que este coordinador está ejecutando ahora mismo (en este proceso)."""
        return frozenset(self._active)

    def get_run(self, run_id: str, *, data_mode: DataMode | str) -> AgentRunView | None:
        with self._session_factory() as session:
            run = AgentRunRepository(session).get(run_id, data_mode=data_mode)
            return AgentRunView.model_validate(run) if run else None

    def list_runs(
        self, *, data_mode: DataMode | str, agent_id: str | None = None, limit: int = 50
    ) -> list[AgentRunView]:
        with self._session_factory() as session:
            runs = AgentRunRepository(session).list_runs(
                data_mode=data_mode, agent_id=agent_id, limit=limit
            )
            return [AgentRunView.model_validate(run) for run in runs]

    def agent_status(self, agent_id: str, *, data_mode: DataMode | str) -> AgentStatusView:
        definition = self._registry.get(agent_id)
        mode = require_data_mode(data_mode)
        with self._session_factory() as session:
            last = AgentRunRepository(session).latest(agent_id, data_mode=mode)
            last_view = AgentRunView.model_validate(last) if last else None
        return AgentStatusView(
            agent=definition,
            data_mode=mode,
            state=_STATE_BY_LAST_STATUS[last_view.status] if last_view else AgentState.IDLE,
            has_runs=last_view is not None,
            last_run=last_view,
            schedule_minutes=self._schedule_minutes[agent_id],
        )

    # --- ejecución -------------------------------------------------------------

    async def start(
        self,
        agent_id: str,
        *,
        data_mode: DataMode | str,
        trigger: AgentRunTrigger = AgentRunTrigger.MANUAL,
        params: dict[str, Any] | None = None,
    ) -> AgentRunView:
        definition = self._registry.get(agent_id)
        mode = require_data_mode(data_mode)

        with self._session_factory() as session, session.begin():
            repo = AgentRunRepository(session)
            latest = repo.latest(agent_id, data_mode=mode)
            if latest is not None and latest.status in (
                AgentRunStatus.PENDING,
                AgentRunStatus.RUNNING,
            ):
                raise AgentBusyError(f"El agente {agent_id!r} ya tiene una ejecución activa")
            run = repo.create(
                agent_id, data_mode=mode, trigger=trigger, requested_at=self._clock(), params=params
            )
            run_id, requested_at, run_params = run.id, run.requested_at, dict(run.params)

        # E11: la ejecución figura como activa en este proceso mientras se ejecuta; así la
        # recuperación de abandonadas nunca cierra una tarea lenta de este proceso.
        self._active.add(run_id)
        try:
            return await self._execute(run_id, agent_id, definition, mode, requested_at, run_params)
        finally:
            self._active.discard(run_id)

    async def _execute(
        self,
        run_id: str,
        agent_id: str,
        definition: AgentDefinition,
        mode: DataMode,
        requested_at: datetime,
        run_params: dict[str, Any],
    ) -> AgentRunView:
        task = self._tasks.get(agent_id)
        blocked_reason = _blocked_reason(definition, task)
        if blocked_reason is not None:
            return self._finish(
                run_id, mode, AgentRunStatus.BLOCKED, error=("not_implemented", blocked_reason)
            )

        with self._session_factory() as session, session.begin():
            AgentRunRepository(session).mark_running(
                run_id, data_mode=mode, started_at=self._clock()
            )

        context = AgentTaskContext(
            run_id=run_id,
            agent_id=agent_id,
            data_mode=mode,
            params=run_params,
            requested_at=requested_at,
        )
        assert task is not None  # garantizado por _blocked_reason
        try:
            async with asyncio.timeout(self._task_timeout):
                result = await task(context)
        except TimeoutError:
            return self._finish(
                run_id,
                mode,
                AgentRunStatus.FAILED,
                error=("task_timeout", f"La tarea superó {self._task_timeout:g} s"),
            )
        except Exception as exc:  # noqa: BLE001 - el fallo se registra, no se oculta
            logger.error("La tarea del agente %s falló: %s", agent_id, type(exc).__name__)
            return self._finish(
                run_id,
                mode,
                AgentRunStatus.FAILED,
                error=("task_error", redact(f"{type(exc).__name__}: {exc}")),
            )

        problem = _result_problem(result)
        if problem is not None:
            return self._finish(run_id, mode, AgentRunStatus.FAILED, error=("invalid_result", problem))
        return self._finish(run_id, mode, AgentRunStatus.COMPLETED, result=result)

    def _finish(
        self,
        run_id: str,
        mode: DataMode,
        status: AgentRunStatus,
        *,
        result: dict[str, Any] | None = None,
        error: tuple[str, str] | None = None,
    ) -> AgentRunView:
        with self._session_factory() as session, session.begin():
            repo = AgentRunRepository(session)
            now = self._clock()
            run: AgentRun
            if status is AgentRunStatus.COMPLETED:
                assert result is not None
                run = repo.mark_completed(run_id, data_mode=mode, finished_at=now, result=result)
            elif status is AgentRunStatus.FAILED:
                assert error is not None
                run = repo.mark_failed(
                    run_id, data_mode=mode, finished_at=now, error_code=error[0], error_detail=error[1]
                )
            else:
                assert error is not None
                run = repo.mark_blocked(
                    run_id, data_mode=mode, finished_at=now, error_code=error[0], error_detail=error[1]
                )
            return AgentRunView.model_validate(run)


def _blocked_reason(definition: AgentDefinition, task: AgentTask | None) -> str | None:
    if definition.implementation_status is not ImplementationStatus.AVAILABLE:
        return f"El agente {definition.id!r} está definido pero su tarea no está implementada."
    if task is None:
        return f"No hay una tarea registrada para el agente {definition.id!r}."
    return None


def _result_problem(result: object) -> str | None:
    if not isinstance(result, dict):
        return f"La tarea devolvió {type(result).__name__}; se esperaba un objeto JSON"
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return f"El resultado no es serializable como JSON: {type(exc).__name__}"
    return None
