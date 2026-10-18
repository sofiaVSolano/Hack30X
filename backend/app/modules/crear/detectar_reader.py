"""Lectura de DETECTAR para CREAR (solo lectura).

CREAR se alimenta de lo que DETECTAR ya calculó y guardó: temas normalizados (E7), métricas
``metrics-v1`` (E8) y clasificaciones vigentes (E9). Este módulo es su único punto de
contacto con ese almacenamiento:

- no escribe ni recalcula: si DETECTAR no calculó algo, CREAR no lo inventa;
- exige ``data_mode`` en cada consulta, como los repositorios de DETECTAR;
- devuelve copias inmutables, no objetos de SQLAlchemy, para que el resto de CREAR no
  dependa del esquema de DETECTAR.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.detectar.metrics.definitions import PARAMS as METRICS_PARAMS
from app.modules.detectar.metrics.definitions import (
    RULES_VERSION as METRICS_RULES_VERSION,
)
from app.modules.detectar.storage.models import (
    DataMode,
    MetricStatus,
    MetricValue,
    RawObservation,
    Source,
    Topic,
    TrendClassification,
    TrendStage,
)
from app.modules.detectar.storage.repository import require_data_mode
from app.modules.detectar.storage.topics import TopicRepository

# metric_key de las observaciones del RSS de Google Trends (una por tendencia y captura).
GTR_PRESENCE_OBSERVATION = "gtr_trending_presence"


@dataclass(frozen=True)
class TopicInfo:
    id: str
    name: str
    data_mode: DataMode
    ambiguous: bool
    links_by_source: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StageInfo:
    stage: TrendStage
    reason: str | None
    as_of: date
    rules_version: str
    calibrated: bool


@dataclass(frozen=True)
class MetricInfo:
    topic_id: str
    source: Source
    scope: str
    key: str
    unit: str
    value: float | None
    ok: bool
    reason: str | None
    validated: bool
    details: dict[str, object]


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


class DetectarReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- temas -------------------------------------------------------------------------

    def topic(self, topic_id: str, *, data_mode: DataMode | str) -> TopicInfo | None:
        repo = TopicRepository(self._session)
        topic = repo.get_topic(topic_id, data_mode=data_mode)
        if topic is None:
            return None
        counts = repo.linked_counts([topic.id], data_mode=data_mode)
        return _topic_info(topic, counts.get(topic.id, {}))

    def topics(
        self, *, data_mode: DataMode | str, query: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[list[TopicInfo], int]:
        repo = TopicRepository(self._session)
        rows = repo.list_topics(data_mode=data_mode, query=query, limit=limit, offset=offset)
        counts = repo.linked_counts([t.id for t in rows], data_mode=data_mode)
        total = repo.count_topics(data_mode=data_mode, query=query)
        return [_topic_info(t, counts.get(t.id, {})) for t in rows], total

    def topic_names(self, topic_ids: Sequence[str], *, data_mode: DataMode | str) -> dict[str, str]:
        mode = require_data_mode(data_mode)
        if not topic_ids:
            return {}
        stmt = select(Topic.id, Topic.canonical_name).where(Topic.data_mode == mode, Topic.id.in_(list(topic_ids)))
        return {topic_id: name for topic_id, name in self._session.execute(stmt)}

    # --- etapas ------------------------------------------------------------------------

    def current_stages(self, topic_ids: Sequence[str], *, data_mode: DataMode | str) -> dict[str, StageInfo]:
        """Clasificación vigente más reciente de cada tema (la de mayor fecha de referencia)."""
        mode = require_data_mode(data_mode)
        if not topic_ids:
            return {}
        stmt = (
            select(TrendClassification)
            .where(
                TrendClassification.data_mode == mode,
                TrendClassification.topic_id.in_(list(topic_ids)),
                TrendClassification.superseded_at.is_(None),
            )
            .order_by(
                TrendClassification.topic_id,
                TrendClassification.as_of.desc(),
                TrendClassification.computed_at.desc(),
                TrendClassification.id.desc(),
            )
        )
        stages: dict[str, StageInfo] = {}
        for row in self._session.scalars(stmt):
            stages.setdefault(
                row.topic_id,
                StageInfo(row.stage, row.reason, row.as_of.date(), row.rules_version, row.calibrated),
            )
        return stages

    # --- métricas ----------------------------------------------------------------------

    def latest_metrics_date(self, *, data_mode: DataMode | str) -> date | None:
        """Última fecha de referencia con métricas ``metrics-v1`` calculadas en ese modo."""
        mode = require_data_mode(data_mode)
        latest = self._session.scalar(
            select(func.max(MetricValue.as_of)).where(
                MetricValue.data_mode == mode, MetricValue.rules_version == METRICS_RULES_VERSION
            )
        )
        return latest.date() if latest is not None else None

    def metrics(
        self,
        *,
        data_mode: DataMode | str,
        as_of: date,
        keys: Sequence[str],
        topic_ids: Sequence[str] | None = None,
    ) -> list[MetricInfo]:
        mode = require_data_mode(data_mode)
        stmt = select(MetricValue).where(
            MetricValue.data_mode == mode,
            MetricValue.as_of == _day_start(as_of),
            MetricValue.rules_version == METRICS_RULES_VERSION,
            MetricValue.metric_key.in_(list(keys)),
        )
        if topic_ids is not None:
            stmt = stmt.where(MetricValue.topic_id.in_(list(topic_ids)))
        stmt = stmt.order_by(MetricValue.topic_id, MetricValue.source, MetricValue.scope, MetricValue.metric_key)
        return [
            MetricInfo(
                topic_id=m.topic_id,
                source=m.source,
                scope=m.scope,
                key=m.metric_key,
                unit=m.unit.value,
                value=m.value,
                ok=m.status is MetricStatus.OK and m.value is not None,
                reason=m.reason,
                validated=m.source_validated,
                details=dict(m.details or {}),
            )
            for m in self._session.scalars(stmt)
        ]

    def gtr_known_captures(self, *, data_mode: DataMode | str, as_of: date) -> dict[str, int]:
        """Capturas conocidas del RSS por país en la ventana actual de ``metrics-v1``.

        Misma definición que E8: instantes con al menos una tendencia guardada para el país.
        Permite distinguir «el país se capturó y el tema no apareció» (medido) de «el país no
        se capturó» (sin medición).
        """
        mode = require_data_mode(data_mode)
        days = int(METRICS_PARAMS["window_days"])
        start, end = _day_start(as_of - timedelta(days=days - 1)), _day_start(as_of + timedelta(days=1))
        stmt = (
            select(RawObservation.country, func.count(func.distinct(RawObservation.observed_at)))
            .where(
                RawObservation.data_mode == mode,
                RawObservation.source == Source.GOOGLE_TRENDS_RSS,
                RawObservation.metric_key == GTR_PRESENCE_OBSERVATION,
                RawObservation.observed_at >= start,
                RawObservation.observed_at < end,
                RawObservation.country.is_not(None),
            )
            .group_by(RawObservation.country)
        )
        return {country: int(count) for country, count in self._session.execute(stmt)}


def _topic_info(topic: Topic, counts: dict[str, int]) -> TopicInfo:
    return TopicInfo(topic.id, topic.canonical_name, topic.data_mode, topic.ambiguous, dict(counts))
