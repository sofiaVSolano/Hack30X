"""Recuperación conservadora de ejecuciones abandonadas (E11)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.modules.detectar.agents.recovery import ABANDONED_CODE, recover_abandoned_runs
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRunStatus,
    AgentRunTrigger,
    DataMode,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
ABANDON = timedelta(hours=1)
TIMEOUT = timedelta(seconds=300)


def make_run(session_factory, *, status: AgentRunStatus, age: timedelta, mode=DataMode.REAL, agent="trend_hunter") -> str:
    """Crea una ejecución cuya marca de tiempo persistida tiene la antigüedad indicada."""
    since = NOW - age
    with session_factory() as session, session.begin():
        repo = AgentRunRepository(session)
        run = repo.create(agent, data_mode=mode, trigger=AgentRunTrigger.MANUAL, requested_at=since)
        if status in (AgentRunStatus.RUNNING, AgentRunStatus.COMPLETED):
            repo.mark_running(run.id, data_mode=mode, started_at=since)
        if status is AgentRunStatus.COMPLETED:
            repo.mark_completed(run.id, data_mode=mode, finished_at=since + timedelta(seconds=1), result={"ok": True})
        return run.id


def recover(session_factory, active=(), modes=(DataMode.REAL, DataMode.SIMULATED)):
    return recover_abandoned_runs(
        session_factory, now=NOW, abandon_after=ABANDON, active_run_ids=active, task_timeout=TIMEOUT, data_modes=modes
    )


def status_of(session_factory, run_id: str, mode=DataMode.REAL):
    with session_factory() as session:
        return AgentRunRepository(session).get(run_id, data_mode=mode)


def test_recent_running_run_is_not_recovered(session_factory) -> None:
    run_id = make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(minutes=59))

    report = recover(session_factory)

    assert report.skipped_recent == [run_id] and report.recovered == []
    assert status_of(session_factory, run_id).status is AgentRunStatus.RUNNING


def test_old_running_and_pending_runs_are_closed_as_abandoned(session_factory) -> None:
    running = make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2))
    pending = make_run(session_factory, status=AgentRunStatus.PENDING, age=timedelta(hours=3), agent="supervisor")

    report = recover(session_factory)

    assert sorted(report.recovered) == sorted([running, pending])
    for run_id, previous in ((running, "running"), (pending, "pending")):
        run = status_of(session_factory, run_id)
        assert run.status is AgentRunStatus.FAILED
        assert run.error_code == ABANDONED_CODE
        assert f"en estado {previous}" in run.error_detail and "3600 s" in run.error_detail
        assert run.result is None and run.finished_at == NOW


def test_run_active_in_this_process_is_never_recovered_even_if_old(session_factory) -> None:
    slow = make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(days=2))

    report = recover(session_factory, active={slow})

    assert report.skipped_active == [slow] and report.recovered == []
    assert status_of(session_factory, slow).status is AgentRunStatus.RUNNING


def test_finished_runs_and_history_are_not_touched(session_factory) -> None:
    done = make_run(session_factory, status=AgentRunStatus.COMPLETED, age=timedelta(days=5))
    make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2), agent="supervisor")
    with session_factory() as session:
        before = session.execute(text("SELECT * FROM agent_runs WHERE id = :i"), {"i": done}).one()

    recover(session_factory)

    with session_factory() as session:
        assert session.execute(text("SELECT * FROM agent_runs WHERE id = :i"), {"i": done}).one() == before
        assert session.execute(text("SELECT count(*) FROM agent_runs")).scalar() == 2  # nada se borra


def test_recovery_is_idempotent(session_factory) -> None:
    make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2))

    first = recover(session_factory)
    second = recover(session_factory)

    assert len(first.recovered) == 1
    assert second.recovered == [] and second.errors == []


def test_persistence_errors_are_reported_not_counted_as_recovered(session_factory, monkeypatch) -> None:
    run_id = make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2))

    def broken(*args, **kwargs):
        raise OperationalError("UPDATE agent_runs", {}, Exception("database is locked"))

    monkeypatch.setattr(AgentRunRepository, "mark_failed", broken)
    report = recover(session_factory)

    assert report.recovered == []
    assert report.errors == [{"run_id": run_id, "error": "OperationalError"}]
    monkeypatch.undo()
    assert status_of(session_factory, run_id).status is AgentRunStatus.RUNNING


def test_modes_are_isolated(session_factory) -> None:
    simulated = make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2), mode=DataMode.SIMULATED)

    report = recover(session_factory, modes=(DataMode.REAL,))

    assert report.recovered == []
    assert status_of(session_factory, simulated, DataMode.SIMULATED).status is AgentRunStatus.RUNNING


def test_threshold_must_exceed_twice_the_task_timeout(session_factory) -> None:
    with pytest.raises(ValueError):
        recover_abandoned_runs(
            session_factory, now=NOW, abandon_after=timedelta(seconds=500), active_run_ids=(), task_timeout=TIMEOUT
        )


def test_recovered_agent_is_no_longer_busy(session_factory) -> None:
    import asyncio

    from app.modules.detectar.agents.coordinator import (
        AgentBusyError,
        LocalAgentCoordinator,
    )
    from app.modules.detectar.agents.registry import default_registry

    make_run(session_factory, status=AgentRunStatus.RUNNING, age=timedelta(hours=2), agent="analyst")
    coordinator = LocalAgentCoordinator(session_factory, default_registry())
    with pytest.raises(AgentBusyError):
        asyncio.run(coordinator.start("analyst", data_mode="real"))

    recover(session_factory)

    assert asyncio.run(coordinator.start("analyst", data_mode="real")).status is AgentRunStatus.BLOCKED
