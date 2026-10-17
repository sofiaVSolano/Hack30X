"""Repositorio de ejecuciones de agentes.

Igual que el repositorio de E2, cada método público exige ``data_mode`` y nunca mezcla
datos reales y simulados. Los cambios de estado son condicionales (compare-and-set): solo
se aplican si el estado actual permite la transición, y SQLite lo vuelve a comprobar
con un trigger.
"""

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.detectar.logsafety import redact
from app.modules.detectar.storage.models import (
    AGENT_RUN_TRANSITIONS,
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    DataMode,
)
from app.modules.detectar.storage.repository import MAX_LIST_LIMIT, require_data_mode

ERROR_DETAIL_MAX_LENGTH = 500
MAX_JSON_BYTES = 200_000


class InvalidTransitionError(ValueError):
    pass


def ensure_transition(current: AgentRunStatus, new: AgentRunStatus) -> None:
    if new not in AGENT_RUN_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"Transición inválida de {current.value!r} a {new.value!r}"
        )


def _check_json(value: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} debe ser un objeto JSON (dict)")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} no es serializable como JSON: {exc}") from None
    if len(encoded.encode()) > MAX_JSON_BYTES:
        raise ValueError(f"{name} supera {MAX_JSON_BYTES} bytes")
    return value


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        agent_id: str,
        *,
        data_mode: DataMode | str,
        trigger: AgentRunTrigger,
        requested_at: datetime,
        params: dict[str, Any] | None = None,
        collection_run_id: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=f"arun_{uuid4().hex}",
            agent_id=agent_id,
            data_mode=require_data_mode(data_mode),
            trigger=AgentRunTrigger(trigger),
            status=AgentRunStatus.PENDING,
            requested_at=requested_at,
            collection_run_id=collection_run_id,
            params=_check_json(params or {}, "params"),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: str, *, data_mode: DataMode | str) -> AgentRun | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.data_mode == mode)
        )

    def list_runs(
        self,
        *,
        data_mode: DataMode | str,
        agent_id: str | None = None,
        status: AgentRunStatus | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        mode = require_data_mode(data_mode)
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit debe estar entre 1 y {MAX_LIST_LIMIT}")
        stmt = select(AgentRun).where(AgentRun.data_mode == mode)
        if agent_id is not None:
            stmt = stmt.where(AgentRun.agent_id == agent_id)
        if status is not None:
            stmt = stmt.where(AgentRun.status == AgentRunStatus(status))
        stmt = stmt.order_by(AgentRun.requested_at.desc(), AgentRun.id.desc()).limit(limit)
        return list(self._session.scalars(stmt))

    def latest(self, agent_id: str, *, data_mode: DataMode | str) -> AgentRun | None:
        runs = self.list_runs(data_mode=data_mode, agent_id=agent_id, limit=1)
        return runs[0] if runs else None

    def list_active(self, *, data_mode: DataMode | str) -> list[AgentRun]:
        """Ejecuciones en ``pending`` o ``running`` (E11: candidatas a revisar)."""
        mode = require_data_mode(data_mode)
        stmt = (
            select(AgentRun)
            .where(
                AgentRun.data_mode == mode,
                AgentRun.status.in_([AgentRunStatus.PENDING, AgentRunStatus.RUNNING]),
            )
            .order_by(AgentRun.requested_at, AgentRun.id)
        )
        return list(self._session.scalars(stmt))

    def mark_running(self, run_id: str, *, data_mode: DataMode | str, started_at: datetime) -> AgentRun:
        return self._transition(
            run_id, AgentRunStatus.RUNNING, data_mode=data_mode, started_at=started_at
        )

    def mark_completed(
        self,
        run_id: str,
        *,
        data_mode: DataMode | str,
        finished_at: datetime,
        result: dict[str, Any],
    ) -> AgentRun:
        if result is None:
            raise ValueError("Una ejecución completada requiere un resultado estructurado")
        return self._transition(
            run_id,
            AgentRunStatus.COMPLETED,
            data_mode=data_mode,
            finished_at=finished_at,
            result=_check_json(result, "result"),
        )

    def mark_failed(
        self,
        run_id: str,
        *,
        data_mode: DataMode | str,
        finished_at: datetime,
        error_code: str,
        error_detail: str,
    ) -> AgentRun:
        return self._finish_with_error(
            run_id, AgentRunStatus.FAILED, data_mode, finished_at, error_code, error_detail
        )

    def mark_blocked(
        self,
        run_id: str,
        *,
        data_mode: DataMode | str,
        finished_at: datetime,
        error_code: str,
        error_detail: str,
    ) -> AgentRun:
        return self._finish_with_error(
            run_id, AgentRunStatus.BLOCKED, data_mode, finished_at, error_code, error_detail
        )

    # --- internos ---------------------------------------------------------------

    def _finish_with_error(
        self,
        run_id: str,
        status: AgentRunStatus,
        data_mode: DataMode | str,
        finished_at: datetime,
        error_code: str,
        error_detail: str,
    ) -> AgentRun:
        if not error_code or not error_detail:
            raise ValueError("Un fallo o bloqueo requiere error_code y error_detail")
        return self._transition(
            run_id,
            status,
            data_mode=data_mode,
            finished_at=finished_at,
            error_code=error_code[:64],
            error_detail=redact(error_detail)[:ERROR_DETAIL_MAX_LENGTH],
        )

    def _transition(
        self,
        run_id: str,
        new_status: AgentRunStatus,
        *,
        data_mode: DataMode | str,
        **values: Any,
    ) -> AgentRun:
        mode = require_data_mode(data_mode)
        run = self.get(run_id, data_mode=mode)
        if run is None:
            raise LookupError(f"No existe la ejecución {run_id!r} con data_mode={mode.value!r}")
        ensure_transition(run.status, new_status)
        allowed_from = [s for s, targets in AGENT_RUN_TRANSITIONS.items() if new_status in targets]
        # Actualización condicional: si otro proceso cambió el estado, no se aplica.
        outcome = self._session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.data_mode == mode,
                AgentRun.status == run.status,
                AgentRun.status.in_(allowed_from),
            )
            .values(status=new_status, **values)
            .execution_options(synchronize_session=False)
        )
        if outcome.rowcount != 1:
            raise InvalidTransitionError(
                f"La ejecución {run_id!r} cambió de estado durante la transición"
            )
        self._session.refresh(run)
        return run
