"""Reglas ``brechas-v1``: comparación inglés–español de un tema (RF-06).

Pregunta que responden: ¿el tema recibe mucha más atención en inglés que en español? Si es
así, hay una brecha que un creador latinoamericano puede cubrir adaptando el tema.

Principios (los mismos de DETECTAR):

- Cada fuente se compara por separado y en su propia unidad; no hay índice combinado ni
  puntuación.
- Un dato ausente nunca es cero: si un idioma no se midió, se dice («sin medición»).
- Solo una fuente validada puede confirmar una brecha; GDELT (no validada) solo la sugiere.
- Los umbrales son PROVISIONALES y no están calibrados con datos reales.

Qué mide cada fuente como «inglés» y «español»:

- Wikimedia: visitas de 7 días (``wiki_views_total``) de artículos de ``en.wikipedia.org``
  frente a ``es.wikipedia.org``.
- GDELT: artículos de 7 días (``gdelt_articles_total``) de consultas ``sourcelang:english``
  frente a ``sourcelang:spanish``.
- Google Trends RSS: presencia en las capturas de países de habla inglesa (EE. UU., Reino
  Unido…) frente a países hispanohablantes de Latinoamérica (``gtr_presence_share``).
"""

import hashlib
import json
import re
from enum import StrEnum

from app.modules.crear.catalog import COUNTRIES
from app.modules.detectar.storage.models import Source

RULES_VERSION = "brechas-v1"

ENGLISH_COUNTRY_NAMES = {
    "AU": "Australia",
    "CA": "Canadá",
    "GB": "Reino Unido",
    "IE": "Irlanda",
    "NZ": "Nueva Zelanda",
    "US": "EE. UU.",
}
ENGLISH_COUNTRIES = tuple(sorted(ENGLISH_COUNTRY_NAMES))
LATAM_COUNTRIES = tuple(sorted(COUNTRIES))

PARAMS: dict[str, object] = {
    "metrics_rules_version": "metrics-v1",
    # Razón mínima entre idiomas para hablar de brecha (y su inversa, de ventaja del español).
    "ratio_min": 3.0,
    # Volumen mínimo (7 días) del idioma con más atención para afirmar una diferencia:
    # con cifras más pequeñas, una razón no significa nada.
    "wiki_min_views": 700,
    "gdelt_min_articles": 7,
    # Capturas mínimas del país en la ventana para afirmar que el tema NO apareció
    # (el mismo mínimo de metrics-v1 para calcular la presencia).
    "gtr_min_known_captures": 3,
    "english_countries": list(ENGLISH_COUNTRIES),
    "latam_countries": list(LATAM_COUNTRIES),
    "calibrated": False,
}


class Language(StrEnum):
    EN = "en"
    ES = "es"


class SourceResult(StrEnum):
    """Resultado de comparar una fuente."""

    BRECHA = "brecha"
    SOLO_INGLES = "solo_ingles"
    PARIDAD = "paridad"
    MAS_FUERTE_ESPANOL = "mas_fuerte_espanol"
    SIN_MEDICION_ESPANOL = "sin_medicion_espanol"
    SIN_MEDICION_INGLES = "sin_medicion_ingles"
    INSUFICIENTE = "insuficiente"


class Verdict(StrEnum):
    """Veredicto del tema. Es una categoría con reglas explícitas, no una puntuación."""

    BRECHA_CONFIRMADA = "brecha_confirmada"
    BRECHA_POR_CONFIRMAR = "brecha_por_confirmar"
    SENALES_MIXTAS = "senales_mixtas"
    SIN_BRECHA = "sin_brecha"
    DATOS_INSUFICIENTES = "datos_insuficientes"


RESULT_DEFINITIONS: dict[SourceResult, str] = {
    SourceResult.BRECHA: "En inglés hay al menos ratio_min veces más atención que en español.",
    SourceResult.SOLO_INGLES: "Hay atención en inglés y, medida, ninguna en español.",
    SourceResult.PARIDAD: "Ambos idiomas tienen atención parecida (razón entre 1/ratio_min y ratio_min).",
    SourceResult.MAS_FUERTE_ESPANOL: "En español hay al menos ratio_min veces más atención que en inglés.",
    SourceResult.SIN_MEDICION_ESPANOL: "Hay atención en inglés, pero DETECTAR no midió el lado en español.",
    SourceResult.SIN_MEDICION_INGLES: "Solo hay mediciones en español: no se puede comparar.",
    SourceResult.INSUFICIENTE: "Faltan datos o el volumen es menor que el mínimo para comparar.",
}

# Hacia dónde apunta cada resultado. El veredicto solo combina direcciones.
DIRECTION: dict[SourceResult, str] = {
    SourceResult.BRECHA: "ingles",
    SourceResult.SOLO_INGLES: "ingles",
    SourceResult.PARIDAD: "pareja",
    SourceResult.MAS_FUERTE_ESPANOL: "espanol",
    SourceResult.SIN_MEDICION_ESPANOL: "falta_espanol",
    SourceResult.SIN_MEDICION_INGLES: "falta_ingles",
    SourceResult.INSUFICIENTE: "insuficiente",
}

VERDICT_DEFINITIONS: dict[Verdict, str] = {
    Verdict.BRECHA_CONFIRMADA: (
        "Al menos una fuente validada muestra mucha más atención en inglés y ninguna fuente "
        "validada muestra lo contrario."
    ),
    Verdict.BRECHA_POR_CONFIRMAR: (
        "Hay atención en inglés, pero el lado en español no se midió o solo lo sugiere una "
        "fuente no validada (GDELT)."
    ),
    Verdict.SENALES_MIXTAS: (
        "Fuentes validadas apuntan en direcciones opuestas: una a favor del inglés y otra a "
        "favor del español."
    ),
    Verdict.SIN_BRECHA: (
        "Las fuentes validadas muestran atención parecida en ambos idiomas o mayor en español."
    ),
    Verdict.DATOS_INSUFICIENTES: "No hay mediciones en inglés que permitan comparar.",
}

# Orden de prioridad para listar: primero lo más útil para crear.
VERDICT_ORDER = (
    Verdict.BRECHA_CONFIRMADA,
    Verdict.BRECHA_POR_CONFIRMAR,
    Verdict.SENALES_MIXTAS,
    Verdict.SIN_BRECHA,
    Verdict.DATOS_INSUFICIENTES,
)

# Métricas de E8 que usa cada fuente: el nivel de 7 días y, como contexto, su crecimiento.
# Google Trends usa la fracción de capturas con el tema (sus detalles traen present/known).
SOURCE_METRICS: dict[Source, tuple[str, ...]] = {
    Source.WIKIMEDIA: ("wiki_views_total", "wiki_views_growth"),
    Source.GDELT: ("gdelt_articles_total", "gdelt_articles_growth"),
    Source.GOOGLE_TRENDS_RSS: ("gtr_presence_share",),
}

_WIKI_LANGUAGES = {"en": Language.EN, "es": Language.ES}
_GDELT_LANGUAGES = {"english": Language.EN, "spanish": Language.ES}
_SOURCELANG = re.compile(r"(?:^|\s)sourcelang:([a-z]+)\b")
_SOURCECOUNTRY = re.compile(r"(?:^|\s)sourcecountry:")


def _number(name: str) -> float:
    value = PARAMS[name]
    assert isinstance(value, int | float)
    return float(value)


def ratio_min() -> float:
    return _number("ratio_min")


def min_volume(source: Source) -> float:
    return _number("wiki_min_views" if source is Source.WIKIMEDIA else "gdelt_min_articles")


def gtr_min_known_captures() -> int:
    return int(_number("gtr_min_known_captures"))


def wiki_language(scope: str) -> Language | None:
    """«en.wikipedia.org:Artículo» -> inglés. Otras ediciones no se comparan."""
    project, separator, _article = scope.partition(":")
    code, _, domain = project.partition(".")
    if not separator or domain != "wikipedia.org":
        return None
    return _WIKI_LANGUAGES.get(code)


def gdelt_language(scope: str) -> Language | None:
    """Idioma del filtro ``sourcelang:`` de la consulta; sin filtro no se compara."""
    match = _SOURCELANG.search(scope)
    return _GDELT_LANGUAGES.get(match.group(1)) if match else None


def gdelt_country_filtered(scope: str) -> bool:
    return bool(_SOURCECOUNTRY.search(scope))


def gtr_language(country: str) -> Language | None:
    if country in ENGLISH_COUNTRIES:
        return Language.EN
    if country in LATAM_COUNTRIES:
        return Language.ES
    return None


def country_label(code: str) -> str:
    return ENGLISH_COUNTRY_NAMES.get(code) or COUNTRIES.get(code) or code


def params_sha256() -> str:
    return hashlib.sha256(json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()
