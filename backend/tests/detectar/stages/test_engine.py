"""Motor puro stages-v1: cada regla, combinaciones y límites (sin base de datos)."""

from itertools import count

import pytest

from app.modules.detectar.stages.engine import MetricSnapshot, MixedInputError, classify
from app.modules.detectar.storage.models import (
    DataMode,
    EvidenceRole,
    MetricStatus,
    Source,
    TrendStage,
)

_ids = count(1)
WIKI = "es.wikipedia.org:Tema"
NEWS = "tema sourcelang:spanish"


def snap(
    key: str,
    value: float | None,
    *,
    source: Source = Source.WIKIMEDIA,
    scope: str = WIKI,
    details: dict | None = None,
    reason: str | None = None,
    mode: DataMode = DataMode.REAL,
    version: str = "metrics-v1",
    window: int = 7,
    validated: bool | None = None,
) -> MetricSnapshot:
    status = MetricStatus.OK if value is not None else MetricStatus.INSUFFICIENT
    return MetricSnapshot(
        id=next(_ids),
        data_mode=mode,
        metric_key=key,
        source=source,
        scope=scope,
        unit="growth_rate",
        value=value,
        status=status,
        reason=reason if value is None else None,
        window_days=window,
        rules_version=version,
        source_validated=(source is not Source.GDELT) if validated is None else validated,
        details=details or {},
    )


def wiki(g: float | None, a: float | None = None, earlier: float | None = None, scope: str = WIKI, **kw):
    accel_details = {"recent_growth": g, "earlier_growth": earlier} if a is not None else {}
    return [
        snap("wiki_views_growth", g, scope=scope, reason="missing_days:1", **kw),
        snap("wiki_views_acceleration", a, scope=scope, details=accel_details, reason="earlier_previous_missing_days:7", **kw),
    ]


def news(g: float | None, a: float | None = None, earlier: float | None = None):
    details = {"recent_growth": g, "earlier_growth": earlier} if a is not None else {}
    return [
        snap("gdelt_articles_growth", g, source=Source.GDELT, scope=NEWS, reason="missing_days:2"),
        snap("gdelt_articles_acceleration", a, source=Source.GDELT, scope=NEWS, details=details, reason="x"),
    ]


def gtr(change: float | None, previous: float = 0.2, current: float | None = None, country: str = "MX"):
    current = previous + change if current is None and change is not None else current
    return [
        snap(
            "gtr_presence_share_change", change, source=Source.GOOGLE_TRENDS_RSS, scope=country,
            details={"previous": previous, "current": current}, reason="current_known_captures_below_minimum:3",
        )
    ]


def run(snapshots):
    return classify(snapshots, data_mode=DataMode.REAL)


def evidence(result, source: Source):
    return next(e for e in result.evidence if e.source is source)


# --- Reglas de Wikimedia (W*) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("g", "a", "earlier", "stage", "rule"),
    [
        (0.5, 0.2, 0.3, TrendStage.ACELERANDO, "W1"),
        (0.5, None, None, TrendStage.EMERGENTE, "W2"),
        (0.5, 0.05, 0.45, TrendStage.EMERGENTE, "W3"),
        (0.05, -0.4, 0.45, TrendStage.PUNTO_MAXIMO, "W5"),
    ],
)
def test_wikimedia_stage_rules(g, a, earlier, stage, rule) -> None:
    result = run(wiki(g, a, earlier))

    assert result.stage is stage
    item = evidence(result, Source.WIKIMEDIA)
    assert item.role is EvidenceRole.PRIMARY
    assert item.scopes[0].rule == rule


@pytest.mark.parametrize(
    ("g", "a", "earlier", "rule"),
    [
        (None, None, None, "W0"),  # crecimiento insuficiente (p. ej. días faltantes)
        (0.5, -0.3, 0.8, "W4"),  # crece pero desacelera
        (0.02, None, None, "W6"),  # estable sin historia: no se infiere un máximo
        (0.02, 0.0, 0.05, "W6"),  # estable sin subida previa
        (-0.4, -0.5, 0.1, "W7"),  # descenso: no es una etapa de v1
        (0.15, 0.0, 0.15, "W8"),  # crecimiento moderado
    ],
)
def test_wikimedia_signals_that_do_not_imply_a_stage(g, a, earlier, rule) -> None:
    result = run(wiki(g, a, earlier))

    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert result.reason == "sin_evidencia_temporal_suficiente"
    assert evidence(result, Source.WIKIMEDIA).scopes[0].rule == rule


def test_insufficient_metrics_are_never_read_as_numbers() -> None:
    result = run(wiki(None, None))

    scope = evidence(result, Source.WIKIMEDIA).scopes[0]
    assert scope.stage is None and "missing_days:1" in scope.explanation


def test_maximum_needs_temporal_evidence_of_a_previous_rise() -> None:
    no_history = run(wiki(0.0, None))
    with_rise = run(wiki(0.0, -0.6, 0.6))

    assert no_history.stage is TrendStage.DATOS_INSUFICIENTES
    assert with_rise.stage is TrendStage.PUNTO_MAXIMO


# --- Google Trends (G*) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "previous", "stage", "rule"),
    [
        (0.5, 0.0, TrendStage.EMERGENTE, "G1"),  # aparece
        (0.4, 0.2, TrendStage.EMERGENTE, "G2"),  # aumenta presencia
        (0.1, 0.2, None, "G3"),
        (None, 0.0, None, "G0"),  # menos de 3 capturas por ventana
    ],
)
def test_google_trends_only_signals_emergence(change, previous, stage, rule) -> None:
    result = run(gtr(change, previous))

    item = evidence(result, Source.GOOGLE_TRENDS_RSS)
    assert item.scopes[0].rule == rule
    assert item.proposed_stage is stage
    assert result.stage in (TrendStage.EMERGENTE, TrendStage.DATOS_INSUFICIENTES)


def test_google_trends_never_infers_growth_acceleration_or_maximum() -> None:
    for change, previous in [(1.0, 0.0), (0.9, 0.1), (0.0, 1.0), (-0.9, 1.0)]:
        assert run(gtr(change, previous)).stage in (TrendStage.EMERGENTE, TrendStage.DATOS_INSUFICIENTES)


# --- Combinación y contradicciones -------------------------------------------------------


def test_emergence_and_acceleration_are_compatible() -> None:
    result = run(gtr(0.5, 0.0) + wiki(0.5, 0.3, 0.2))

    assert result.stage is TrendStage.ACELERANDO
    assert any("Compatibles" in note for note in result.notes)


def test_contradictory_primary_sources_are_insufficient() -> None:
    result = run(gtr(0.5, 0.0) + wiki(0.0, -0.6, 0.6))  # emergente vs punto_maximo

    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert result.reason == "senales_contradictorias"


def test_contradictory_scopes_within_a_source_exclude_it() -> None:
    result = run(wiki(0.5, 0.3, 0.2, scope="es.wikipedia.org:A") + wiki(0.0, -0.6, 0.6, scope="es.wikipedia.org:B"))

    item = evidence(result, Source.WIKIMEDIA)
    assert item.role is EvidenceRole.EXCLUDED and "contradictorios" in item.reason
    assert result.stage is TrendStage.DATOS_INSUFICIENTES


def test_scopes_without_signal_do_not_contradict() -> None:
    result = run(wiki(0.5, 0.3, 0.2, scope="es.wikipedia.org:A") + wiki(None, scope="es.wikipedia.org:B"))

    assert result.stage is TrendStage.ACELERANDO


# --- GDELT no validada ---------------------------------------------------------------------


def test_gdelt_alone_never_determines_a_stage() -> None:
    result = run(news(0.9, 0.5, 0.2))

    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert result.reason == "solo_fuente_no_validada"
    item = evidence(result, Source.GDELT)
    assert item.role is EvidenceRole.COMPLEMENTARY and item.source_validated is False
    assert item.proposed_stage is TrendStage.ACELERANDO


def test_gdelt_disagreement_is_only_a_note() -> None:
    result = run(wiki(0.5, None) + news(0.9, 0.5, 0.2))

    assert result.stage is TrendStage.EMERGENTE  # decide Wikimedia
    assert any("gdelt (no validada)" in note and "no coincide" in note for note in result.notes)


# --- Popularidad no es saturación -------------------------------------------------------------


def test_high_popularity_is_not_saturation() -> None:
    levels = [
        snap("wiki_views_total", 5_000_000.0),
        snap("wiki_views_daily_mean", 714_285.0),
        snap("gtr_max_traffic_lower_bound", 2_000_000.0, source=Source.GOOGLE_TRENDS_RSS, scope="MX"),
        snap("gtr_presence_share", 1.0, source=Source.GOOGLE_TRENDS_RSS, scope="MX"),
    ]

    result = run(levels + wiki(0.01, -0.05, 0.02))

    assert result.stage is not TrendStage.SATURADA
    assert result.stage is TrendStage.DATOS_INSUFICIENTES


def test_saturated_is_never_assigned_in_v1() -> None:
    cases = [wiki(g, a, e) for g in (-0.9, 0.0, 0.9) for a in (None, -0.9, 0.9) for e in (0.0, 0.9)]
    for case in cases:
        assert run(case + news(-0.9, -0.9, 0.9)).stage is not TrendStage.SATURADA


def test_level_metrics_alone_are_not_stage_evidence() -> None:
    result = run([snap("wiki_views_total", 1000.0), snap("gdelt_articles_total", 50.0, source=Source.GDELT, scope=NEWS)])

    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert evidence(result, Source.WIKIMEDIA).role is EvidenceRole.EXCLUDED


# --- Entradas incompatibles --------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"mode": DataMode.SIMULATED}, {"version": "metrics-v2"}, {"window": 14}],
)
def test_mixed_modes_versions_or_windows_are_rejected(kwargs) -> None:
    with pytest.raises(MixedInputError):
        run(wiki(0.5, 0.3, 0.2) + [snap("wiki_views_growth", 0.5, scope="es.wikipedia.org:Otro", **kwargs)])


def test_no_metrics_is_insufficient() -> None:
    result = run([])

    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert all(e.role is EvidenceRole.EXCLUDED for e in result.evidence)


def test_excluded_source_without_metrics_reports_its_real_validation_status() -> None:
    """Cierre de DETECTAR: sin métricas, la evidencia excluida no degrada una fuente validada."""
    result = classify([], data_mode=DataMode.REAL)
    by_source = {e.source: e for e in result.evidence}
    assert all(e.role is EvidenceRole.EXCLUDED for e in result.evidence)
    assert by_source[Source.WIKIMEDIA].source_validated is True
    assert by_source[Source.GOOGLE_TRENDS_RSS].source_validated is True
    assert by_source[Source.GDELT].source_validated is False
    assert result.stage is TrendStage.DATOS_INSUFICIENTES
    assert result.reason == "sin_evidencia_temporal_suficiente"
