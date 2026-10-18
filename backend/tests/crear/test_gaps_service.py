"""Brechas sobre lo que DETECTAR realmente persiste: observaciones -> E7 -> E8 -> E9 -> CREAR."""

from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.gaps.rules import SourceResult, Verdict
from app.modules.crear.gaps.service import GapService
from app.modules.detectar.storage.models import DataMode, Source

from .builders import AS_OF, seed_gaps, topic_id


def analyze(sessions: sessionmaker[Session], mode: DataMode = DataMode.REAL, **kwargs):
    with sessions() as session:
        return GapService(DetectarReader(session)).analyze(data_mode=mode, **kwargs)


def test_one_topic_per_verdict_in_priority_order(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions)

    report = analyze(detectar_sessions)

    assert report.as_of == AS_OF  # por defecto, la última fecha con métricas
    assert [(a.topic_name, a.verdict) for a in report.analyses] == [
        ("Brecha", Verdict.BRECHA_CONFIRMADA),
        ("Solo ingles", Verdict.BRECHA_POR_CONFIRMAR),
        ("Mixta", Verdict.SENALES_MIXTAS),
        ("Pareja", Verdict.SIN_BRECHA),
        ("Solo espanol", Verdict.DATOS_INSUFICIENTES),
    ]


def test_figures_are_the_ones_detectar_computed(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions)

    gap = analyze(detectar_sessions).analyses[0]

    by_source = {c.source: c for c in gap.comparisons}
    wiki = by_source[Source.WIKIMEDIA]
    assert (wiki.english.value, wiki.spanish.value, wiki.ratio) == (7000.0, 280.0, 25.0)  # 7 días × 1000 y × 40
    assert by_source[Source.GOOGLE_TRENDS_RSS].result is SourceResult.SOLO_INGLES
    assert gap.summary == "Hay brecha: en Wikipedia se lee 25,0× más en inglés; es tendencia en EE. UU. y no en México."


def test_current_stage_comes_from_detectar(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions)

    report = analyze(detectar_sessions)

    stage = report.stages[topic_id("Solo ingles")]
    assert (stage.as_of, stage.rules_version, stage.calibrated) == (AS_OF, "stages-v1", False)


def test_filters_by_topic(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions)

    report = analyze(detectar_sessions, topic_ids=[topic_id("Mixta")])

    assert [a.topic_name for a in report.analyses] == ["Mixta"]


def test_without_metrics_there_is_no_reference_date(detectar_sessions: sessionmaker[Session]) -> None:
    report = analyze(detectar_sessions)

    assert (report.as_of, report.analyses) == (None, [])


def test_real_and_simulated_data_never_mix(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions, mode=DataMode.SIMULATED)

    assert analyze(detectar_sessions, DataMode.REAL).analyses == []
    simulated = analyze(detectar_sessions, DataMode.SIMULATED).analyses
    assert next(a.topic_id for a in simulated) == topic_id("Brecha", DataMode.SIMULATED)
