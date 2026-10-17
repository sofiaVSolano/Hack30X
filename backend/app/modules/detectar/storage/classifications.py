"""Lectura de clasificaciones (E9). Toda lectura exige ``data_mode``."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.detectar.storage.models import (
    ClassificationEvidence,
    DataMode,
    EvidenceRole,
    Source,
    TrendClassification,
    TrendStage,
)
from app.modules.detectar.storage.repository import MAX_LIST_LIMIT, require_data_mode


class ClassificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _filter(self, data_mode, topic_id, source, stage, rules_version, as_of, include_superseded):
        mode = require_data_mode(data_mode)
        stmt = select(TrendClassification).where(TrendClassification.data_mode == mode)
        if not include_superseded:
            stmt = stmt.where(TrendClassification.superseded_at.is_(None))
        if topic_id is not None:
            stmt = stmt.where(TrendClassification.topic_id == topic_id)
        if stage is not None:
            stmt = stmt.where(TrendClassification.stage == TrendStage(stage))
        if rules_version is not None:
            stmt = stmt.where(TrendClassification.rules_version == rules_version)
        if as_of is not None:
            stmt = stmt.where(TrendClassification.as_of == datetime.combine(as_of, time.min, tzinfo=UTC))
        if source is not None:
            # Fuente que aportó evidencia (primaria o complementaria), no las excluidas.
            evidence = (
                select(ClassificationEvidence.id)
                .where(
                    ClassificationEvidence.classification_id == TrendClassification.id,
                    ClassificationEvidence.source == Source(source),
                    ClassificationEvidence.role != EvidenceRole.EXCLUDED,
                )
                .exists()
            )
            stmt = stmt.where(evidence)
        return stmt

    def list_classifications(
        self,
        *,
        data_mode: DataMode | str,
        topic_id: str | None = None,
        source: Source | None = None,
        stage: TrendStage | None = None,
        rules_version: str | None = None,
        as_of: date | None = None,
        include_superseded: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TrendClassification]:
        if not 1 <= limit <= MAX_LIST_LIMIT or offset < 0:
            raise ValueError("limit u offset fuera de rango")
        stmt = self._filter(data_mode, topic_id, source, stage, rules_version, as_of, include_superseded)
        stmt = stmt.order_by(TrendClassification.as_of.desc(), TrendClassification.topic_id, TrendClassification.id)
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))

    def count_classifications(
        self,
        *,
        data_mode: DataMode | str,
        topic_id: str | None = None,
        source: Source | None = None,
        stage: TrendStage | None = None,
        rules_version: str | None = None,
        as_of: date | None = None,
        include_superseded: bool = False,
    ) -> int:
        stmt = self._filter(data_mode, topic_id, source, stage, rules_version, as_of, include_superseded)
        return int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    def evidence_for(
        self, classification_ids: Sequence[int], *, data_mode: DataMode | str
    ) -> dict[int, list[ClassificationEvidence]]:
        mode = require_data_mode(data_mode)
        grouped: dict[int, list[ClassificationEvidence]] = defaultdict(list)
        if not classification_ids:
            return grouped
        stmt = (
            select(ClassificationEvidence)
            .join(TrendClassification, TrendClassification.id == ClassificationEvidence.classification_id)
            .where(
                TrendClassification.data_mode == mode,
                ClassificationEvidence.classification_id.in_(list(classification_ids)),
            )
            .order_by(ClassificationEvidence.classification_id, ClassificationEvidence.source)
        )
        for row in self._session.scalars(stmt):
            grouped[row.classification_id].append(row)
        return grouped
