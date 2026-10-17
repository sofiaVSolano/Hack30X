"""Definiciones y parámetros de ``stages-v1`` (PROVISIONALES, no calibrados).

Ver ``docs/clasificacion-etapas-v1.md``. Los parámetros se registran en
``rules_versions`` con su sha256; cambiarlos exige una versión nueva.
"""

import hashlib
import json

from app.modules.detectar.metrics.definitions import (
    RULES_VERSION as METRICS_RULES_VERSION,
)
from app.modules.detectar.storage.models import Source, TrendStage

RULES_VERSION = "stages-v1"

PARAMS: dict[str, object] = {
    "metrics_rules_version": METRICS_RULES_VERSION,
    "window_days": 7,
    "growth_min": 0.20,
    "acceleration_min": 0.10,
    "flat_band": 0.10,
    "gtr_share_rise_min": 0.30,
    "calibrated": False,
}

STAGE_DEFINITIONS: dict[TrendStage, str] = {
    TrendStage.EMERGENTE: (
        "Hay señales recientes de aparición o crecimiento del tema, pero no hay evidencia "
        "suficiente de que su crecimiento se esté acelerando."
    ),
    TrendStage.ACELERANDO: (
        "Hay crecimiento y aumento de ese crecimiento en tres ventanas completas y "
        "comparables de una misma fuente validada."
    ),
    TrendStage.PUNTO_MAXIMO: (
        "Tras una subida en la ventana anterior, la actividad se estabilizó en un nivel "
        "superior al previo (meseta). No afirma un máximo absoluto ni anticipa el descenso."
    ),
    TrendStage.SATURADA: (
        "Requiere evidencia de saturación (oferta de contenido frente a demanda). stages-v1 "
        "NO la asigna: E8 no tiene métricas de oferta y la popularidad alta no la demuestra."
    ),
    TrendStage.DATOS_INSUFICIENTES: (
        "Falta historia temporal, faltan métricas, las señales se contradicen o la única "
        "evidencia proviene de una fuente no validada."
    ),
}

# Qué etapas puede proponer cada fuente en v1.
SOURCE_CAPABILITIES: dict[Source, tuple[TrendStage, ...]] = {
    Source.WIKIMEDIA: (TrendStage.EMERGENTE, TrendStage.ACELERANDO, TrendStage.PUNTO_MAXIMO),
    Source.GDELT: (TrendStage.EMERGENTE, TrendStage.ACELERANDO, TrendStage.PUNTO_MAXIMO),
    Source.GOOGLE_TRENDS_RSS: (TrendStage.EMERGENTE,),
}

# Métricas de E8 que intervienen en la clasificación; el resto (niveles) no infiere etapas.
STAGE_METRICS: dict[Source, tuple[str, str] | tuple[str]] = {
    Source.WIKIMEDIA: ("wiki_views_growth", "wiki_views_acceleration"),
    Source.GDELT: ("gdelt_articles_growth", "gdelt_articles_acceleration"),
    Source.GOOGLE_TRENDS_RSS: ("gtr_presence_share_change",),
}


def params_sha256() -> str:
    return hashlib.sha256(json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()
