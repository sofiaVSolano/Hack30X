"""Programador periódico de la oficina (E11). Ver docs/e11-programador-periodico.md.

- Apagado por defecto (``DETECTAR_SCHEDULER_ENABLED``).
- Reutiliza ``resolve_schedules`` para las frecuencias y el coordinador compartido para
  ejecutar (``trigger=scheduled``).
- Solo programa agentes implementados, con frecuencia y con ``data_mode`` explícito.
- Cada tick: primero recupera ejecuciones abandonadas; luego lanza los agentes vencidos,
  uno a uno. ``AgentBusyError`` no es un fallo. Un error no detiene el bucle.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import (
    AgentBusyError,
    LocalAgentCoordinator,
)
from app.modules.detectar.agents.definitions import ImplementationStatus
from app.modules.detectar.agents.recovery import RecoveryReport, recover_abandoned_runs
from app.modules.detectar.agents.registry import AgentRegistry
from app.modules.detectar.agents.tasks import SupervisorParams, TrendHunterParams
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.ingestion.collection import source_availability
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import AgentRunTrigger, DataMode, Source
from app.modules.detectar.timeutil import format_utc

logger = logging.getLogger(__name__)

ParamsBuilder = Callable[[datetime], dict[str, Any]]


@dataclass(frozen=True)
class ScheduleEntry:
    agent_id: str
    interval: timedelta
    data_mode: DataMode
    build_params: ParamsBuilder


@dataclass(frozen=True)
class SchedulePlan:
    entries: tuple[ScheduleEntry, ...]
    skipped: dict[str, str]  # agente -> motivo


@dataclass
class TickReport:
    at: datetime
    recovery: RecoveryReport | None = None
    launched: list[dict[str, str]] = field(default_factory=list)
    not_due: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "momento": format_utc(self.at),
            "recuperacion": self.recovery.as_dict() if self.recovery else None,
            "lanzadas": list(self.launched),
            "no_vencidas": list(self.not_due),
            "ocupadas": list(self.busy),
            "errores": list(self.errors),
        }


def last_closed_utc_day(now: datetime):
    """Último día cerrado en UTC (no depende de la hora local del equipo)."""
    return now.astimezone(UTC).date() - timedelta(days=1)


def build_plan(registry: AgentRegistry, settings: DetectarSettings) -> SchedulePlan:
    """Decide qué agentes se programan. Frecuencias inválidas -> ValueError (no se ignoran)."""
    intervals = registry.resolve_schedules(settings.agent_schedules)
    unknown_modes = set(settings.scheduler_agent_modes) - set(registry.ids)
    if unknown_modes:
        raise ValueError(f"Agentes desconocidos en DETECTAR_SCHEDULER_AGENT_MODES: {sorted(unknown_modes)}")
    entries: list[ScheduleEntry] = []
    skipped: dict[str, str] = {}
    for definition in registry.all():
        agent_id = definition.id
        interval = intervals[agent_id]
        if interval is None:
            skipped[agent_id] = "sin_frecuencia"
            continue
        if definition.implementation_status is not ImplementationStatus.AVAILABLE:
            skipped[agent_id] = "no_implementado"
            continue
        raw_mode = settings.scheduler_agent_modes.get(agent_id)
        if raw_mode is None:
            skipped[agent_id] = "sin_data_mode"
            continue
        mode = DataMode(raw_mode)
        builder = _params_builder(agent_id, mode, settings)
        if isinstance(builder, str):
            skipped[agent_id] = builder
            continue
        entries.append(ScheduleEntry(agent_id, interval, mode, builder))
    return SchedulePlan(tuple(entries), skipped)


def _params_builder(agent_id: str, mode: DataMode, settings: DetectarSettings) -> ParamsBuilder | str:
    """Devuelve el constructor de parámetros o el motivo por el que no es seguro programarlo."""
    if agent_id == "trend_hunter":
        sources = tuple(Source(s) for s in settings.scheduler_trend_hunter_sources)
        if sources and mode is not DataMode.REAL:
            return "recoleccion_solo_real"
        reasons = source_availability(settings)
        disabled = [s.value for s in sources if reasons[s] is not None]
        if disabled:
            return f"fuente_no_habilitada:{','.join(disabled)}"
        countries = tuple(settings.countries)

        def trend_hunter_params(now: datetime) -> dict[str, Any]:
            collection = (
                {"sources": [s.value for s in sources], "countries": list(countries)} if sources else None
            )
            return TrendHunterParams.model_validate(
                {"as_of": last_closed_utc_day(now).isoformat(), "collection": collection}
            ).model_dump(mode="json")

        return trend_hunter_params
    if agent_id == "supervisor":
        return lambda _now: SupervisorParams().model_dump(mode="json")
    return "sin_parametros_definidos"


class AgentScheduler:
    def __init__(
        self,
        coordinator: LocalAgentCoordinator,
        session_factory: sessionmaker[Session],
        registry: AgentRegistry,
        settings: DetectarSettings,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._coordinator = coordinator
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self.plan = build_plan(registry, settings)
        self._abandon_after = timedelta(seconds=settings.agent_abandon_after_seconds)
        self._task_timeout = timedelta(seconds=coordinator.task_timeout_seconds)
        if self._abandon_after < 2 * self._task_timeout:
            raise ValueError("DETECTAR_AGENT_ABANDON_AFTER_SECONDS debe ser al menos el doble del tiempo máximo de tarea")
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self.last_tick: TickReport | None = None

    @property
    def enabled(self) -> bool:
        return self._settings.scheduler_enabled

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    def _is_due(self, entry: ScheduleEntry, now: datetime) -> bool:
        with self._session_factory() as session:
            last = AgentRunRepository(session).latest(entry.agent_id, data_mode=entry.data_mode)
        return last is None or now - last.requested_at >= entry.interval

    async def tick(self) -> TickReport:
        now = self._clock()
        report = TickReport(at=now)
        try:
            report.recovery = recover_abandoned_runs(
                self._session_factory,
                now=now,
                abandon_after=self._abandon_after,
                active_run_ids=self._coordinator.active_run_ids(),
                task_timeout=self._task_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - se informa; el resto del tick continúa
            logger.error("La recuperación de ejecuciones falló: %s", type(exc).__name__)
            report.errors.append({"agente": "*", "etapa": "recuperacion", "error": type(exc).__name__})

        for entry in self.plan.entries:
            try:
                if not self._is_due(entry, now):
                    report.not_due.append(entry.agent_id)
                    continue
                run = await self._coordinator.start(
                    entry.agent_id,
                    data_mode=entry.data_mode,
                    trigger=AgentRunTrigger.SCHEDULED,
                    params=entry.build_params(now),
                )
                report.launched.append({"agente": entry.agent_id, "run_id": run.id, "estado": run.status.value})
            except AgentBusyError:
                report.busy.append(entry.agent_id)  # ocupado no es fallido
            except Exception as exc:  # noqa: BLE001 - un agente no detiene a los demás
                logger.error("El programador no pudo ejecutar %s: %s", entry.agent_id, type(exc).__name__)
                report.errors.append({"agente": entry.agent_id, "etapa": "ejecucion", "error": type(exc).__name__})
        self.last_tick = report
        return report

    async def _loop(self) -> None:
        interval = self._settings.scheduler_tick_seconds
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    def start(self) -> bool:
        """Inicia el bucle si está habilitado. Idempotente: no crea una segunda tarea."""
        if not self.enabled or self.running:
            return False
        self._stop.clear()
        self._loop_task = asyncio.get_running_loop().create_task(self._loop(), name="detectar-scheduler")
        return True

    async def stop(self, timeout: float = 30.0) -> None:
        """Apagado ordenado: espera al tick en curso; si excede ``timeout``, lo cancela."""
        if self._loop_task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._loop_task), timeout=timeout)
        except TimeoutError:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                logger.warning("Programador cancelado durante un tick; la recuperación cerrará lo pendiente")
        self._loop_task = None
