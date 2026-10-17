"""Vinculación de observaciones de las tres fuentes con temas (reglas topics-v1)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.detectar.storage.models import (
    AliasKind,
    Certainty,
    DataMode,
    LinkRule,
    LinkStatus,
    RawObservation,
    Source,
    Topic,
    TopicLink,
)
from app.modules.detectar.storage.repository import InvalidDataModeError
from app.modules.detectar.storage.topics import (
    AliasConflictError,
    TopicNotFoundError,
    TopicRepository,
    topic_id_for,
)
from app.modules.detectar.topics.candidates import candidate_for
from app.modules.detectar.topics.linker import TopicLinker, correct_link

from . import helpers

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _process(session: Session, mode: DataMode = DataMode.REAL, **kwargs):
    report = TopicLinker(session, clock=lambda: NOW).process(data_mode=mode, **kwargs)
    session.flush()
    return report


def _link(session: Session, observation: RawObservation) -> TopicLink:
    link = TopicRepository(session).current_link(observation.id, data_mode=observation.data_mode)
    assert link is not None
    return link


# --- Candidatos por fuente -------------------------------------------------------------


def test_candidates_use_only_the_thematic_field(session: Session) -> None:
    gtr = helpers.trends(session, "Copa América 2026")
    wiki = helpers.wiki(session, "Copa_América_2026")
    news = helpers.gdelt(session, "copa america 2026")

    assert candidate_for(gtr).text == "Copa América 2026"
    assert candidate_for(wiki).text == "Copa América 2026"  # sin "es.wikipedia.org:"
    # GDELT: el término, no la consulta con filtros.
    assert candidate_for(news).text == "copa america 2026"
    assert "sourcelang" not in candidate_for(news).text


def test_gdelt_without_stored_term_is_a_limitation_not_a_topic(session: Session) -> None:
    obs = helpers.gdelt(session, None, query="Mundial sourcelang:spanish", excerpt={"query": "x"})

    report = _process(session)

    link = _link(session, obs)
    assert (link.status, link.rule, link.certainty) == (
        LinkStatus.UNLINKED,
        LinkRule.INSUFFICIENT_DATA,
        Certainty.NONE,
    )
    assert link.reason == "gdelt_term_missing"
    assert link.topic_id is None
    assert report.topics_created == 0
    assert session.scalar(select(Topic)) is None


def test_too_short_key_is_insufficient(session: Session) -> None:
    obs = helpers.trends(session, "¡X!")

    _process(session)

    assert _link(session, obs).rule is LinkRule.INSUFFICIENT_DATA


# --- Coincidencias entre fuentes ------------------------------------------------------------


def test_clear_normalized_match_across_the_three_sources(session: Session) -> None:
    gtr = helpers.trends(session, "México")
    wiki = helpers.wiki(session, "México")
    news = helpers.gdelt(session, "mexico")

    report = _process(session)

    links = [_link(session, o) for o in (gtr, wiki, news)]
    assert len({link.topic_id for link in links}) == 1
    assert [link.rule for link in links] == [
        LinkRule.NEW_TOPIC,
        LinkRule.EXACT_NORMALIZED,
        LinkRule.EXACT_NORMALIZED,
    ]
    assert all(link.status is LinkStatus.LINKED and link.certainty is Certainty.EXACT for link in links)
    assert report.topics_created == 1
    topic = TopicRepository(session).get_topic(links[0].topic_id, data_mode=DataMode.REAL)
    assert (topic.canonical_name, topic.normalized_key) == ("México", "mexico")
    assert topic.id == topic_id_for(DataMode.REAL, "mexico")  # identidad estable


def test_shared_words_never_merge_topics(session: Session) -> None:
    obs = [
        helpers.trends(session, "Apple"),
        helpers.trends(session, "Apple Music"),
        helpers.wiki(session, "Apple_Inc."),
        helpers.gdelt(session, "manzana apple"),
    ]

    report = _process(session)

    assert report.topics_created == 4
    assert len({_link(session, o).topic_id for o in obs}) == 4


def test_acronym_is_not_merged_without_a_registered_alias(session: Session) -> None:
    full = helpers.wiki(session, "Inteligencia_artificial")
    short = helpers.trends(session, "IA")

    _process(session)

    assert _link(session, full).topic_id != _link(session, short).topic_id


def test_registered_alias_links_later_observations(session: Session) -> None:
    full = helpers.wiki(session, "Inteligencia_artificial")
    _process(session)
    topic_id = _link(session, full).topic_id
    TopicRepository(session).add_alias(
        topic_id, "IA", data_mode=DataMode.REAL, kind=AliasKind.ACRONYM, origin="manual:ana", now=NOW
    )

    short = helpers.trends(session, "IA")
    _process(session)

    link = _link(session, short)
    assert (link.status, link.rule, link.certainty, link.topic_id) == (
        LinkStatus.LINKED,
        LinkRule.ALIAS,
        Certainty.ALIAS,
        topic_id,
    )
    assert "manual:ana" in link.reason


# --- Ambigüedad y revisión ----------------------------------------------------------------


def test_ambiguous_topic_sends_new_matches_to_review(session: Session) -> None:
    first = helpers.trends(session, "Jaguar")
    _process(session)
    topic_id = _link(session, first).topic_id
    TopicRepository(session).set_ambiguous(
        topic_id, data_mode=DataMode.REAL, ambiguous=True, actor="ana",
        reason="Animal, marca de autos o equipo", now=NOW,
    )

    second = helpers.gdelt(session, "jaguar")
    _process(session)

    link = _link(session, second)
    assert (link.status, link.rule, link.certainty) == (
        LinkStatus.NEEDS_REVIEW,
        LinkRule.AMBIGUOUS_TOPIC,
        Certainty.NONE,
    )
    assert link.topic_id == topic_id  # tema propuesto, no vinculado
    assert "Animal" in link.reason


def test_wikipedia_disambiguation_goes_to_review(session: Session) -> None:
    helpers.trends(session, "Mercurio")
    _process(session)
    planet = helpers.wiki(session, "Mercurio_(planeta)")

    report = _process(session)

    link = _link(session, planet)
    assert (link.status, link.rule) == (LinkStatus.NEEDS_REVIEW, LinkRule.DISAMBIGUATION_BASE)
    assert link.topic_id == topic_id_for(DataMode.REAL, "mercurio")
    assert report.topics_created == 0  # una persona decide


def test_disambiguated_title_without_base_topic_is_its_own_topic(session: Session) -> None:
    planet = helpers.wiki(session, "Mercurio_(planeta)")

    _process(session)

    assert _link(session, planet).rule is LinkRule.NEW_TOPIC


# --- Idempotencia y procedencia -------------------------------------------------------------


def test_reprocessing_creates_no_duplicates(session: Session) -> None:
    helpers.trends(session, "México")
    helpers.wiki(session, "México")
    _process(session)
    counts = [session.scalar(text(f"SELECT count(*) FROM {t}")) for t in ("topics", "topic_aliases", "topic_links")]

    again = _process(session)

    assert again.processed == 0
    assert [session.scalar(text(f"SELECT count(*) FROM {t}")) for t in ("topics", "topic_aliases", "topic_links")] == counts


def test_new_data_keeps_topic_identity(session: Session) -> None:
    first = helpers.trends(session, "Copa América")
    _process(session)
    topic_id = _link(session, first).topic_id

    later = helpers.wiki(session, "Copa_América")
    report = _process(session)

    assert report.processed == 1 and report.topics_created == 0
    assert _link(session, later).topic_id == topic_id


def test_link_keeps_provenance_and_original_observation_is_untouched(session: Session) -> None:
    obs = helpers.wiki(session, "Copa_América_2026", views=321)
    before = (obs.subject_ref, obs.value, obs.country, obs.language, dict(obs.raw_excerpt))

    _process(session)
    session.expire_all()

    stored = session.get(RawObservation, obs.id)
    assert (stored.subject_ref, stored.value, stored.country, stored.language, stored.raw_excerpt) == before
    link = _link(session, stored)
    assert link.observation_id == obs.id
    assert link.source is Source.WIKIMEDIA
    assert link.subject_ref == "es.wikipedia.org:Copa_América_2026"
    assert link.candidate_text == "Copa América 2026"
    assert link.normalized_candidate == "copa america 2026"
    assert link.origin == "normalizer:topics-v1"
    assert link.created_at == NOW


def test_processing_can_be_limited_to_one_source(session: Session) -> None:
    helpers.trends(session, "México")
    wiki = helpers.wiki(session, "México")

    report = _process(session, source=Source.GOOGLE_TRENDS_RSS)

    assert report.processed == 1
    assert TopicRepository(session).current_link(wiki.id, data_mode=DataMode.REAL) is None


# --- Separación real / simulado ------------------------------------------------------------


def test_real_and_simulated_never_share_topics_or_links(session: Session) -> None:
    real = helpers.trends(session, "México", mode=DataMode.REAL)
    simulated = helpers.trends(session, "México", mode=DataMode.SIMULATED)

    real_report = _process(session, DataMode.REAL)
    sim_report = _process(session, DataMode.SIMULATED)

    real_link, sim_link = _link(session, real), _link(session, simulated)
    assert real_link.topic_id != sim_link.topic_id
    assert real_report.processed == sim_report.processed == 1
    repo = TopicRepository(session)
    assert repo.get_topic(sim_link.topic_id, data_mode=DataMode.REAL) is None
    assert [t.id for t in repo.list_topics(data_mode=DataMode.REAL)] == [real_link.topic_id]
    assert repo.list_links(data_mode=DataMode.SIMULATED)[0].observation_id == simulated.id


def test_database_rejects_cross_mode_links(session: Session) -> None:
    real = helpers.trends(session, "México")
    simulated = helpers.trends(session, "Otro", mode=DataMode.SIMULATED)
    _process(session, DataMode.SIMULATED)
    sim_topic = _link(session, simulated).topic_id

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO topic_links (observation_id, data_mode, source, subject_ref, topic_id, "
                "status, rule, certainty, origin, created_at) VALUES (:obs, 'real', "
                "'google_trends_rss', 'x', :topic, 'linked', 'exact_normalized', 'exact', 'x', "
                "'2026-10-17 00:00:00')"
            ),
            {"obs": real.id, "topic": sim_topic},
        )


@pytest.mark.parametrize("bad", [None, "", "both"])
def test_processing_requires_an_explicit_valid_mode(session: Session, bad) -> None:
    with pytest.raises(InvalidDataModeError):
        TopicLinker(session).process(data_mode=bad)
    with pytest.raises(TypeError):
        TopicLinker(session).process()  # type: ignore[call-arg]


# --- Correcciones y trazabilidad -------------------------------------------------------------


def test_correction_creates_new_link_and_keeps_history(session: Session) -> None:
    planet = helpers.wiki(session, "Mercurio_(planeta)")
    element = helpers.wiki(session, "Mercurio_(elemento)")
    _process(session)
    wrong = _link(session, planet)
    target = _link(session, element).topic_id

    corrected = correct_link(
        session, wrong.id, data_mode=DataMode.REAL, action="link", topic_id=target,
        actor="ana", reason="Prueba de corrección", now=NOW,
    )
    session.flush()

    assert corrected.status is LinkStatus.LINKED and corrected.topic_id == target
    assert (corrected.rule, corrected.certainty, corrected.origin) == (
        LinkRule.MANUAL_CORRECTION, Certainty.MANUAL, "manual:ana",
    )
    assert corrected.supersedes_id == wrong.id
    history = TopicRepository(session).link_history(planet.id, data_mode=DataMode.REAL)
    assert [h.id for h in history] == [wrong.id, corrected.id]
    assert history[0].superseded_at == NOW and history[0].topic_id != target  # se conserva
    assert _link(session, planet).id == corrected.id


def test_reject_and_unlink_corrections(session: Session) -> None:
    obs = helpers.trends(session, "Ruido")
    _process(session)

    rejected = correct_link(
        session, _link(session, obs).id, data_mode="real", action="reject",
        actor="ana", reason="No es un tema", now=NOW,
    )
    unlinked = correct_link(
        session, rejected.id, data_mode="real", action="unlink",
        actor="beto", reason="Revisar de nuevo", now=NOW,
    )

    assert rejected.status is LinkStatus.REJECTED and rejected.topic_id is None
    assert unlinked.status is LinkStatus.UNLINKED and unlinked.supersedes_id == rejected.id
    assert len(TopicRepository(session).link_history(obs.id, data_mode="real")) == 3


def test_manual_correction_is_repeated_for_new_observations_of_same_subject(session: Session) -> None:
    first = helpers.trends(session, "Jaguar")
    other = helpers.trends(session, "Jaguar animal")
    _process(session)
    correct_link(
        session, _link(session, first).id, data_mode="real", action="link",
        topic_id=_link(session, other).topic_id, actor="ana", reason="Se refería al animal", now=NOW,
    )

    again = helpers.trends(session, "Jaguar")  # nueva captura del mismo sujeto
    _process(session)

    link = _link(session, again)
    assert (link.rule, link.certainty) == (LinkRule.MANUAL_PRECEDENT, Certainty.MANUAL)
    assert link.topic_id == _link(session, other).topic_id


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"action": "link", "topic_id": "tpc_0000000000000000"}, TopicNotFoundError),
        ({"action": "link"}, TopicNotFoundError),
        ({"action": "reject", "topic_id": "tpc_0000000000000000"}, ValueError),
        ({"action": "borrar"}, ValueError),
        ({"action": "reject", "reason": "  "}, ValueError),
        ({"action": "reject", "actor": "a b"}, ValueError),
    ],
)
def test_invalid_corrections_are_rejected(session: Session, kwargs, error) -> None:
    obs = helpers.trends(session, "Algo")
    _process(session)
    options = {"actor": "ana", "reason": "motivo"} | kwargs

    with pytest.raises(error):
        correct_link(session, _link(session, obs).id, data_mode="real", now=NOW, **options)
    assert _link(session, obs).rule is LinkRule.NEW_TOPIC  # nada cambió


def test_superseded_link_cannot_be_corrected_again(session: Session) -> None:
    obs = helpers.trends(session, "Algo")
    _process(session)
    old = _link(session, obs)
    correct_link(session, old.id, data_mode="real", action="reject", actor="ana", reason="x y z", now=NOW)

    with pytest.raises(ValueError, match="vigente"):
        correct_link(session, old.id, data_mode="real", action="unlink", actor="ana", reason="x y z", now=NOW)


def test_links_are_append_only_in_the_database(session: Session) -> None:
    obs = helpers.trends(session, "Algo")
    _process(session)
    link = _link(session, obs)

    with pytest.raises(IntegrityError, match="reemplazado"):
        session.execute(text("UPDATE topic_links SET topic_id = NULL, status = 'unlinked' WHERE id = :i"), {"i": link.id})
    with pytest.raises(IntegrityError, match="no se borran"):
        session.execute(text("DELETE FROM topic_links WHERE id = :i"), {"i": link.id})


def test_only_one_current_link_per_observation(session: Session) -> None:
    obs = helpers.trends(session, "Algo")
    _process(session)
    link = _link(session, obs)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO topic_links (observation_id, data_mode, source, subject_ref, topic_id, "
                "status, rule, certainty, origin, created_at) VALUES (:obs, 'real', "
                "'google_trends_rss', 'Algo', :topic, 'linked', 'exact_normalized', 'exact', 'x', "
                "'2026-10-17 00:00:00')"
            ),
            {"obs": obs.id, "topic": link.topic_id},
        )


# --- Alias y temas ------------------------------------------------------------------------


def test_alias_registration_is_idempotent_and_conflicts_are_detected(session: Session) -> None:
    helpers.trends(session, "Inteligencia artificial")
    helpers.trends(session, "Ingeniería aeroespacial")
    _process(session)
    repo = TopicRepository(session)
    ai, aero = (t.id for t in repo.list_topics(data_mode="real"))

    _, created = repo.add_alias(aero, "IA", data_mode="real", kind=AliasKind.ACRONYM, origin="manual:a", now=NOW)
    _, again = repo.add_alias(aero, "ia", data_mode="real", kind=AliasKind.ACRONYM, origin="manual:a", now=NOW)

    assert created is True and again is False
    with pytest.raises(AliasConflictError):
        repo.add_alias(ai, "I.A.", data_mode="real", kind=AliasKind.ACRONYM, origin="manual:a", now=NOW)
    with pytest.raises(ValueError):
        repo.add_alias(ai, "x", data_mode="real", kind=AliasKind.ACRONYM, origin="manual:a", now=NOW)
    with pytest.raises(ValueError):
        repo.add_alias(ai, "otra", data_mode="real", kind=AliasKind.CANONICAL, origin="manual:a", now=NOW)


def test_create_topic_is_idempotent(session: Session) -> None:
    repo = TopicRepository(session)

    first, created = repo.create_topic("México", data_mode="real", created_by="x", now=NOW)
    second, again = repo.create_topic("MEXICO", data_mode="real", created_by="x", now=NOW)

    assert created is True and again is False and first.id == second.id


def test_ambiguity_requires_reason_and_is_traceable(session: Session) -> None:
    topic, _ = TopicRepository(session).create_topic("Jaguar", data_mode="real", created_by="x", now=NOW)
    repo = TopicRepository(session)

    with pytest.raises(ValueError):
        repo.set_ambiguous(topic.id, data_mode="real", ambiguous=True, actor="ana", reason="", now=NOW)
    marked = repo.set_ambiguous(topic.id, data_mode="real", ambiguous=True, actor="ana", reason="varios sentidos", now=NOW)

    assert (marked.ambiguous, marked.ambiguous_marked_by, marked.ambiguous_marked_at) == (True, "ana", NOW)
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE topics SET ambiguous_reason = NULL WHERE id = :i"), {"i": topic.id})


def test_every_public_topic_repository_method_requires_data_mode() -> None:
    import inspect

    methods = {
        name: member
        for name, member in inspect.getmembers(TopicRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods
    for name, method in methods.items():
        parameter = inspect.signature(method).parameters.get("data_mode")
        assert parameter is not None, name
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name
