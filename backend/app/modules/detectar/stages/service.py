"""Clasificación persistida ``stages-v1``.

Lee SOLO ``metric_values`` (E8) del ``data_mode``, la fecha de referencia y la versión de
métricas indicados. No toca ``raw_observations`` ni ``topic_links``.

Reproducibilidad (ver docs/clasificacion-etapas-v1.md, sección 8):

- misma huella de métricas y mismas versiones: no se escribe nada (idempotente);
- métricas recalculadas (otra huella): nuevo resultado; el anterior queda reemplazado;
- otra versión de reglas: filas independientes; nunca se sobrescriben.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.stages.engine import Classification, MetricSnapshot, classify
from app.modules.detectar.stages.rules import (
    METRICS_RULES_VERSION,
    PARAMS,
    RULES_VERSION,
    STAGE_DEFINITIONS,
    STAGE_METRICS,
    params_sha256,
)
from app.modules.detectar.storage.models import (
    ClassificationEvidence,
    DataMode,
    MetricValue,
    RulesVersion,
    TrendClassification,
)
from app.modules.detectar.storage.repository import require_data_mode

_STAGE_KEYS = {key for keys in STAGE_METRICS.values() for key in keys}


class StageRulesConflictError(RuntimeError):
    """La versión de reglas ya existe con otros parámetros."""


@dataclass
class ClassificationReport:
    data_mode: DataMode
    as_of: date
    rules_version: str
    created: int = 0
    unchanged: int = 0
    superseded: int = 0
    by_stage: Counter[str] = field(default_factory=Counter)


def _as_of_datetime(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _fingerprint(snapshots: Sequence[MetricSnapshot]) -> str:
    payload = sorted(
        (s.id, s.metric_key, s.scope, s.value, s.status.value, s.reason, json.dumps(s.details, sort_keys=True))
        for s in snapshots
    )
    data = json.dumps([RULES_VERSION, METRICS_RULES_VERSION, payload], default=str)
    return hashlib.sha256(data.encode()).hexdigest()


class ClassificationService:
    def __init__(self, session: Session, *, clock: Clock = utc_now) -> None:
        self._session = session
        self._clock = clock

    def classify(
        self, *, data_mode: DataMode | str, as_of: date, topic_ids: Sequence[str] | None = None
    ) -> ClassificationReport:
        mode = require_data_mode(data_mode)
        if as_of >= self._clock().astimezone(UTC).date():
            raise ValueError("as_of debe ser un día cerrado (anterior a hoy en UTC)")
        self._ensure_rules_version()
        report = ClassificationReport(data_mode=mode, as_of=as_of, rules_version=RULES_VERSION)

        stmt = select(MetricValue).where(
            MetricValue.data_mode == mode,
            MetricValue.as_of == _as_of_datetime(as_of),
            MetricValue.rules_version == METRICS_RULES_VERSION,
        )
        if topic_ids is not None:
            stmt = stmt.where(MetricValue.topic_id.in_(list(topic_ids)))
        by_topic: dict[str, list[MetricSnapshot]] = defaultdict(list)
        for row in self._session.scalars(stmt.order_by(MetricValue.id)):
            by_topic[row.topic_id].append(
                MetricSnapshot(
                    id=row.id,
                    data_mode=row.data_mode,
                    metric_key=row.metric_key,
                    source=row.source,
                    scope=row.scope,
                    unit=row.unit.value,
                    value=row.value,
                    status=row.status,
                    reason=row.reason,
                    window_days=row.window_days,
                    rules_version=row.rules_version,
                    source_validated=row.source_validated,
                    details=dict(row.details),
                )
            )

        for topic_id, snapshots in sorted(by_topic.items()):
            result = classify(snapshots, data_mode=mode)
            self._persist(report, topic_id, as_of, snapshots, result)
        self._session.flush()
        return report

    def _ensure_rules_version(self) -> None:
        sha = params_sha256()
        existing = self._session.get(RulesVersion, RULES_VERSION)
        if existing is None:
            self._session.add(
                RulesVersion(version=RULES_VERSION, params=dict(PARAMS), params_sha256=sha, created_at=self._clock())
            )
            self._session.flush()
        elif existing.params_sha256 != sha:
            raise StageRulesConflictError(f"{RULES_VERSION} ya existe con otros parámetros; cree una versión nueva")

    def _persist(self, report, topic_id, as_of, snapshots, result: Classification) -> None:
        sha = _fingerprint(snapshots)
        current = self._session.scalar(
            select(TrendClassification).where(
                TrendClassification.data_mode == report.data_mode,
                TrendClassification.topic_id == topic_id,
                TrendClassification.as_of == _as_of_datetime(as_of),
                TrendClassification.rules_version == RULES_VERSION,
                TrendClassification.metrics_rules_version == METRICS_RULES_VERSION,
                TrendClassification.superseded_at.is_(None),
            )
        )
        if current is not None and current.inputs_sha256 == sha:
            report.unchanged += 1
            report.by_stage[current.stage.value] += 1
            return
        now = self._clock()
        if current is not None:
            current.superseded_at = now
            self._session.flush()
            report.superseded += 1

        classification = TrendClassification(
            data_mode=report.data_mode,
            topic_id=topic_id,
            as_of=_as_of_datetime(as_of),
            computed_at=now,
            rules_version=RULES_VERSION,
            metrics_rules_version=METRICS_RULES_VERSION,
            stage=result.stage,
            reason=result.reason,
            calibrated=bool(PARAMS["calibrated"]),
            inputs_sha256=sha,
            metrics_considered=[
                s.as_dict() | {"used_for_stage": s.metric_key in _STAGE_KEYS} for s in result.metrics_considered
            ],
            explanation={
                "stage_definition": STAGE_DEFINITIONS[result.stage],
                "provisional": not PARAMS["calibrated"],
                "notes": list(result.notes),
                "sources": {
                    e.source.value: {
                        "role": e.role.value,
                        "proposed_stage": e.proposed_stage.value if e.proposed_stage else None,
                        "reason": e.reason,
                        "rules": [s.as_dict() for s in e.scopes],
                    }
                    for e in result.evidence
                },
            },
        )
        self._session.add(classification)
        self._session.flush()
        for item in result.evidence:
            self._session.add(
                ClassificationEvidence(
                    classification_id=classification.id,
                    source=item.source,
                    role=item.role,
                    source_validated=item.source_validated,
                    proposed_stage=item.proposed_stage,
                    reason=item.reason[:300],
                    scopes=[s.as_dict() for s in item.scopes],
                )
            )
        report.created += 1
        report.by_stage[result.stage.value] += 1
