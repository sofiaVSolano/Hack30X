"""Motor brechas-v1 (funciones puras): resultados por fuente, veredicto y textos."""

import pytest

from app.modules.crear.detectar_reader import MetricInfo
from app.modules.crear.gaps.engine import SideState, analyze_topic, decide
from app.modules.crear.gaps.rules import SourceResult, Verdict
from app.modules.detectar.storage.models import Source

T = "tpc_0000000000000001"
W, G, R = Source.WIKIMEDIA, Source.GDELT, Source.GOOGLE_TRENDS_RSS


def metric(source: Source, scope: str, key: str, value: float | None, *, reason: str | None = None, details=None) -> MetricInfo:
    return MetricInfo(
        topic_id=T, source=source, scope=scope, key=key, unit="views", value=value, ok=value is not None,
        reason=None if value is not None else (reason or "missing_days:1"), validated=source is not G,
        details=details or {},
    )


def views(language: str, total: float | None, article: str = "Tema", growth: float | None = None) -> list[MetricInfo]:
    scope = f"{language}.wikipedia.org:{article}"
    items = [metric(W, scope, "wiki_views_total", total)]
    if growth is not None:
        items.append(metric(W, scope, "wiki_views_growth", growth))
    return items


def share(country: str, present: int, known: int) -> MetricInfo:
    return metric(R, country, "gtr_presence_share", present / known, details={"present": present, "known": known})


def run(metrics: list[MetricInfo], known: dict[str, int] | None = None):
    return analyze_topic(T, "Tema", metrics, known or {})


def only(analysis, source: Source):
    (comparison,) = [c for c in analysis.comparisons if c.source is source]
    return comparison


# --- Wikimedia --------------------------------------------------------------------------------


def test_much_more_attention_in_english_is_a_confirmed_gap() -> None:
    analysis = run(views("en", 7000, growth=0.4) + views("es", 280, growth=0.1))

    wiki = only(analysis, W)
    assert (wiki.result, wiki.ratio) == (SourceResult.BRECHA, 25.0)
    assert wiki.explanation == "7000 visitas en inglés frente a 280 en español en 7 días: 25,0× más en inglés."
    assert wiki.trend == "Crecimiento semanal según DETECTAR: +40 % en inglés y +10 % en español."
    assert analysis.verdict is Verdict.BRECHA_CONFIRMADA
    assert analysis.summary == "Hay brecha: en Wikipedia se lee 25,0× más en inglés."


@pytest.mark.parametrize(
    ("en", "es", "result", "verdict"),
    [
        (1400, 1260, SourceResult.PARIDAD, Verdict.SIN_BRECHA),
        (300, 1200, SourceResult.MAS_FUERTE_ESPANOL, Verdict.SIN_BRECHA),
        (2100, 0, SourceResult.SOLO_INGLES, Verdict.BRECHA_CONFIRMADA),
        (600, 50, SourceResult.INSUFICIENTE, Verdict.DATOS_INSUFICIENTES),  # volumen bajo en ambos
    ],
)
def test_wikipedia_results(en: float, es: float, result: SourceResult, verdict: Verdict) -> None:
    analysis = run(views("en", en) + views("es", es))

    assert only(analysis, W).result is result
    assert analysis.verdict is verdict


def test_unmeasured_spanish_side_is_a_gap_to_confirm() -> None:
    analysis = run(views("en", 6300, growth=0.5))

    wiki = only(analysis, W)
    assert wiki.result is SourceResult.SIN_MEDICION_ESPANOL
    assert wiki.spanish.state is SideState.SIN_MEDICION and wiki.ratio is None
    assert analysis.verdict is Verdict.BRECHA_POR_CONFIRMAR
    assert "Para confirmarla, DETECTAR debe medir también el lado en español." in analysis.summary


def test_only_spanish_measurements_cannot_be_compared() -> None:
    analysis = run(views("es", 1300))

    assert only(analysis, W).result is SourceResult.SIN_MEDICION_INGLES
    assert analysis.verdict is Verdict.DATOS_INSUFICIENTES
    assert "DETECTAR debe medir también en inglés" in analysis.summary


def test_incomplete_side_is_never_summed_or_treated_as_zero() -> None:
    analysis = run(views("en", 50000) + views("es", None))

    wiki = only(analysis, W)
    assert wiki.result is SourceResult.INSUFICIENTE
    assert wiki.spanish.state is SideState.INSUFICIENTE and wiki.spanish.value is None
    assert "faltan días" in wiki.explanation
    assert analysis.verdict is Verdict.DATOS_INSUFICIENTES


def test_several_articles_of_a_language_are_summed_but_growth_is_not_combined() -> None:
    metrics = views("en", 9000) + views("es", 200, growth=0.2) + views("es", 100, "Tema (película)", growth=0.9)

    wiki = only(run(metrics), W)
    assert wiki.spanish.value == 300 and len(wiki.spanish.scopes) == 2
    assert wiki.spanish.growth is None and wiki.trend is None
    assert wiki.ratio == 30.0


def test_other_wikipedia_editions_are_ignored_with_a_note() -> None:
    analysis = run(views("en", 7000) + views("es", 280) + views("pt", 5000))

    assert {s.scope for s in only(analysis, W).english.scopes} == {"en.wikipedia.org:Tema"}
    assert any("pt.wikipedia.org:Tema" in note for note in analysis.notes)


# --- GDELT (no validada) ----------------------------------------------------------------------


def test_gdelt_alone_can_only_suggest_a_gap() -> None:
    metrics = [
        metric(G, "Tema sourcelang:english", "gdelt_articles_total", 140),
        metric(G, "Tema sourcelang:spanish", "gdelt_articles_total", 14),
    ]
    analysis = run(metrics)

    gdelt = only(analysis, G)
    assert (gdelt.result, gdelt.validated) == (SourceResult.BRECHA, False)
    assert analysis.verdict is Verdict.BRECHA_POR_CONFIRMAR
    assert "(GDELT no está validada)" in analysis.summary
    assert any("GDELT no está validada" in note for note in analysis.notes)


def test_gdelt_prefers_the_unfiltered_query_over_country_filtered_ones() -> None:
    metrics = [
        metric(G, "Tema sourcelang:english", "gdelt_articles_total", 140),
        metric(G, "Tema sourcelang:spanish", "gdelt_articles_total", 20),
        metric(G, "Tema sourcelang:spanish sourcecountry:mexico", "gdelt_articles_total", 12),
    ]

    assert only(run(metrics), G).spanish.value == 20  # no 32: las consultas se solapan


# --- Google Trends ----------------------------------------------------------------------------


def test_absence_in_a_captured_country_is_a_measured_zero() -> None:
    analysis = run([share("US", 7, 7)], known={"US": 7, "MX": 7})

    trends = only(analysis, R)
    assert trends.result is SourceResult.SOLO_INGLES
    assert trends.explanation == "Aparece en 7 de 7 capturas de EE. UU. y en ninguna captura de México."
    assert analysis.verdict is Verdict.BRECHA_CONFIRMADA
    assert ".." not in analysis.summary


def test_a_country_without_enough_captures_is_not_measured() -> None:
    analysis = run([share("US", 7, 7)], known={"US": 7, "MX": 2})

    assert only(analysis, R).result is SourceResult.SIN_MEDICION_ESPANOL
    assert analysis.verdict is Verdict.BRECHA_POR_CONFIRMAR


def test_trending_in_both_does_not_contradict_a_wikipedia_gap() -> None:
    metrics = views("en", 25200) + views("es", 1295) + [share("US", 7, 7), share("MX", 4, 7)]
    analysis = run(metrics, known={"US": 7, "MX": 7})

    assert only(analysis, R).result is SourceResult.PARIDAD
    assert analysis.verdict is Verdict.BRECHA_CONFIRMADA
    assert analysis.summary.endswith("En Google Trends aparece tanto en EE. UU. como en México.")


def test_sources_pointing_in_opposite_directions_are_mixed_signals() -> None:
    metrics = views("en", 4900) + views("es", 980) + [share("MX", 6, 7)]
    analysis = run(metrics, known={"US": 7, "MX": 7})

    assert only(analysis, R).result is SourceResult.MAS_FUERTE_ESPANOL
    assert analysis.verdict is Verdict.SENALES_MIXTAS
    assert analysis.summary == (
        "Señales mixtas: en Wikipedia se lee 5,0× más en inglés, pero es tendencia en México y no en EE. UU."
    )


def test_countries_outside_both_lists_do_not_count() -> None:
    analysis = run([share("ES", 7, 7)], known={"ES": 7})

    assert analysis.comparisons == ()


# --- reglas del veredicto ----------------------------------------------------------------------


def test_metrics_of_another_topic_are_rejected() -> None:
    other = MetricInfo("tpc_ffffffffffffffff", W, "en.wikipedia.org:X", "wiki_views_total", "views", 1.0, True, None, True, {})
    with pytest.raises(ValueError, match="otro tema"):
        analyze_topic(T, "Tema", [other], {})


def test_decide_only_lets_validated_sources_confirm() -> None:
    gdelt_gap = only(run([
        metric(G, "Tema sourcelang:english", "gdelt_articles_total", 140),
        metric(G, "Tema sourcelang:spanish", "gdelt_articles_total", 14),
    ]), G)
    wiki_spanish = only(run(views("en", 300) + views("es", 1200)), W)

    assert decide([gdelt_gap]) is Verdict.BRECHA_POR_CONFIRMAR
    assert decide([gdelt_gap, wiki_spanish]) is Verdict.SIN_BRECHA
    assert decide([]) is Verdict.DATOS_INSUFICIENTES
