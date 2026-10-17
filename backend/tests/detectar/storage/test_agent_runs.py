"""Tabla agent_runs: ciclo de vida, transiciones, restricciones SQL y aislamiento por modo."""

import inspect as pyinspect
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.detectar.storage.agent_runs import (
    AgentRunRepository,
    InvalidTransitionError,
    ensure_transition,
)
from app.modules.detectar.storage.models import (
    AGENT_RUN_TRANSITIONS,
    AgentRunStatus,
    AgentRunTrigger,
    CollectionTrigger,
    DataMode,
)
from app.modules.detectar.storage.repository import (
    DetectarRepository,
    InvalidDataModeError,
)

from .factories import T1

T2 = T1 + timedelta(minutes=1)
T3 = T1 + timedelta(minutes=2)


@pytest.fixture
def runs(session: Session) -> AgentRunRepository:
    return AgentRunRepository(session)


def _pending(runs: AgentRunRepository, mode: DataMode = DataMode.REAL, agent_id: str = "trend_hunter"):
    return runs.create(agent_id, data_mode=mode, trigger=AgentRunTrigger.MANUAL, requested_at=T1)


# --- Ciclo de vida -------------------------------------------------------------


def test_successful_lifecycle(runs: AgentRunRepository) -> None:
    run = _pending(runs)
    assert run.id.startswith("arun_")
    assert run.status is AgentRunStatus.PENDING
    assert run.params == {}

    runs.mark_running(run.id, data_mode=DataMode.REAL, started_at=T2)
    done = runs.mark_completed(
        run.id, data_mode=DataMode.REAL, finished_at=T3, result={"hallazgos": []}
    )

    assert done.status is AgentRunStatus.COMPLETED
    assert (done.started_at, done.finished_at) == (T2, T3)
    assert done.result == {"hallazgos": []}
    assert done.error_code is None


def test_failure_records_redacted_error(runs: AgentRunRepository) -> None:
    run = _pending(runs)
    runs.mark_running(run.id, data_mode=DataMode.REAL, started_at=T2)

    failed = runs.mark_failed(
        run.id,
        data_mode=DataMode.REAL,
        finished_at=T3,
        error_code="task_error",
        error_detail="Falló https://api.test/?token=SECRETO-ABC",
    )

    assert failed.status is AgentRunStatus.FAILED
    assert failed.result is None
    assert "SECRETO-ABC" not in (failed.error_detail or "")


def test_pending_run_can_be_blocked_with_reason(runs: AgentRunRepository) -> None:
    run = _pending(runs)

    blocked = runs.mark_blocked(
        run.id,
        data_mode=DataMode.REAL,
        finished_at=T2,
        error_code="not_implemented",
        error_detail="Sin tarea implementada",
    )

    assert blocked.status is AgentRunStatus.BLOCKED
    assert blocked.started_at is None
    assert blocked.error_code == "not_implemented"


# --- Transiciones ------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (AgentRunStatus.PENDING, AgentRunStatus.COMPLETED),
        (AgentRunStatus.RUNNING, AgentRunStatus.PENDING),
        (AgentRunStatus.COMPLETED, AgentRunStatus.FAILED),
        (AgentRunStatus.FAILED, AgentRunStatus.COMPLETED),
        (AgentRunStatus.BLOCKED, AgentRunStatus.RUNNING),
        (AgentRunStatus.RUNNING, AgentRunStatus.RUNNING),
    ],
)
def test_invalid_transitions_are_rejected(current: AgentRunStatus, new: AgentRunStatus) -> None:
    with pytest.raises(InvalidTransitionError):
        ensure_transition(current, new)


def test_terminal_states_have_no_transitions() -> None:
    for status in (AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.BLOCKED):
        assert AGENT_RUN_TRANSITIONS[status] == frozenset()


def test_cannot_complete_a_pending_run(runs: AgentRunRepository) -> None:
    run = _pending(runs)

    with pytest.raises(InvalidTransitionError):
        runs.mark_completed(run.id, data_mode=DataMode.REAL, finished_at=T2, result={})


def test_failed_run_can_never_become_completed(runs: AgentRunRepository) -> None:
    run = _pending(runs)
    runs.mark_running(run.id, data_mode=DataMode.REAL, started_at=T2)
    runs.mark_failed(
        run.id, data_mode=DataMode.REAL, finished_at=T3, error_code="x", error_detail="falló"
    )

    with pytest.raises(InvalidTransitionError):
        runs.mark_completed(run.id, data_mode=DataMode.REAL, finished_at=T3, result={"ok": True})
    assert runs.get(run.id, data_mode=DataMode.REAL).status is AgentRunStatus.FAILED


def test_completed_requires_a_result_and_errors_require_detail(runs: AgentRunRepository) -> None:
    run = _pending(runs)
    runs.mark_running(run.id, data_mode=DataMode.REAL, started_at=T2)

    with pytest.raises(ValueError):
        runs.mark_completed(run.id, data_mode=DataMode.REAL, finished_at=T3, result=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        runs.mark_failed(run.id, data_mode=DataMode.REAL, finished_at=T3, error_code="", error_detail="x")
    with pytest.raises(ValueError):
        runs.mark_completed(
            run.id, data_mode=DataMode.REAL, finished_at=T3, result={"x": float("nan")}
        )


# --- Restricciones en SQLite (sin pasar por el repositorio) --------------------


def _insert(session: Session, **overrides: object) -> None:
    values = {
        "id": "arun_directo",
        "agent_id": "trend_hunter",
        "data_mode": "real",
        "trigger": "manual",
        "status": "pending",
        "requested_at": "2026-10-16 00:00:00",
        "started_at": None,
        "finished_at": None,
        "collection_run_id": None,
        "params": "{}",
        "result": None,
        "error_code": None,
        "error_detail": None,
    } | overrides
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    session.execute(text(f"INSERT INTO agent_runs ({columns}) VALUES ({placeholders})"), values)


@pytest.mark.parametrize(
    "overrides",
    [
        # completado sin resultado
        {"status": "completed", "started_at": "2026-10-16 00:01:00", "finished_at": "2026-10-16 00:02:00"},
        # completado con error
        {
            "status": "completed",
            "started_at": "2026-10-16 00:01:00",
            "finished_at": "2026-10-16 00:02:00",
            "result": "{}",
            "error_code": "x",
            "error_detail": "y",
        },
        # fallido sin explicación
        {"status": "failed", "finished_at": "2026-10-16 00:02:00"},
        # fallido con resultado
        {
            "status": "failed",
            "finished_at": "2026-10-16 00:02:00",
            "result": "{}",
            "error_code": "x",
            "error_detail": "y",
        },
        # en curso sin fecha de inicio
        {"status": "running"},
        # termina antes de empezar
        {
            "status": "completed",
            "started_at": "2026-10-16 00:05:00",
            "finished_at": "2026-10-16 00:02:00",
            "result": "{}",
        },
        {"status": "idle"},
        {"data_mode": "mixed"},
    ],
)
def test_database_rejects_inconsistent_rows(session: Session, overrides: dict) -> None:
    with pytest.raises(IntegrityError):
        _insert(session, **overrides)


def test_database_trigger_rejects_invalid_transition(session: Session) -> None:
    _insert(session)

    with pytest.raises(IntegrityError, match="transicion de estado invalida"):
        session.execute(
            text(
                "UPDATE agent_runs SET status = 'completed', started_at = '2026-10-16 00:01:00', "
                "finished_at = '2026-10-16 00:02:00', result = '{}' WHERE id = 'arun_directo'"
            )
        )


def test_database_trigger_freezes_terminal_runs(session: Session) -> None:
    _insert(
        session,
        status="failed",
        finished_at="2026-10-16 00:02:00",
        error_code="x",
        error_detail="falló",
    )

    with pytest.raises(IntegrityError, match="terminada no se modifica"):
        session.execute(
            text("UPDATE agent_runs SET error_detail = 'reescrito' WHERE id = 'arun_directo'")
        )


def test_agent_run_must_share_mode_with_its_collection(
    session: Session, runs: AgentRunRepository
) -> None:
    collection = DetectarRepository(session).create_collection_run(
        data_mode=DataMode.REAL,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[],
        requested_countries=[],
        created_at=T1,
    )

    with pytest.raises(IntegrityError):
        runs.create(
            "trend_hunter",
            data_mode=DataMode.SIMULATED,
            trigger=AgentRunTrigger.MANUAL,
            requested_at=T1,
            collection_run_id=collection.id,
        )


# --- Aislamiento real / simulado ------------------------------------------------


def test_runs_are_isolated_by_data_mode(runs: AgentRunRepository) -> None:
    real = _pending(runs, DataMode.REAL)
    simulated = _pending(runs, DataMode.SIMULATED)

    assert [r.id for r in runs.list_runs(data_mode=DataMode.REAL)] == [real.id]
    assert [r.id for r in runs.list_runs(data_mode=DataMode.SIMULATED)] == [simulated.id]
    assert runs.get(real.id, data_mode=DataMode.SIMULATED) is None
    assert runs.latest("trend_hunter", data_mode=DataMode.SIMULATED).id == simulated.id
    with pytest.raises(LookupError):
        runs.mark_running(real.id, data_mode=DataMode.SIMULATED, started_at=T2)


@pytest.mark.parametrize("bad_mode", [None, "", "both", "REAL"])
def test_invalid_mode_is_rejected(runs: AgentRunRepository, bad_mode: object) -> None:
    with pytest.raises(InvalidDataModeError):
        runs.list_runs(data_mode=bad_mode)  # type: ignore[arg-type]


def test_every_public_method_requires_keyword_data_mode() -> None:
    methods = {
        name: member
        for name, member in pyinspect.getmembers(AgentRunRepository, pyinspect.isfunction)
        if not name.startswith("_")
    }
    assert methods
    for name, method in methods.items():
        parameter = pyinspect.signature(method).parameters.get("data_mode")
        assert parameter is not None, name
        assert parameter.kind is pyinspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is pyinspect.Parameter.empty, name


def test_storage_repository_still_requires_data_mode_after_e3() -> None:
    """El método añadido en E3 al repositorio de E2 respeta la misma regla."""
    parameter = pyinspect.signature(DetectarRepository.set_source_run_items).parameters["data_mode"]

    assert parameter.kind is pyinspect.Parameter.KEYWORD_ONLY
    assert parameter.default is pyinspect.Parameter.empty
