"""Vinculación conservadora de observaciones con temas (reglas ``topics-v1``).

Para cada observación SIN vínculo vigente se aplica la primera regla que corresponda:

0. Sin candidato fiable (campo temático ausente o clave de menos de 2 caracteres)
   -> ``unlinked`` / ``insufficient_data``.
1. Hay una corrección manual vigente para el mismo sujeto (misma fuente y mismo
   ``subject_ref``) -> se repite esa decisión / ``manual_precedent``.
2. La clave normalizada coincide con un alias registrado:
   - si el tema está marcado como ambiguo -> ``needs_review`` / ``ambiguous_topic``
     (se propone el tema, no se vincula);
   - si es el alias canónico -> ``linked`` / ``exact_normalized``;
   - si es otro alias -> ``linked`` / ``alias``.
3. (Solo Wikipedia) El título tiene calificador, "X (algo)", y la base "X" coincide con un
   tema -> ``needs_review`` / ``disambiguation_base``. No se crea tema: lo decide una persona.
4. En otro caso -> se crea un tema nuevo -> ``linked`` / ``new_topic``.

Nunca se une por palabras compartidas, subcadenas ni similitud aproximada.
Es idempotente: solo procesa observaciones sin vínculo vigente.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.storage.models import (
    AliasKind,
    Certainty,
    DataMode,
    LinkRule,
    LinkStatus,
    RawObservation,
    Source,
    TopicLink,
)
from app.modules.detectar.storage.repository import require_data_mode
from app.modules.detectar.storage.topics import (
    TopicNotFoundError,
    TopicRepository,
    check_actor,
)
from app.modules.detectar.topics.candidates import candidate_for
from app.modules.detectar.topics.normalize import (
    RULES_VERSION,
    is_usable_key,
    normalize_text,
)

NORMALIZER_ORIGIN = f"normalizer:{RULES_VERSION}"


@dataclass
class NormalizationReport:
    data_mode: DataMode
    processed: int = 0
    topics_created: int = 0
    by_status: Counter[str] = field(default_factory=Counter)
    by_rule: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class _Decision:
    status: LinkStatus
    rule: LinkRule
    certainty: Certainty
    topic_id: str | None = None
    reason: str | None = None


class TopicLinker:
    def __init__(self, session: Session, *, clock: Clock = utc_now) -> None:
        self._repo = TopicRepository(session)
        self._clock = clock

    def process(
        self, *, data_mode: DataMode | str, source: Source | None = None, limit: int = 500
    ) -> NormalizationReport:
        mode = require_data_mode(data_mode)
        report = NormalizationReport(data_mode=mode)
        for observation in self._repo.observations_without_link(
            data_mode=mode, source=source, limit=limit
        ):
            self._link(observation, mode, report)
        return report

    def _link(self, observation: RawObservation, mode: DataMode, report: NormalizationReport) -> TopicLink:
        now = self._clock()
        candidate = candidate_for(observation)
        key = normalize_text(candidate.text) if candidate.text else None
        decision, created = self._decide(observation, mode, candidate.text, key, candidate, now)
        link = self._repo.add_link(
            observation,
            data_mode=mode,
            status=decision.status,
            rule=decision.rule,
            certainty=decision.certainty,
            origin=NORMALIZER_ORIGIN,
            now=now,
            topic_id=decision.topic_id,
            candidate_text=candidate.text,
            normalized_candidate=key,
            reason=decision.reason,
        )
        report.processed += 1
        report.topics_created += int(created)
        report.by_status[decision.status.value] += 1
        report.by_rule[decision.rule.value] += 1
        return link

    def _decide(self, observation, mode, text, key, candidate, now) -> tuple[_Decision, bool]:
        if candidate.limitation or not key or not is_usable_key(key):
            return _Decision(
                LinkStatus.UNLINKED,
                LinkRule.INSUFFICIENT_DATA,
                Certainty.NONE,
                reason=candidate.limitation or "clave normalizada demasiado corta",
            ), False

        precedent = self._repo.manual_precedent(
            observation.source, observation.subject_ref, data_mode=mode
        )
        if precedent is not None:
            return _Decision(
                precedent.status,
                LinkRule.MANUAL_PRECEDENT,
                Certainty.MANUAL,
                topic_id=precedent.topic_id,
                reason=f"Repite la corrección manual del vínculo {precedent.id}",
            ), False

        alias = self._repo.find_alias(key, data_mode=mode)
        if alias is not None:
            topic = self._repo.get_topic(alias.topic_id, data_mode=mode)
            assert topic is not None
            if topic.ambiguous:
                return _Decision(
                    LinkStatus.NEEDS_REVIEW,
                    LinkRule.AMBIGUOUS_TOPIC,
                    Certainty.NONE,
                    topic_id=topic.id,
                    reason=f"El tema está marcado como ambiguo: {topic.ambiguous_reason}",
                ), False
            canonical = alias.kind is AliasKind.CANONICAL
            return _Decision(
                LinkStatus.LINKED,
                LinkRule.EXACT_NORMALIZED if canonical else LinkRule.ALIAS,
                Certainty.EXACT if canonical else Certainty.ALIAS,
                topic_id=topic.id,
                reason=None if canonical else f"Alias {alias.kind.value} registrado por {alias.origin}",
            ), False

        if candidate.disambiguation_base:
            base_key = normalize_text(candidate.disambiguation_base)
            base_alias = self._repo.find_alias(base_key, data_mode=mode) if is_usable_key(base_key) else None
            if base_alias is not None:
                return _Decision(
                    LinkStatus.NEEDS_REVIEW,
                    LinkRule.DISAMBIGUATION_BASE,
                    Certainty.NONE,
                    topic_id=base_alias.topic_id,
                    reason=f"El título calificado coincide con la base {candidate.disambiguation_base!r}",
                ), False

        topic, created = self._repo.create_topic(
            text, data_mode=mode, created_by=NORMALIZER_ORIGIN, now=now
        )
        return _Decision(LinkStatus.LINKED, LinkRule.NEW_TOPIC, Certainty.EXACT, topic_id=topic.id), created


CorrectionAction = Literal["link", "reject", "unlink"]


def correct_link(
    session: Session,
    link_id: int,
    *,
    data_mode: DataMode | str,
    action: CorrectionAction,
    actor: str,
    reason: str,
    topic_id: str | None = None,
    now: datetime,
) -> TopicLink:
    """Corrige un vínculo vigente creando uno nuevo; el anterior queda como reemplazado.

    Nunca modifica la observación original ni borra el vínculo anterior.
    """
    mode = require_data_mode(data_mode)
    check_actor(actor)
    if not reason or not reason.strip():
        raise ValueError("Toda corrección requiere un motivo")
    repo = TopicRepository(session)
    current = repo.get_link(link_id, data_mode=mode)
    if current is None:
        raise LookupError(f"No existe el vínculo {link_id}")
    if current.superseded_at is not None:
        raise ValueError("Solo se puede corregir el vínculo vigente")

    if action == "link":
        if topic_id is None or repo.get_topic(topic_id, data_mode=mode) is None:
            raise TopicNotFoundError(topic_id or "")
        status, target = LinkStatus.LINKED, topic_id
    elif action == "reject":
        if topic_id is not None:
            raise ValueError("Rechazar no admite un tema")
        status, target = LinkStatus.REJECTED, None
    elif action == "unlink":
        if topic_id is not None:
            raise ValueError("Desvincular no admite un tema")
        status, target = LinkStatus.UNLINKED, None
    else:
        raise ValueError(f"Acción desconocida: {action!r}")

    observation = session.get(RawObservation, current.observation_id)
    assert observation is not None  # garantizado por la clave foránea
    # Primero deja de ser vigente el actual y luego se inserta el nuevo, que apunta a él.
    # Ambos pasos ocurren en la transacción del llamador: o se aplican los dos o ninguno.
    repo.mark_superseded(current.id, data_mode=mode, now=now)
    return repo.add_link(
        observation,
        data_mode=mode,
        status=status,
        rule=LinkRule.MANUAL_CORRECTION,
        certainty=Certainty.MANUAL,
        origin=f"manual:{actor}",
        now=now,
        topic_id=target,
        candidate_text=current.candidate_text,
        normalized_candidate=current.normalized_candidate,
        reason=reason.strip(),
        supersedes_id=current.id,
    )
