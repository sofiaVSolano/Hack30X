"""Repositorio de temas, alias y vínculos (E7).

Igual que el resto del almacenamiento: cada método público exige ``data_mode`` como
argumento con nombre, sin valor por defecto, y nunca mezcla datos reales y simulados.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.detectar.logsafety import redact
from app.modules.detectar.storage.models import (
    AliasKind,
    Certainty,
    DataMode,
    LinkRule,
    LinkStatus,
    RawObservation,
    Source,
    Topic,
    TopicAlias,
    TopicLink,
)
from app.modules.detectar.storage.repository import MAX_LIST_LIMIT, require_data_mode
from app.modules.detectar.topics.normalize import (
    MAX_KEY_LENGTH,
    is_usable_key,
    normalize_text,
)

ACTOR_RE = re.compile(r"^[A-Za-z0-9._@-]{2,60}$")
REASON_MAX_LENGTH = 500
NAME_MAX_LENGTH = 300


class AliasConflictError(ValueError):
    """La forma normalizada ya apunta a otro tema."""


class TopicNotFoundError(LookupError):
    pass


def topic_id_for(data_mode: DataMode, normalized_key: str) -> str:
    digest = hashlib.sha256(f"{data_mode.value}:{normalized_key}".encode()).hexdigest()
    return f"tpc_{digest[:16]}"


def check_actor(actor: str) -> str:
    if not ACTOR_RE.match(actor):
        raise ValueError("autor inválido: 2 a 60 caracteres [A-Za-z0-9._@-]")
    return actor


def _check_limit(limit: int, offset: int = 0) -> None:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise ValueError(f"limit debe estar entre 1 y {MAX_LIST_LIMIT}")
    if offset < 0:
        raise ValueError("offset no puede ser negativo")


def _key(text: str) -> str:
    key = normalize_text(text)
    if not is_usable_key(key):
        raise ValueError(f"El texto {text!r} no produce una clave normalizada útil")
    return key


class TopicRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- temas -----------------------------------------------------------------

    def get_topic(self, topic_id: str, *, data_mode: DataMode | str) -> Topic | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(Topic).where(Topic.id == topic_id, Topic.data_mode == mode)
        )

    def create_topic(
        self, name: str, *, data_mode: DataMode | str, created_by: str, now: datetime
    ) -> tuple[Topic, bool]:
        """Crea el tema y su alias canónico. Idempotente: devuelve (tema, creado)."""
        mode = require_data_mode(data_mode)
        name = " ".join(name.split())[:NAME_MAX_LENGTH]
        key = _key(name)
        existing_alias = self.find_alias(key, data_mode=mode)
        if existing_alias is not None:
            topic = self.get_topic(existing_alias.topic_id, data_mode=mode)
            assert topic is not None
            return topic, False
        topic = Topic(
            id=topic_id_for(mode, key),
            data_mode=mode,
            canonical_name=name,
            normalized_key=key,
            created_by=created_by[:80],
            created_at=now,
            updated_at=now,
            ambiguous=False,
        )
        self._session.add(topic)
        self._session.flush()
        self._session.add(
            TopicAlias(
                topic_id=topic.id,
                data_mode=mode,
                alias_text=name,
                normalized_alias=key,
                kind=AliasKind.CANONICAL,
                origin=created_by[:80],
                created_at=now,
            )
        )
        self._session.flush()
        return topic, True

    def list_topics(
        self,
        *,
        data_mode: DataMode | str,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Topic]:
        _check_limit(limit, offset)
        stmt = self._topic_filter(data_mode, query).order_by(Topic.normalized_key, Topic.id)
        return list(self._session.scalars(stmt.limit(limit).offset(offset)))

    def count_topics(self, *, data_mode: DataMode | str, query: str | None = None) -> int:
        stmt = self._topic_filter(data_mode, query)
        return int(self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    def _topic_filter(self, data_mode: DataMode | str, query: str | None):
        mode = require_data_mode(data_mode)
        stmt = select(Topic).where(Topic.data_mode == mode)
        if query:
            key = normalize_text(query)
            # Búsqueda literal sobre la clave normalizada (los comodines se escapan).
            escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Topic.normalized_key.like(f"%{escaped}%", escape="\\"))
        return stmt

    def set_ambiguous(
        self,
        topic_id: str,
        *,
        data_mode: DataMode | str,
        ambiguous: bool,
        actor: str,
        reason: str | None,
        now: datetime,
    ) -> Topic:
        topic = self.get_topic(topic_id, data_mode=data_mode)
        if topic is None:
            raise TopicNotFoundError(topic_id)
        check_actor(actor)
        if ambiguous:
            if not reason or not reason.strip():
                raise ValueError("Marcar un tema como ambiguo requiere un motivo")
            topic.ambiguous = True
            topic.ambiguous_reason = redact(reason.strip())[:REASON_MAX_LENGTH]
            topic.ambiguous_marked_by = actor
            topic.ambiguous_marked_at = now
        else:
            topic.ambiguous = False
            topic.ambiguous_reason = None
            topic.ambiguous_marked_by = None
            topic.ambiguous_marked_at = None
        topic.updated_at = now
        self._session.flush()
        return topic

    # --- alias -----------------------------------------------------------------

    def find_alias(self, normalized: str, *, data_mode: DataMode | str) -> TopicAlias | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(TopicAlias).where(
                TopicAlias.data_mode == mode, TopicAlias.normalized_alias == normalized
            )
        )

    def list_aliases(self, topic_id: str, *, data_mode: DataMode | str) -> list[TopicAlias]:
        mode = require_data_mode(data_mode)
        stmt = (
            select(TopicAlias)
            .where(TopicAlias.topic_id == topic_id, TopicAlias.data_mode == mode)
            .order_by(TopicAlias.kind, TopicAlias.normalized_alias)
        )
        return list(self._session.scalars(stmt))

    def add_alias(
        self,
        topic_id: str,
        text: str,
        *,
        data_mode: DataMode | str,
        kind: AliasKind,
        origin: str,
        now: datetime,
    ) -> tuple[TopicAlias, bool]:
        """Idempotente para el mismo tema; error si la forma ya pertenece a otro tema."""
        mode = require_data_mode(data_mode)
        if AliasKind(kind) is AliasKind.CANONICAL:
            raise ValueError("El alias canónico se crea solo con el tema")
        topic = self.get_topic(topic_id, data_mode=mode)
        if topic is None:
            raise TopicNotFoundError(topic_id)
        text = " ".join(text.split())[:NAME_MAX_LENGTH]
        key = _key(text)
        existing = self.find_alias(key, data_mode=mode)
        if existing is not None:
            if existing.topic_id != topic_id:
                raise AliasConflictError(
                    f"La forma {key!r} ya pertenece al tema {existing.topic_id}"
                )
            return existing, False
        alias = TopicAlias(
            topic_id=topic_id,
            data_mode=mode,
            alias_text=text,
            normalized_alias=key,
            kind=AliasKind(kind),
            origin=origin[:80],
            created_at=now,
        )
        self._session.add(alias)
        topic.updated_at = now
        self._session.flush()
        return alias, True

    # --- vínculos --------------------------------------------------------------

    def get_link(self, link_id: int, *, data_mode: DataMode | str) -> TopicLink | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(TopicLink).where(TopicLink.id == link_id, TopicLink.data_mode == mode)
        )

    def current_link(self, observation_id: int, *, data_mode: DataMode | str) -> TopicLink | None:
        mode = require_data_mode(data_mode)
        return self._session.scalar(
            select(TopicLink).where(
                TopicLink.observation_id == observation_id,
                TopicLink.data_mode == mode,
                TopicLink.superseded_at.is_(None),
            )
        )

    def link_history(self, observation_id: int, *, data_mode: DataMode | str) -> list[TopicLink]:
        mode = require_data_mode(data_mode)
        stmt = (
            select(TopicLink)
            .where(TopicLink.observation_id == observation_id, TopicLink.data_mode == mode)
            .order_by(TopicLink.id)
        )
        return list(self._session.scalars(stmt))

    def list_links(
        self,
        *,
        data_mode: DataMode | str,
        status: LinkStatus | None = None,
        topic_id: str | None = None,
        source: Source | None = None,
        current_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TopicLink]:
        _check_limit(limit, offset)
        mode = require_data_mode(data_mode)
        stmt = select(TopicLink).where(TopicLink.data_mode == mode)
        if current_only:
            stmt = stmt.where(TopicLink.superseded_at.is_(None))
        if status is not None:
            stmt = stmt.where(TopicLink.status == LinkStatus(status))
        if topic_id is not None:
            stmt = stmt.where(TopicLink.topic_id == topic_id)
        if source is not None:
            stmt = stmt.where(TopicLink.source == Source(source))
        stmt = stmt.order_by(TopicLink.id).limit(limit).offset(offset)
        return list(self._session.scalars(stmt))

    def add_link(
        self,
        observation: RawObservation,
        *,
        data_mode: DataMode | str,
        status: LinkStatus,
        rule: LinkRule,
        certainty: Certainty,
        origin: str,
        now: datetime,
        topic_id: str | None = None,
        candidate_text: str | None = None,
        normalized_candidate: str | None = None,
        reason: str | None = None,
        supersedes_id: int | None = None,
    ) -> TopicLink:
        mode = require_data_mode(data_mode)
        if observation.data_mode is not mode:
            raise ValueError("La observación no pertenece al data_mode indicado")
        link = TopicLink(
            observation_id=observation.id,
            data_mode=mode,
            source=observation.source,
            subject_ref=observation.subject_ref,
            candidate_text=candidate_text[:500] if candidate_text else None,
            normalized_candidate=normalized_candidate[:MAX_KEY_LENGTH] if normalized_candidate else None,
            topic_id=topic_id,
            status=LinkStatus(status),
            rule=LinkRule(rule),
            certainty=Certainty(certainty),
            origin=origin[:80],
            reason=redact(reason)[:REASON_MAX_LENGTH] if reason else None,
            created_at=now,
            supersedes_id=supersedes_id,
        )
        self._session.add(link)
        self._session.flush()
        return link

    def mark_superseded(self, link_id: int, *, data_mode: DataMode | str, now: datetime) -> TopicLink:
        """Deja de ser vigente. Debe seguirle, en la misma transacción, el vínculo nuevo."""
        link = self.get_link(link_id, data_mode=data_mode)
        if link is None:
            raise LookupError(f"No existe el vínculo {link_id}")
        if link.superseded_at is not None:
            raise ValueError("El vínculo ya fue reemplazado")
        link.superseded_at = now
        self._session.flush()
        return link

    def manual_precedent(
        self, source: Source, subject_ref: str, *, data_mode: DataMode | str
    ) -> TopicLink | None:
        """Última corrección manual vigente para el mismo sujeto de la misma fuente."""
        mode = require_data_mode(data_mode)
        stmt = (
            select(TopicLink)
            .where(
                TopicLink.data_mode == mode,
                TopicLink.source == Source(source),
                TopicLink.subject_ref == subject_ref,
                TopicLink.rule == LinkRule.MANUAL_CORRECTION,
                TopicLink.superseded_at.is_(None),
            )
            .order_by(TopicLink.id.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def observations_without_link(
        self, *, data_mode: DataMode | str, source: Source | None = None, limit: int = 500
    ) -> list[RawObservation]:
        _check_limit(limit)
        mode = require_data_mode(data_mode)
        current = (
            select(TopicLink.id)
            .where(
                TopicLink.observation_id == RawObservation.id,
                TopicLink.superseded_at.is_(None),
            )
            .exists()
        )
        stmt = select(RawObservation).where(RawObservation.data_mode == mode, ~current)
        if source is not None:
            stmt = stmt.where(RawObservation.source == Source(source))
        return list(self._session.scalars(stmt.order_by(RawObservation.id).limit(limit)))

    def linked_counts(
        self, topic_ids: Sequence[str], *, data_mode: DataMode | str
    ) -> dict[str, dict[str, int]]:
        """Vínculos vigentes con estado ``linked`` por tema y fuente."""
        mode = require_data_mode(data_mode)
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        if not topic_ids:
            return counts
        stmt = (
            select(TopicLink.topic_id, TopicLink.source, func.count())
            .where(
                TopicLink.data_mode == mode,
                TopicLink.topic_id.in_(list(topic_ids)),
                TopicLink.status == LinkStatus.LINKED,
                TopicLink.superseded_at.is_(None),
            )
            .group_by(TopicLink.topic_id, TopicLink.source)
        )
        for topic_id, source, count in self._session.execute(stmt):
            counts[topic_id][source.value] = count
        return counts

    def subjects_for_topic(
        self, topic_id: str, *, data_mode: DataMode | str, limit: int = 50
    ) -> list[tuple[str, str, int]]:
        """(fuente, sujeto original, nº de observaciones) vinculados al tema."""
        _check_limit(limit)
        mode = require_data_mode(data_mode)
        stmt = (
            select(TopicLink.source, TopicLink.subject_ref, func.count())
            .where(
                TopicLink.data_mode == mode,
                TopicLink.topic_id == topic_id,
                TopicLink.status == LinkStatus.LINKED,
                TopicLink.superseded_at.is_(None),
            )
            .group_by(TopicLink.source, TopicLink.subject_ref)
            .order_by(TopicLink.source, TopicLink.subject_ref)
            .limit(limit)
        )
        return [(s.value, ref, n) for s, ref, n in self._session.execute(stmt)]
