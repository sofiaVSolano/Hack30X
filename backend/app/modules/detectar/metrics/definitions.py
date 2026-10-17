"""Definiciones de las métricas ``metrics-v1``: única fuente de verdad (código, API y docs).

Principios:

- Cada fuente se mide por separado y en su propia unidad; no hay índices combinados.
- Ventanas de días UTC cerrados: la ventana actual termina en ``as_of`` (incluido) y dura
  ``window_days``; la anterior es la inmediatamente previa, del mismo tamaño.
- Un dato ausente nunca se trata como cero: una ventana con días faltantes es insuficiente.
- Una tasa de crecimiento solo se calcula si la base alcanza un mínimo; si no, queda
  insuficiente (evita porcentajes engañosos o divisiones por cero).
"""

from dataclasses import asdict, dataclass

from app.modules.detectar.storage.models import MetricUnit, Source

RULES_VERSION = "metrics-v1"

# Parámetros exactos de la versión; se guardan en ``rules_versions``.
PARAMS: dict[str, object] = {
    "window_days": 7,
    # Google Trends: capturas mínimas con datos del país en cada ventana.
    "gtr_min_known_captures": 3,
    # Wikimedia: visitas mínimas de la ventana base para calcular una tasa (10/día).
    "wiki_min_base_views": 70,
    # GDELT: artículos mínimos de la ventana base para calcular una tasa (1/día).
    "gdelt_min_base_articles": 7,
    "max_input_ids": 500,
}

# Estado de validación real de cada conector (ver docs/validacion-fuentes-reales.md).
SOURCE_VALIDATED = {
    Source.GOOGLE_TRENDS_RSS: True,
    Source.WIKIMEDIA: True,
    Source.GDELT: False,
}


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    source: Source
    unit: MetricUnit
    scope: str
    description: str
    formula: str
    required_data: str
    min_period: str
    insufficient_when: str
    limitations: str

    def as_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["source"] = self.source.value
        data["unit"] = self.unit.value
        return data


_W = "ventana de 7 días cerrados que termina en as_of"

DEFINITIONS: tuple[MetricDefinition, ...] = (
    # --- Google Trends RSS ---------------------------------------------------------------
    MetricDefinition(
        key="gtr_presence_captures",
        source=Source.GOOGLE_TRENDS_RSS,
        unit=MetricUnit.CAPTURES,
        scope="país (informado por Google)",
        description="Capturas del RSS del país en las que el tema aparecía.",
        formula="nº de instantes de captura distintos con presencia del tema en el país",
        required_data="observaciones gtr_trending_presence vinculadas al tema",
        min_period=_W,
        insufficient_when="no hay ninguna captura conocida del país en la ventana",
        limitations="Solo cuenta capturas guardadas; no es volumen de búsquedas.",
    ),
    MetricDefinition(
        key="gtr_presence_share",
        source=Source.GOOGLE_TRENDS_RSS,
        unit=MetricUnit.RATIO,
        scope="país (informado por Google)",
        description="Fracción de capturas conocidas del país en las que el tema aparecía.",
        formula="capturas con el tema / capturas conocidas del país en la ventana",
        required_data="todas las observaciones gtr_trending_presence del país (denominador)",
        min_period=_W,
        insufficient_when="menos de 3 capturas conocidas del país en la ventana",
        limitations=(
            "Capturas conocidas = instantes con al menos una tendencia guardada para el país; "
            "capturas vacías o fallidas no se cuentan. El RSS solo lista unas 10 tendencias."
        ),
    ),
    MetricDefinition(
        key="gtr_presence_share_change",
        source=Source.GOOGLE_TRENDS_RSS,
        unit=MetricUnit.RATIO_DIFFERENCE,
        scope="país (informado por Google)",
        description="Cambio de la fracción de presencia respecto de la ventana anterior.",
        formula="presence_share(actual) - presence_share(anterior); diferencia, no tasa",
        required_data="capturas en la ventana actual y en la anterior",
        min_period="dos ventanas consecutivas de 7 días",
        insufficient_when="alguna de las dos ventanas tiene menos de 3 capturas conocidas",
        limitations="Mide cambio de presencia en capturas, no crecimiento de búsquedas.",
    ),
    MetricDefinition(
        key="gtr_max_traffic_lower_bound",
        source=Source.GOOGLE_TRENDS_RSS,
        unit=MetricUnit.SEARCHES_LOWER_BOUND,
        scope="país (informado por Google)",
        description="Mayor cota inferior de tráfico informada ('200+' -> 200) en la ventana.",
        formula="máximo de gtr_approx_traffic_min con valor numérico",
        required_data="observaciones gtr_approx_traffic_min con valor",
        min_period=_W,
        insufficient_when="ninguna captura trae un tráfico interpretable como cota inferior",
        limitations="Es una cota inferior aproximada de Google, no un volumen exacto.",
    ),
    MetricDefinition(
        key="gtr_interest_countries",
        source=Source.GOOGLE_TRENDS_RSS,
        unit=MetricUnit.COUNTRIES,
        scope="* (tema completo)",
        description="Países en cuyo RSS apareció el tema al menos una vez en la ventana.",
        formula="nº de países distintos con presence_captures >= 1",
        required_data="observaciones gtr_trending_presence vinculadas",
        min_period=_W,
        insufficient_when="el tema no tiene observaciones de Google Trends",
        limitations="País de interés según Google; no equivale a país del medio (GDELT).",
    ),
    # --- Wikimedia ------------------------------------------------------------------------
    MetricDefinition(
        key="wiki_views_total",
        source=Source.WIKIMEDIA,
        unit=MetricUnit.VIEWS,
        scope="artículo (proyecto:Artículo)",
        description="Visitas de personas al artículo en la ventana.",
        formula="suma de visitas diarias de los 7 días",
        required_data="los 7 días con observación wiki_pageviews",
        min_period=_W,
        insufficient_when="falta algún día de la ventana (no se rellena con cero)",
        limitations="Visitas a Wikipedia, no búsquedas; la edición no indica el país.",
    ),
    MetricDefinition(
        key="wiki_views_daily_mean",
        source=Source.WIKIMEDIA,
        unit=MetricUnit.VIEWS_PER_DAY,
        scope="artículo (proyecto:Artículo)",
        description="Promedio diario de visitas en la ventana.",
        formula="wiki_views_total / 7",
        required_data="los 7 días",
        min_period=_W,
        insufficient_when="falta algún día de la ventana",
        limitations="Igual que wiki_views_total.",
    ),
    MetricDefinition(
        key="wiki_views_abs_change",
        source=Source.WIKIMEDIA,
        unit=MetricUnit.VIEWS,
        scope="artículo (proyecto:Artículo)",
        description="Diferencia absoluta de visitas respecto de la ventana anterior.",
        formula="total(actual) - total(anterior)",
        required_data="14 días completos",
        min_period="dos ventanas consecutivas de 7 días",
        insufficient_when="falta algún día en alguna ventana",
        limitations="Diferencia absoluta; no es una tasa.",
    ),
    MetricDefinition(
        key="wiki_views_growth",
        source=Source.WIKIMEDIA,
        unit=MetricUnit.GROWTH_RATE,
        scope="artículo (proyecto:Artículo)",
        description="Tasa de crecimiento de visitas respecto de la ventana anterior.",
        formula="(total(actual) - total(anterior)) / total(anterior)",
        required_data="14 días completos",
        min_period="dos ventanas consecutivas de 7 días",
        insufficient_when="falta algún día, o total(anterior) < 70 visitas (base insuficiente)",
        limitations="Fracción (0.5 = +50 %). Con bases pequeñas no se calcula.",
    ),
    MetricDefinition(
        key="wiki_views_acceleration",
        source=Source.WIKIMEDIA,
        unit=MetricUnit.GROWTH_RATE_DIFFERENCE,
        scope="artículo (proyecto:Artículo)",
        description="Cambio de la tasa de crecimiento entre ventanas consecutivas.",
        formula="growth(actual vs anterior) - growth(anterior vs previa)",
        required_data="21 días completos",
        min_period="tres ventanas consecutivas de 7 días",
        insufficient_when="falta algún día o alguna base < 70 visitas",
        limitations="Diferencia entre tasas, no una tasa.",
    ),
    # --- GDELT ----------------------------------------------------------------------------
    MetricDefinition(
        key="gdelt_articles_total",
        source=Source.GDELT,
        unit=MetricUnit.ARTICLES,
        scope="consulta (término + filtros de idioma/país del medio)",
        description="Artículos de noticias monitoreados por GDELT que coinciden con la consulta.",
        formula="suma de gdelt_article_count de los 7 días",
        required_data="los 7 días con observación de la misma consulta",
        min_period=_W,
        insufficient_when="falta algún día de la ventana",
        limitations=(
            "Cobertura periodística, no búsquedas ni redes. Conector NO validado con la API "
            "real: source_validated=false."
        ),
    ),
    MetricDefinition(
        key="gdelt_articles_daily_mean",
        source=Source.GDELT,
        unit=MetricUnit.ARTICLES_PER_DAY,
        scope="consulta (término + filtros)",
        description="Promedio diario de artículos en la ventana.",
        formula="gdelt_articles_total / 7",
        required_data="los 7 días",
        min_period=_W,
        insufficient_when="falta algún día",
        limitations="Igual que gdelt_articles_total.",
    ),
    MetricDefinition(
        key="gdelt_articles_abs_change",
        source=Source.GDELT,
        unit=MetricUnit.ARTICLES,
        scope="consulta (término + filtros)",
        description="Diferencia absoluta de artículos respecto de la ventana anterior.",
        formula="total(actual) - total(anterior)",
        required_data="14 días completos",
        min_period="dos ventanas consecutivas de 7 días",
        insufficient_when="falta algún día en alguna ventana",
        limitations="Diferencia absoluta; no es una tasa.",
    ),
    MetricDefinition(
        key="gdelt_articles_growth",
        source=Source.GDELT,
        unit=MetricUnit.GROWTH_RATE,
        scope="consulta (término + filtros)",
        description="Tasa de crecimiento de la cobertura respecto de la ventana anterior.",
        formula="(total(actual) - total(anterior)) / total(anterior)",
        required_data="14 días completos",
        min_period="dos ventanas consecutivas de 7 días",
        insufficient_when="falta algún día, o total(anterior) < 7 artículos",
        limitations="Fracción. Con bases pequeñas no se calcula.",
    ),
    MetricDefinition(
        key="gdelt_articles_acceleration",
        source=Source.GDELT,
        unit=MetricUnit.GROWTH_RATE_DIFFERENCE,
        scope="consulta (término + filtros)",
        description="Cambio de la tasa de crecimiento de la cobertura.",
        formula="growth(actual vs anterior) - growth(anterior vs previa)",
        required_data="21 días completos",
        min_period="tres ventanas consecutivas de 7 días",
        insufficient_when="falta algún día o alguna base < 7 artículos",
        limitations="Diferencia entre tasas.",
    ),
    MetricDefinition(
        key="gdelt_publisher_countries",
        source=Source.GDELT,
        unit=MetricUnit.COUNTRIES,
        scope="* (tema completo)",
        description="Países de MEDIOS con al menos un artículo, entre consultas filtradas por país.",
        formula="nº de países del medio (filtro sourcecountry) con artículos > 0 en la ventana",
        required_data="observaciones con country_basis = publisher_country",
        min_period=_W,
        insufficient_when="ninguna consulta del tema se filtró por país del medio",
        limitations="País del medio que publica, no de la audiencia ni del interés de búsqueda.",
    ),
)

BY_KEY = {definition.key: definition for definition in DEFINITIONS}
