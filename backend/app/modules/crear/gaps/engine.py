"""Motor de ``brechas-v1``: funciones puras, sin base de datos.

Recibe las métricas de DETECTAR de un tema (una fecha de referencia) y las capturas conocidas
de Google Trends por país, y devuelve la comparación por fuente, el veredicto y textos que lo
explican con las mismas cifras de DETECTAR. Ver ``rules.py`` y ``docs/crear.md``.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.crear.detectar_reader import MetricInfo
from app.modules.crear.gaps.rules import (
    DIRECTION,
    ENGLISH_COUNTRIES,
    LATAM_COUNTRIES,
    SOURCE_METRICS,
    Language,
    SourceResult,
    Verdict,
    country_label,
    gdelt_country_filtered,
    gdelt_language,
    gtr_min_known_captures,
    min_volume,
    ratio_min,
    wiki_language,
)
from app.modules.crear.text import fmt_int, fmt_pct, fmt_ratio, join_es, sentence
from app.modules.detectar.storage.models import Source

COMPARED_SOURCES = (Source.WIKIMEDIA, Source.GOOGLE_TRENDS_RSS, Source.GDELT)

# Sustantivo y verbo de cada fuente con volumen, para los textos.
_VOLUME_WORDS = {
    Source.WIKIMEDIA: ("visitas", "se lee"),
    Source.GDELT: ("artículos de prensa", "se publica"),
}


class SideState(StrEnum):
    MEDIDO = "medido"
    INSUFICIENTE = "insuficiente"
    SIN_MEDICION = "sin_medicion"


@dataclass(frozen=True)
class ScopeMeasure:
    """Un ámbito de DETECTAR: artículo de Wikipedia, consulta de GDELT o país del RSS."""

    scope: str
    value: float | None
    growth: float | None = None
    reason: str | None = None  # motivo de DETECTAR cuando la métrica es insuficiente
    present: int | None = None  # Google Trends: capturas con el tema
    known: int | None = None  # Google Trends: capturas conocidas del país


@dataclass(frozen=True)
class Side:
    language: Language
    state: SideState
    value: float | None = None
    scopes: tuple[ScopeMeasure, ...] = ()

    @property
    def growth(self) -> float | None:
        """Crecimiento semanal de DETECTAR, solo con un único ámbito: las tasas no se suman."""
        if len(self.scopes) != 1:
            return None
        return self.scopes[0].growth

    @property
    def best(self) -> ScopeMeasure | None:
        measured = [s for s in self.scopes if s.value is not None]
        return max(measured, key=lambda s: (s.value, s.scope)) if measured else None


@dataclass(frozen=True)
class SourceComparison:
    source: Source
    validated: bool
    metric: str
    unit: str
    english: Side
    spanish: Side
    ratio: float | None
    result: SourceResult
    explanation: str  # frase completa con las cifras
    short: str  # fragmento para el resumen del tema
    trend: str | None = None

    @property
    def direction(self) -> str:
        return DIRECTION[self.result]


@dataclass(frozen=True)
class GapAnalysis:
    topic_id: str
    topic_name: str
    verdict: Verdict
    summary: str
    comparisons: tuple[SourceComparison, ...]
    notes: tuple[str, ...] = ()

    @property
    def headline_ratio(self) -> float | None:
        """Razón de la comparación validada más fuerte a favor del inglés (para ordenar)."""
        ratios = [c.ratio for c in self.comparisons if c.validated and c.direction == "ingles" and c.ratio]
        return max(ratios) if ratios else None

    @property
    def english_volume(self) -> float:
        values = [c.english.value for c in self.comparisons if c.source is Source.WIKIMEDIA and c.english.value]
        return max(values) if values else 0.0


# --- motivos de DETECTAR en palabras ---------------------------------------------------------


def _reason_text(reason: str | None) -> str:
    if not reason:
        return "métrica no disponible"
    if reason.startswith("missing_days"):
        return "faltan días en la ventana de 7 días"
    if reason.startswith("known_captures_below_minimum"):
        return "menos de 3 capturas del país en la ventana"
    return reason


def _side_reasons(*sides: Side) -> str:
    reasons = sorted({_reason_text(s.reason) for side in sides for s in side.scopes if s.value is None})
    return "; ".join(reasons) if reasons else "datos insuficientes"


# --- fuentes con volumen: Wikimedia y GDELT ---------------------------------------------------


def _volume_side(language: Language, items: list[tuple[str, dict[str, MetricInfo]]], source: Source) -> Side:
    if not items:
        return Side(language, SideState.SIN_MEDICION)
    total_key, growth_key = SOURCE_METRICS[source]
    scopes = []
    for scope, metrics in items:
        total, growth = metrics[total_key], metrics.get(growth_key)
        scopes.append(
            ScopeMeasure(
                scope,
                total.value if total.ok else None,
                growth=growth.value if growth is not None and growth.ok else None,
                reason=None if total.ok else total.reason,
            )
        )
    # Una suma con ámbitos incompletos subestimaría ese idioma: no se compara.
    if any(s.value is None for s in scopes):
        return Side(language, SideState.INSUFICIENTE, None, tuple(scopes))
    return Side(language, SideState.MEDIDO, sum(s.value or 0.0 for s in scopes), tuple(scopes))


def _volume_sides(source: Source, metrics: list[MetricInfo]) -> tuple[Side, Side, list[str]]:
    total_key = SOURCE_METRICS[source][0]
    by_scope: dict[str, dict[str, MetricInfo]] = defaultdict(dict)
    for metric in metrics:
        by_scope[metric.scope][metric.key] = metric
    groups: dict[Language, list[tuple[str, dict[str, MetricInfo]]]] = {Language.EN: [], Language.ES: []}
    ignored: list[str] = []
    for scope, by_key in sorted(by_scope.items()):
        if total_key not in by_key:
            continue
        language = wiki_language(scope) if source is Source.WIKIMEDIA else gdelt_language(scope)
        if language is None:
            ignored.append(scope)
            continue
        groups[language].append((scope, by_key))
    if source is Source.GDELT:
        # Una consulta sin filtro de país ya incluye las filtradas por país: no se suman ambas.
        for language, items in groups.items():
            unfiltered = [item for item in items if not gdelt_country_filtered(item[0])]
            if unfiltered:
                groups[language] = unfiltered
    notes = [f"No se compara (sin idioma inglés o español): {join_es(ignored)}."] if ignored else []
    return (
        _volume_side(Language.EN, groups[Language.EN], source),
        _volume_side(Language.ES, groups[Language.ES], source),
        notes,
    )


def _compare_volume(source: Source, english: Side, spanish: Side, validated: bool) -> SourceComparison | None:
    if english.state is SideState.SIN_MEDICION and spanish.state is SideState.SIN_MEDICION:
        return None
    noun, verb = _VOLUME_WORDS[source]
    name = "Wikipedia" if source is Source.WIKIMEDIA else "GDELT"
    minimum = min_volume(source)
    r_min = ratio_min()
    ratio: float | None = None
    en, es = english.value or 0.0, spanish.value or 0.0
    if SideState.INSUFICIENTE in (english.state, spanish.state):
        result = SourceResult.INSUFICIENTE
        explanation = f"Datos insuficientes: {_side_reasons(english, spanish)}."
        short = f"en {name} faltan datos para comparar"
    elif english.state is SideState.SIN_MEDICION:
        result = SourceResult.SIN_MEDICION_INGLES
        explanation = f"{fmt_int(es)} {noun} en español en 7 días; DETECTAR no midió el lado en inglés."
        short = f"en {name} solo hay mediciones en español"
    elif spanish.state is SideState.SIN_MEDICION:
        if en >= minimum:
            result = SourceResult.SIN_MEDICION_ESPANOL
            explanation = f"{fmt_int(en)} {noun} en inglés en 7 días; DETECTAR no midió el lado en español."
            short = f"en {name} hay {fmt_int(en)} {noun} en inglés y el lado en español no se midió"
        else:
            result = SourceResult.INSUFICIENTE
            explanation = f"Solo {fmt_int(en)} {noun} en inglés en 7 días: menos del mínimo ({fmt_int(minimum)})."
            short = f"en {name} el volumen en inglés es bajo"
    elif max(en, es) < minimum:
        result = SourceResult.INSUFICIENTE
        explanation = (
            f"{fmt_int(en)} {noun} en inglés y {fmt_int(es)} en español en 7 días: "
            f"volumen bajo para comparar (mínimo {fmt_int(minimum)})."
        )
        short = f"en {name} el volumen es bajo en ambos idiomas"
    elif es == 0:
        result = SourceResult.SOLO_INGLES
        explanation = f"{fmt_int(en)} {noun} en inglés y ninguna en español en 7 días."
        short = f"en {name} {verb} solo en inglés"
    else:
        ratio = en / es
        if ratio >= r_min:
            result = SourceResult.BRECHA
            explanation = (
                f"{fmt_int(en)} {noun} en inglés frente a {fmt_int(es)} en español en 7 días: "
                f"{fmt_ratio(ratio)} más en inglés."
            )
            short = f"en {name} {verb} {fmt_ratio(ratio)} más en inglés"
        elif ratio <= 1 / r_min:
            result = SourceResult.MAS_FUERTE_ESPANOL
            explanation = (
                f"{fmt_int(en)} {noun} en inglés frente a {fmt_int(es)} en español en 7 días: "
                f"{fmt_ratio(1 / ratio)} más en español."
            )
            short = f"en {name} {verb} más en español"
        else:
            result = SourceResult.PARIDAD
            explanation = (
                f"{fmt_int(en)} {noun} en inglés y {fmt_int(es)} en español en 7 días: "
                f"atención parecida ({fmt_ratio(ratio)})."
            )
            short = f"en {name} la atención es parecida en ambos idiomas"
    if not validated:
        short += " (GDELT no está validada)"
    return SourceComparison(
        source=source,
        validated=validated,
        metric=SOURCE_METRICS[source][0],
        unit="views" if source is Source.WIKIMEDIA else "articles",
        english=english,
        spanish=spanish,
        ratio=ratio,
        result=result,
        explanation=explanation,
        short=short,
        trend=_trend_text(english, spanish),
    )


def _trend_text(english: Side, spanish: Side) -> str | None:
    g_en, g_es = english.growth, spanish.growth
    if g_en is not None and g_es is not None:
        return f"Crecimiento semanal según DETECTAR: {fmt_pct(g_en)} en inglés y {fmt_pct(g_es)} en español."
    if g_en is not None:
        return f"Crecimiento semanal en inglés según DETECTAR: {fmt_pct(g_en)}."
    if g_es is not None:
        return f"Crecimiento semanal en español según DETECTAR: {fmt_pct(g_es)}."
    return None


# --- Google Trends RSS: presencia por país ----------------------------------------------------


def _presence_side(
    language: Language,
    countries: Iterable[str],
    by_country: Mapping[str, MetricInfo],
    known: Mapping[str, int],
) -> Side:
    scopes = []
    for country in countries:
        share = by_country.get(country)
        if share is not None:
            if share.ok:
                present, seen = share.details.get("present"), share.details.get("known")
                scopes.append(
                    ScopeMeasure(
                        country,
                        share.value,
                        present=present if isinstance(present, int) else None,
                        known=seen if isinstance(seen, int) else None,
                    )
                )
            else:
                scopes.append(ScopeMeasure(country, None, reason=share.reason))
        elif known.get(country, 0) >= gtr_min_known_captures():
            # El país se capturó y el tema no apareció: es una ausencia medida, no un dato faltante.
            scopes.append(ScopeMeasure(country, 0.0, present=0, known=known[country]))
    if not scopes:
        return Side(language, SideState.SIN_MEDICION)
    measured = [s.value for s in scopes if s.value is not None]
    if not measured:
        return Side(language, SideState.INSUFICIENTE, None, tuple(scopes))
    return Side(language, SideState.MEDIDO, max(measured), tuple(scopes))


def _captures_text(scope: ScopeMeasure) -> str:
    if scope.present is not None and scope.known is not None:
        return f"{scope.present} de {scope.known} capturas de {country_label(scope.scope)}"
    return f"las capturas de {country_label(scope.scope)}"


def _countries(side: Side) -> str:
    return join_es([country_label(s.scope) for s in side.scopes if s.value is not None])


def _compare_presence(
    metrics: list[MetricInfo], known: Mapping[str, int], validated: bool
) -> SourceComparison | None:
    by_country = {m.scope: m for m in metrics if m.key == SOURCE_METRICS[Source.GOOGLE_TRENDS_RSS][0]}
    if not by_country:
        return None  # el tema nunca apareció en el RSS: la fuente no aplica
    english = _presence_side(Language.EN, ENGLISH_COUNTRIES, by_country, known)
    spanish = _presence_side(Language.ES, LATAM_COUNTRIES, by_country, known)
    if english.state is SideState.SIN_MEDICION and spanish.state is SideState.SIN_MEDICION:
        return None
    r_min = ratio_min()
    ratio: float | None = None
    en, es = english.value or 0.0, spanish.value or 0.0
    en_best, es_best = english.best, spanish.best
    if SideState.INSUFICIENTE in (english.state, spanish.state):
        result = SourceResult.INSUFICIENTE
        explanation = f"Datos insuficientes: {_side_reasons(english, spanish)}."
        short = "en Google Trends faltan capturas para comparar"
    elif english.state is SideState.SIN_MEDICION:
        result = SourceResult.SIN_MEDICION_INGLES
        explanation = "No hay capturas de países de habla inglesa en la ventana; solo se midió Latinoamérica."
        short = "en Google Trends solo se midió Latinoamérica"
    elif spanish.state is SideState.SIN_MEDICION:
        if en > 0 and en_best is not None:
            result = SourceResult.SIN_MEDICION_ESPANOL
            explanation = f"Aparece en {_captures_text(en_best)}; no hay capturas de Latinoamérica en la ventana."
            short = f"es tendencia en {country_label(en_best.scope)}, pero no hay capturas de Latinoamérica"
        else:
            result = SourceResult.INSUFICIENTE
            explanation = "No aparece en las capturas de habla inglesa y Latinoamérica no se capturó."
            short = "en Google Trends no hay señal"
    elif en == 0 and es == 0:
        result = SourceResult.INSUFICIENTE
        explanation = "No aparece en las capturas de la ventana en ningún país comparado."
        short = "en Google Trends no aparece en la ventana"
    elif es == 0 and en_best is not None:
        result = SourceResult.SOLO_INGLES
        explanation = sentence(f"Aparece en {_captures_text(en_best)} y en ninguna captura de {_countries(spanish)}")
        short = f"es tendencia en {country_label(en_best.scope)} y no en {_countries(spanish)}"
    elif en == 0 and es_best is not None:
        result = SourceResult.MAS_FUERTE_ESPANOL
        explanation = sentence(f"Aparece en {_captures_text(es_best)} y en ninguna captura de {_countries(english)}")
        short = f"es tendencia en {country_label(es_best.scope)} y no en {_countries(english)}"
    else:
        assert en_best is not None and es_best is not None
        ratio = en / es
        both = f"{_captures_text(en_best)} y en {_captures_text(es_best)}"
        if ratio >= r_min:
            result = SourceResult.BRECHA
            explanation = f"Aparece en {both}: {fmt_ratio(ratio)} más presencia en inglés."
            short = f"es más tendencia en {country_label(en_best.scope)} que en {country_label(es_best.scope)}"
        elif ratio <= 1 / r_min:
            result = SourceResult.MAS_FUERTE_ESPANOL
            explanation = f"Aparece en {both}: {fmt_ratio(1 / ratio)} más presencia en español."
            short = f"es más tendencia en {country_label(es_best.scope)} que en {country_label(en_best.scope)}"
        else:
            result = SourceResult.PARIDAD
            explanation = f"Aparece en {both}: presencia parecida."
            short = (
                f"en Google Trends aparece tanto en {country_label(en_best.scope)} "
                f"como en {country_label(es_best.scope)}"
            )
    return SourceComparison(
        source=Source.GOOGLE_TRENDS_RSS,
        validated=validated,
        metric=SOURCE_METRICS[Source.GOOGLE_TRENDS_RSS][0],
        unit="ratio",
        english=english,
        spanish=spanish,
        ratio=ratio,
        result=result,
        explanation=explanation,
        short=short,
    )


# --- veredicto --------------------------------------------------------------------------------


def decide(comparisons: Sequence[SourceComparison]) -> Verdict:
    validated = {c.direction for c in comparisons if c.validated}
    complementary = {c.direction for c in comparisons if not c.validated}
    if "ingles" in validated and "espanol" in validated:
        return Verdict.SENALES_MIXTAS
    if "ingles" in validated:
        return Verdict.BRECHA_CONFIRMADA
    if validated & {"espanol", "pareja"}:
        return Verdict.SIN_BRECHA
    if "falta_espanol" in validated or complementary & {"ingles", "falta_espanol"}:
        return Verdict.BRECHA_POR_CONFIRMAR
    return Verdict.DATOS_INSUFICIENTES


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _shorts(comparisons: Sequence[SourceComparison], directions: set[str]) -> list[str]:
    ordered = sorted(comparisons, key=lambda c: (not c.validated, COMPARED_SOURCES.index(c.source)))
    return [c.short for c in ordered if c.direction in directions]


def summarize(verdict: Verdict, comparisons: Sequence[SourceComparison]) -> str:
    if verdict is Verdict.BRECHA_CONFIRMADA:
        text = sentence(f"Hay brecha: {'; '.join(_shorts(comparisons, {'ingles'}))}")
        others = _shorts(comparisons, {"pareja", "falta_espanol"})
        return f"{text} {sentence(_capitalize('; '.join(others)))}" if others else text
    if verdict is Verdict.BRECHA_POR_CONFIRMAR:
        evidence = sentence(f"Posible brecha: {'; '.join(_shorts(comparisons, {'ingles', 'falta_espanol'}))}")
        return f"{evidence} Para confirmarla, DETECTAR debe medir también el lado en español."
    if verdict is Verdict.SENALES_MIXTAS:
        return sentence(
            f"Señales mixtas: {'; '.join(_shorts(comparisons, {'ingles'}))}, "
            f"pero {'; '.join(_shorts(comparisons, {'espanol'}))}"
        )
    if verdict is Verdict.SIN_BRECHA:
        return sentence(f"Sin brecha: {'; '.join(_shorts(comparisons, {'espanol', 'pareja'}))}")
    if any(c.direction == "falta_ingles" for c in comparisons):
        return (
            "Solo hay mediciones en español: para buscar brechas, DETECTAR debe medir también en "
            "inglés (por ejemplo, en.wikipedia.org o Google Trends de EE. UU.)."
        )
    return "Datos insuficientes para comparar inglés y español."


def analyze_topic(
    topic_id: str,
    topic_name: str,
    metrics: Sequence[MetricInfo],
    known_captures: Mapping[str, int],
) -> GapAnalysis:
    """Analiza un tema con sus métricas de una misma fecha de referencia."""
    by_source: dict[Source, list[MetricInfo]] = defaultdict(list)
    for metric in metrics:
        if metric.topic_id != topic_id:
            raise ValueError("Métrica de otro tema")
        by_source[metric.source].append(metric)
    comparisons: list[SourceComparison] = []
    notes: list[str] = []
    for source in COMPARED_SOURCES:
        items = by_source.get(source, [])
        if not items:
            continue
        validated = all(m.validated for m in items)
        if source is Source.GOOGLE_TRENDS_RSS:
            comparison = _compare_presence(items, known_captures, validated)
        else:
            english, spanish, source_notes = _volume_sides(source, items)
            notes.extend(source_notes)
            comparison = _compare_volume(source, english, spanish, validated)
        if comparison is not None:
            comparisons.append(comparison)
    if any(not c.validated for c in comparisons):
        notes.append("GDELT no está validada con la fuente real: puede sugerir una brecha, nunca confirmarla.")
    verdict = decide(comparisons)
    return GapAnalysis(
        topic_id=topic_id,
        topic_name=topic_name,
        verdict=verdict,
        summary=summarize(verdict, comparisons),
        comparisons=tuple(comparisons),
        notes=tuple(notes),
    )
