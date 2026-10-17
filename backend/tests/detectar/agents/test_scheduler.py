"""Programador periódico (E11): plan, vencimiento, concurrencia, modos y apagado.

Sin esperas reales: reloj inyectado y llamadas directas a ``tick()``.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.detectar.agents.coordinator import LocalAgentCoordinator
from app.modules.detectar.agents.registry import default_registry
from app.modules.detectar.agents.scheduler import (
    AgentScheduler,
    build_plan,
    last_closed_utc_day,
)
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    DataMode,
)

from .test_tasks import coordinator as build_coordinator
from .test_tasks import rss_transport

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


START = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)


def settings(**overrides: Any) -> DetectarSettings:
    base = {
        "env": "test",
        "http_max_retries": 0,
        "scheduler_enabled": True,
        "agent_schedules": {"trend_hunter": 240, "supervisor": 480},
        "scheduler_agent_modes": {"trend_hunter": "real", "supervisor": "real"},
    }
    return DetectarSettings(**(base | overrides))


def scheduler(session_factory, clock: Clock, cfg: DetectarSettings | None = None, transport=None, coord=None) -> AgentScheduler:
    cfg = cfg or settings()
    coord = coord or build_coordinator(session_factory, clock=clock, transport=transport, settings=cfg)
    return AgentScheduler(coord, session_factory, default_registry(), cfg, clock=clock)


def runs(session_factory, agent_id: str | None = None) -> list[AgentRun]:
    with session_factory() as session:
        stmt = select(AgentRun).order_by(AgentRun.requested_at, AgentRun.id)
        if agent_id:
            stmt = stmt.where(AgentRun.agent_id == agent_id)
        return list(session.scalars(stmt))


# --- configuración y plan -------------------------------------------------------------------


def test_scheduler_is_disabled_by_default() -> None:
    cfg = DetectarSettings()

    assert cfg.scheduler_enabled is False
    plan = build_plan(default_registry(), cfg)
    assert plan.entries == ()
    assert set(plan.skipped.values()) == {"sin_frecuencia"}  # no se inventan frecuencias


def test_plan_only_includes_implemented_agents_with_explicit_mode() -> None:
    cfg = settings(
        agent_schedules={"trend_hunter": 240, "supervisor": 480, "analyst": 60},
        scheduler_agent_modes={"supervisor": "simulated", "analyst": "real"},
    )

    plan = build_plan(default_registry(), cfg)

    assert [(e.agent_id, e.data_mode, e.interval) for e in plan.entries] == [
        ("supervisor", DataMode.SIMULATED, timedelta(minutes=480))
    ]
    assert plan.skipped["trend_hunter"] == "sin_data_mode"
    assert plan.skipped["analyst"] == "no_implementado"
    assert plan.skipped["strategist"] == "sin_frecuencia"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"scheduler_agent_modes": {"trend_hunter": "simulated"}, "scheduler_trend_hunter_sources": ("google_trends_rss",)}, "recoleccion_solo_real"),
        ({"gtr_mode": "off", "scheduler_trend_hunter_sources": ("google_trends_rss",)}, "fuente_no_habilitada:google_trends_rss"),
    ],
)
def test_unsafe_trend_hunter_configuration_is_skipped_with_reason(overrides, reason) -> None:
    plan = build_plan(default_registry(), settings(**overrides))

    assert plan.skipped["trend_hunter"] == reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"agent_schedules": {"trend_hunter": 5}},
        {"agent_schedules": {"trend_hunter": 60 * 24 * 8}},
        {"agent_schedules": {"fantasma": 60}},
        {"scheduler_agent_modes": {"fantasma": "real"}},
    ],
)
def test_invalid_configuration_is_rejected(session_factory, overrides) -> None:
    with pytest.raises(ValueError):
        scheduler(session_factory, Clock(START), settings(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [{"scheduler_trend_hunter_sources": ("wikimedia",)}, {"scheduler_agent_modes": {"supervisor": "mixto"}}, {"agent_abandon_after_seconds": 60}],
)
def test_invalid_settings_values_are_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        settings(**overrides)


def test_abandon_threshold_must_exceed_twice_the_task_timeout(session_factory) -> None:
    coord = LocalAgentCoordinator(session_factory, default_registry(), task_timeout_seconds=400)

    with pytest.raises(ValueError):
        AgentScheduler(coord, session_factory, default_registry(), settings(agent_abandon_after_seconds=600))


# --- ejecución periódica ------------------------------------------------------------------


async def test_due_agents_run_with_scheduled_trigger(session_factory) -> None:
    sched = scheduler(session_factory, Clock(START))

    report = await sched.tick()

    assert sorted(item["agente"] for item in report.launched) == ["supervisor", "trend_hunter"]
    assert all(r.trigger is AgentRunTrigger.SCHEDULED for r in runs(session_factory))
    assert all(r.status is AgentRunStatus.COMPLETED for r in runs(session_factory))
    assert sched.last_tick is report


async def test_not_run_before_interval_and_run_after(session_factory) -> None:
    clock = Clock(START)
    sched = scheduler(session_factory, clock)
    await sched.tick()

    clock.now = START + timedelta(minutes=239)
    early = await sched.tick()
    clock.now = START + timedelta(minutes=240)
    due = await sched.tick()

    assert sorted(early.not_due) == ["supervisor", "trend_hunter"] and early.launched == []
    assert [item["agente"] for item in due.launched] == ["trend_hunter"]
    assert due.not_due == ["supervisor"]
    assert len(runs(session_factory, "trend_hunter")) == 2


async def test_recent_manual_run_postpones_the_scheduled_one(session_factory) -> None:
    clock = Clock(START)
    await build_coordinator(session_factory, clock=clock).start("supervisor", data_mode="real", params={})

    report = await scheduler(session_factory, clock).tick()

    assert "supervisor" in report.not_due


async def test_trend_hunter_uses_last_closed_utc_day(session_factory) -> None:
    # 22:00 en Bogotá (UTC-5) del 16 = 03:00 UTC del 17: el último día cerrado UTC es el 16.
    clock = Clock(datetime(2026, 10, 16, 22, 0, tzinfo=timezone(timedelta(hours=-5))))

    await scheduler(session_factory, clock).tick()

    (run,) = runs(session_factory, "trend_hunter")
    assert run.params["as_of"] == "2026-10-16"
    assert last_closed_utc_day(clock.now) == date(2026, 10, 16)
    assert run.result["fecha_referencia"] == "2026-10-16"


async def test_failed_task_is_recorded_as_failed_and_others_still_run(session_factory) -> None:
    cfg = settings(scheduler_trend_hunter_sources=("google_trends_rss",), countries=("MX",))

    report = await scheduler(session_factory, Clock(START), cfg, transport=rss_transport({"MX": 503})).tick()

    statuses = {item["agente"]: item["estado"] for item in report.launched}
    assert statuses == {"trend_hunter": "failed", "supervisor": "completed"}
    (hunter,) = runs(session_factory, "trend_hunter")
    assert hunter.status is AgentRunStatus.FAILED and hunter.result is None


async def test_unexpected_error_does_not_stop_the_other_agents(session_factory) -> None:
    clock = Clock(START)
    coord = build_coordinator(session_factory, clock=clock)
    original = coord.start

    async def flaky(agent_id: str, **kwargs: Any):
        if agent_id == "trend_hunter":
            raise RuntimeError("fallo inesperado")
        return await original(agent_id, **kwargs)

    coord.start = flaky  # type: ignore[method-assign]
    report = await scheduler(session_factory, clock, coord=coord).tick()

    assert report.errors == [{"agente": "trend_hunter", "etapa": "ejecucion", "error": "RuntimeError"}]
    assert [item["agente"] for item in report.launched] == ["supervisor"]


async def test_scheduled_runs_respect_the_configured_mode(session_factory) -> None:
    cfg = settings(scheduler_agent_modes={"trend_hunter": "simulated", "supervisor": "simulated"})

    await scheduler(session_factory, Clock(START), cfg).tick()

    assert {r.data_mode for r in runs(session_factory)} == {DataMode.SIMULATED}


async def test_supervisor_schedule_does_not_trigger_other_agents(session_factory) -> None:
    cfg = settings(agent_schedules={"supervisor": 60}, scheduler_agent_modes={"supervisor": "real"})

    await scheduler(session_factory, Clock(START), cfg).tick()

    assert [r.agent_id for r in runs(session_factory)] == ["supervisor"]


# --- concurrencia ---------------------------------------------------------------------------


async def test_concurrent_ticks_do_not_duplicate_runs(session_factory) -> None:
    release = asyncio.Event()

    async def slow_supervisor(_context):
        await release.wait()
        return {"ok": True}

    clock = Clock(START)
    coord = LocalAgentCoordinator(session_factory, default_registry(), tasks={"supervisor": slow_supervisor}, clock=clock)
    cfg = settings(agent_schedules={"supervisor": 60}, scheduler_agent_modes={"supervisor": "real"})
    sched = AgentScheduler(coord, session_factory, default_registry(), cfg, clock=clock)

    first = asyncio.create_task(sched.tick())
    await asyncio.sleep(0.01)
    # 61 min después: el agente vence y la ejecución en curso supera el umbral de abandono
    # (60 min), pero sigue activa en este proceso.
    clock.now = START + timedelta(minutes=61)
    second = await sched.tick()
    release.set()
    await first

    (run,) = runs(session_factory, "supervisor")
    assert second.busy == ["supervisor"]  # ocupado, no fallido ni duplicado
    assert second.errors == []
    assert second.recovery.skipped_active == [run.id]  # una tarea lenta no se declara abandonada
    assert second.recovery.recovered == []
    assert run.status is AgentRunStatus.COMPLETED


async def test_active_manual_run_is_respected_and_not_marked_failed(session_factory) -> None:
    clock = Clock(START)
    with session_factory() as session, session.begin():
        AgentRunRepository(session).create(
            "supervisor", data_mode="real", trigger=AgentRunTrigger.MANUAL, requested_at=START - timedelta(minutes=30)
        )
    cfg = settings(agent_schedules={"supervisor": 15}, scheduler_agent_modes={"supervisor": "real"})

    report = await scheduler(session_factory, clock, cfg).tick()

    assert report.busy == ["supervisor"]
    (run,) = runs(session_factory, "supervisor")
    assert run.status is AgentRunStatus.PENDING  # reciente: ni se duplica ni se cierra


async def test_tick_recovers_abandoned_run_and_then_launches(session_factory) -> None:
    clock = Clock(START)
    with session_factory() as session, session.begin():
        AgentRunRepository(session).create(
            "supervisor", data_mode="real", trigger=AgentRunTrigger.MANUAL, requested_at=START - timedelta(hours=2)
        )
    cfg = settings(agent_schedules={"supervisor": 60}, scheduler_agent_modes={"supervisor": "real"})

    report = await scheduler(session_factory, clock, cfg).tick()

    assert len(report.recovery.recovered) == 1
    assert [item["agente"] for item in report.launched] == ["supervisor"]
    statuses = [r.status for r in runs(session_factory, "supervisor")]
    assert statuses == [AgentRunStatus.FAILED, AgentRunStatus.COMPLETED]


# --- inicio y apagado -----------------------------------------------------------------------


async def test_start_and_orderly_stop_without_real_waits(session_factory) -> None:
    sched = scheduler(session_factory, Clock(START), settings(scheduler_tick_seconds=3600))

    assert sched.start() is True
    assert sched.start() is False  # idempotente: no crea otra tarea
    for _ in range(20):
        if sched.last_tick is not None:
            break
        await asyncio.sleep(0)
    await sched.stop(timeout=5)

    assert sched.running is False
    assert sched.last_tick is not None
    assert len(runs(session_factory)) == 2


async def test_disabled_scheduler_never_starts(session_factory) -> None:
    sched = scheduler(session_factory, Clock(START), settings(scheduler_enabled=False))

    assert sched.start() is False and sched.running is False
    await sched.stop()


async def test_stop_cancels_a_hung_tick(session_factory) -> None:
    async def hung(_context):
        await asyncio.Event().wait()
        return {}

    clock = Clock(START)
    coord = LocalAgentCoordinator(session_factory, default_registry(), tasks={"supervisor": hung}, clock=clock)
    cfg = settings(agent_schedules={"supervisor": 60}, scheduler_agent_modes={"supervisor": "real"})
    sched = AgentScheduler(coord, session_factory, default_registry(), cfg, clock=clock)

    sched.start()
    await asyncio.sleep(0.01)
    await sched.stop(timeout=0.05)

    assert sched.running is False
    (run,) = runs(session_factory, "supervisor")
    assert run.status is AgentRunStatus.RUNNING  # queda para la recuperación; no se finge éxito
    assert coord.active_run_ids() == frozenset()

