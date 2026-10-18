"""Repositorio de propuestas. Toda lectura exige ``data_mode``, como en DETECTAR."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.crear.storage.models import Proposal
from app.modules.detectar.storage.models import DataMode

MAX_LIMIT = 200


class ProposalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, proposals: list[Proposal]) -> None:
        self._session.add_all(proposals)
        self._session.flush()

    def get(self, proposal_id: str, *, data_mode: DataMode) -> Proposal | None:
        proposal = self._session.get(Proposal, proposal_id)
        return proposal if proposal is not None and proposal.data_mode is data_mode else None

    def lineage(self, root_id: str, *, data_mode: DataMode) -> list[Proposal]:
        stmt = (
            select(Proposal)
            .where(Proposal.root_id == root_id, Proposal.data_mode == data_mode)
            .order_by(Proposal.version)
        )
        return list(self._session.scalars(stmt))

    def last_version(self, root_id: str, *, data_mode: DataMode) -> int:
        stmt = select(func.max(Proposal.version)).where(Proposal.root_id == root_id, Proposal.data_mode == data_mode)
        return int(self._session.scalar(stmt) or 0)

    def _filtered(self, data_mode: DataMode, topic_id: str | None, batch_id: str | None):
        stmt = select(Proposal).where(Proposal.data_mode == data_mode)
        if topic_id is not None:
            stmt = stmt.where(Proposal.topic_id == topic_id)
        if batch_id is not None:
            stmt = stmt.where(Proposal.batch_id == batch_id)
        return stmt

    def list(
        self,
        *,
        data_mode: DataMode,
        topic_id: str | None = None,
        batch_id: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[Proposal]:
        if not 1 <= limit <= MAX_LIMIT or offset < 0:
            raise ValueError("limit u offset fuera de rango")
        stmt = self._filtered(data_mode, topic_id, batch_id).order_by(
            Proposal.created_at.desc(), Proposal.batch_id, Proposal.id
        )
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))

    def count(self, *, data_mode: DataMode, topic_id: str | None = None, batch_id: str | None = None) -> int:
        stmt = self._filtered(data_mode, topic_id, batch_id)
        return int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
