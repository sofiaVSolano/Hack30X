"""Recuperación conservadora de ejecuciones abandonadas (E11).

Una ejecución ``pending``/``running`` se cierra como ``failed`` con el código ``abandoned``
solo si se cumplen TODAS estas condiciones (ver docs/e11-programador-periodico.md, sección 8):

1. no está entre las ejecuciones activas del coordinador de este proceso;
2. su antigüedad persistida (``started_at`` o, si sigue en ``pending``, ``requested_at``)
   alcanza el umbral;
3. la transición sigue siendo válida en el momento de cerrarla.

Nunca borra filas ni toca ejecuciones terminadas. Un error de base de datos se informa en
``errors`` y la ejecución NO cuenta como recuperada.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.storage.agent_runs import (
    AgentRunRepository,
    InvalidTransitionError,
)
from app.modules.detectar.storage.models import DataMode
from app.modules.detectar.timeutil import format_utc

logger = logging.getLogger(__name__)

ABANDONED_CODE = "abandoned"


@dataclass
class RecoveryReport:
    recovered: list[str] = field(default_factory=list)
    skipped_active: list[str] = field(default_factory=list)  # activas en este proceso
    skipped_recent: list[str] = field(default_factory=list)  # no superan el umbral
    skipped_changed: list[str] = field(default_factory=list)  # cambiaron de estado entretanto
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "recuperadas": list(self.recovered),
            "omitidas_activas": list(self.skipped_active),
            "omitidas_recientes": list(self.skipped_recent),
            "omitidas_cambiadas": list(self.skipped_changed),
            "errores": list(self.errors),
        }


def recover_abandoned_runs(
    session_factory: sessionmaker[Session],
    *,
    now: datetime,
    abandon_after: timedelta,
    active_run_ids: Iterable[str],
    task_timeout: timedelta,
    data_modes: Iterable[DataMode] = (DataMode.REAL, DataMode.SIMULATED),
) -> RecoveryReport:
    if abandon_after < 2 * task_timeout:
        raise ValueError("El umbral de abandono debe ser al menos el doble del tiempo máximo de una tarea")
    active = frozenset(active_run_ids)
    report = RecoveryReport()
    for mode in data_modes:
        with session_factory() as session:
            candidates = [
                (run.id, run.status, run.started_at or run.requested_at)
                for run in AgentRunRepository(session).list_active(data_mode=mode)
            ]
        for run_id, status, since in candidates:
            if run_id in active:
                report.skipped_active.append(run_id)
                continue
            age = now - since
            if age < abandon_after:
                report.skipped_recent.append(run_id)
                continue
            detail = (
                f"Ejecución abandonada: en estado {status.value} desde {format_utc(since)}; "
                f"superó {int(abandon_after.total_seconds())} s sin un proceso activo que la ejecute."
            )
            try:
                with session_factory() as session, session.begin():
                    AgentRunRepository(session).mark_failed(
                        run_id,
                        data_mode=mode,
                        finished_at=max(now, since),
                        error_code=ABANDONED_CODE,
                        error_detail=detail,
                    )
            except InvalidTransitionError:
                report.skipped_changed.append(run_id)  # p. ej. terminó entretanto
                continue
            except (SQLAlchemyError, LookupError) as exc:
                logger.error("No se pudo cerrar la ejecución abandonada %s: %s", run_id, type(exc).__name__)
                report.errors.append({"run_id": run_id, "error": type(exc).__name__})
                continue
            logger.warning("Ejecución %s cerrada como abandonada (%s)", run_id, status.value)
            report.recovered.append(run_id)
    return report

