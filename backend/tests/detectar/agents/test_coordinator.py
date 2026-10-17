"""Coordinador local: inicia ejecuciones y registra su resultado real. Sin LLM ni red."""

import asyncio
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import (
    AgentBusyError,
    AgentState,
    AgentTaskContext,
    LocalAgentCoordinator,
)
from app.modules.detectar.agents.definitions import (
    AgentDefinition,
    AgentScope,
    ImplementationStatus,
    OfficeModule,
)
from app.modules.detectar.agents.registry import AgentRegistry, default_registry
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRunStatus,
    AgentRunTrigger,
    DataMode,
)

from ..fakes import StepClock

pytestmark = pytest.mark.anyio

TEST_AGENT = AgentDefinition(
    id="agente_prueba",
    name="Agente de prueba",
    description="Agente usado solo en pruebas automáticas.",
    responsibility="Devolver lo que la prueba le indique.",
    scope=AgentScope.DETECTAR,
    collaborates_with=frozenset({OfficeModule.DETECTAR}),
    implementation_status=ImplementationStatus.AVAILABLE,
)


def _coordinator(
    session_factory: sessionmaker[Session], task=None, **kwargs: Any
) -> LocalAgentCoordinator:
    registry = AgentRegistry([TEST_AGENT, *default_registry().all()])
    tasks = {"agente_prueba": task} if task else {}
    return LocalAgentCoordinator(session_factory, registry, tasks=tasks, clock=StepClock(), **kwargs)


async def test_planned_agent_is_blocked_not_completed(session_factory) -> None:
    coordinator = _coordinator(session_factory)

    run = await coordinator.start("trend_hunter", data_mode=DataMode.REAL)

    assert run.status is AgentRunStatus.BLOCKED
    assert run.error_code == "not_implemented"
    assert run.result is None
    assert run.started_at is None
    status = coordinator.agent_status("trend_hunter", data_mode=DataMode.REAL)
    assert status.state is AgentState.BLOCKED


async def test_available_agent_without_task_is_blocked(session_factory) -> None:
    run = await _coordinator(session_factory).start("agente_prueba", data_mode="real")

    assert run.status is AgentRunStatus.BLOCKED
    assert "No hay una tarea" in (run.error_detail or "")


async def test_successful_task_is_recorded_with_its_result(session_factory) -> None:
    received: list[AgentTaskContext] = []

    async def task(context: AgentTaskContext) -> dict[str, Any]:
        received.append(context)
        return {"resumen": "sin hallazgos", "items": []}

    coordinator = _coordinator(session_factory, task)
    run = await coordinator.start(
        "agente_prueba", data_mode=DataMode.SIMULATED, params={"pais": "MX"}
    )

    assert run.status is AgentRunStatus.COMPLETED
    assert run.result == {"resumen": "sin hallazgos", "items": []}
    assert run.started_at is not None and run.finished_at > run.started_at
    assert received[0].data_mode is DataMode.SIMULATED
    assert received[0].params == {"pais": "MX"}
    assert coordinator.get_run(run.id, data_mode=DataMode.SIMULATED) == run


async def test_failing_task_is_recorded_as_failed(session_factory) -> None:
    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        raise RuntimeError("se cayó con token=SECRETO-XYZ")

    coordinator = _coordinator(session_factory, task)
    run = await coordinator.start("agente_prueba", data_mode=DataMode.REAL)

    assert run.status is AgentRunStatus.FAILED
    assert run.result is None
    assert run.error_code == "task_error"
    assert "SECRETO-XYZ" not in (run.error_detail or "")
    status = coordinator.agent_status("agente_prueba", data_mode=DataMode.REAL)
    assert status.state is AgentState.FAILED


@pytest.mark.parametrize("bad_result", [None, ["lista"], "texto", {"x": float("inf")}, {"x": object()}])
async def test_invalid_results_never_appear_as_completed(session_factory, bad_result) -> None:
    async def task(_context: AgentTaskContext) -> Any:
        return bad_result

    run = await _coordinator(session_factory, task).start("agente_prueba", data_mode=DataMode.REAL)

    assert run.status is AgentRunStatus.FAILED
    assert run.error_code == "invalid_result"


async def test_task_timeout_is_a_failure(session_factory) -> None:
    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    run = await _coordinator(session_factory, task, task_timeout_seconds=0.05).start(
        "agente_prueba", data_mode=DataMode.REAL
    )

    assert run.status is AgentRunStatus.FAILED
    assert run.error_code == "task_timeout"


async def test_agent_without_runs_is_idle_and_says_so(session_factory) -> None:
    status = _coordinator(session_factory).agent_status("supervisor", data_mode=DataMode.REAL)

    assert status.state is AgentState.IDLE
    assert status.has_runs is False
    assert status.last_run is None


async def test_runs_and_status_are_isolated_by_data_mode(session_factory) -> None:
    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        return {}

    coordinator = _coordinator(session_factory, task)
    run = await coordinator.start("agente_prueba", data_mode=DataMode.SIMULATED)

    assert coordinator.get_run(run.id, data_mode=DataMode.REAL) is None
    assert coordinator.list_runs(data_mode=DataMode.REAL) == []
    real_status = coordinator.agent_status("agente_prueba", data_mode=DataMode.REAL)
    assert real_status.has_runs is False


async def test_agent_with_active_run_cannot_start_again(session_factory) -> None:
    with session_factory() as session, session.begin():
        AgentRunRepository(session).create(
            "agente_prueba",
            data_mode=DataMode.REAL,
            trigger=AgentRunTrigger.MANUAL,
            requested_at=StepClock()(),
        )

    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        return {}

    with pytest.raises(AgentBusyError):
        await _coordinator(session_factory, task).start("agente_prueba", data_mode=DataMode.REAL)


async def test_definition_is_separate_from_its_executions(session_factory) -> None:
    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        return {"ok": True}

    before = TEST_AGENT.model_copy(deep=True)
    coordinator = _coordinator(session_factory, task)
    await coordinator.start("agente_prueba", data_mode=DataMode.REAL)
    await coordinator.start("agente_prueba", data_mode=DataMode.REAL)

    assert TEST_AGENT == before
    runs = coordinator.list_runs(data_mode=DataMode.REAL, agent_id="agente_prueba")
    assert len(runs) == 2
    assert all(run.agent_id == "agente_prueba" for run in runs)
    status = coordinator.agent_status("agente_prueba", data_mode=DataMode.REAL)
    assert status.agent == TEST_AGENT
    assert status.state is AgentState.IDLE and status.has_runs is True


async def test_status_exposes_configured_schedule(session_factory) -> None:
    coordinator = _coordinator(session_factory, schedules_minutes={"trend_hunter": 240})

    assert coordinator.agent_status("trend_hunter", data_mode="real").schedule_minutes == 240
    assert coordinator.agent_status("analyst", data_mode="real").schedule_minutes is None


def test_tasks_for_unknown_agents_are_rejected(session_factory) -> None:
    async def task(_context: AgentTaskContext) -> dict[str, Any]:
        return {}

    with pytest.raises(ValueError, match="desconocidos"):
        LocalAgentCoordinator(session_factory, default_registry(), tasks={"fantasma": task})


def test_invalid_schedule_configuration_fails_at_construction(session_factory) -> None:
    with pytest.raises(ValueError):
        LocalAgentCoordinator(
            session_factory, default_registry(), schedules_minutes={"trend_hunter": 1}
        )


async def test_unknown_agent_cannot_be_started(session_factory) -> None:
    with pytest.raises(LookupError):
        await _coordinator(session_factory).start("fantasma", data_mode=DataMode.REAL)
