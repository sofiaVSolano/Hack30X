"""Lectura de métricas calculadas (E8). Toda lectura exige ``data_mode``."""

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.detectar.storage.models import (
    MetricStatus,
    MetricValue,
    RulesVersion,
    Source,
)
from app.modules.detectar.storage.repository import (
    MAX_LIST_LIMIT,
    DataMode,
    require_data_mode,
)


class MetricRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _filter(self, data_mode, topic_id, source, metric_key, status, as_of):
        mode = require_data_mode(data_mode)
        stmt = select(MetricValue).where(MetricValue.data_mode == mode)
        if topic_id is not None:
            stmt = stmt.where(MetricValue.topic_id == topic_id)
        if source is not None:
            stmt = stmt.where(MetricValue.source == Source(source))
        if metric_key is not None:
            stmt = stmt.where(MetricValue.metric_key == metric_key)
        if status is not None:
            stmt = stmt.where(MetricValue.status == MetricStatus(status))
        if as_of is not None:
            stmt = stmt.where(MetricValue.as_of == datetime.combine(as_of, time.min, tzinfo=UTC))
        return stmt

    def list_values(
        self,
        *,
        data_mode: DataMode | str,
        topic_id: str | None = None,
        source: Source | None = None,
        metric_key: str | None = None,
        status: MetricStatus | None = None,
        as_of: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MetricValue]:
        if not 1 <= limit <= MAX_LIST_LIMIT or offset < 0:
            raise ValueError("limit u offset fuera de rango")
        stmt = self._filter(data_mode, topic_id, source, metric_key, status, as_of)
        stmt = stmt.order_by(
            MetricValue.as_of.desc(),
            MetricValue.topic_id,
            MetricValue.source,
            MetricValue.scope,
            MetricValue.metric_key,
        )
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))

    def count_values(
        self,
        *,
        data_mode: DataMode | str,
        topic_id: str | None = None,
        source: Source | None = None,
        metric_key: str | None = None,
        status: MetricStatus | None = None,
        as_of: date | None = None,
    ) -> int:
        stmt = self._filter(data_mode, topic_id, source, metric_key, status, as_of)
        return int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    def rules_version(self, version: str, *, data_mode: DataMode | str) -> RulesVersion | None:
        """Las versiones son comunes a ambos modos; se exige data_mode por coherencia."""
        require_data_mode(data_mode)
        return self._session.get(RulesVersion, version)
