"""Contextos creativos y parámetros de prueba para los motores de generación."""

from datetime import date

from app.modules.crear.catalog import Platform
from app.modules.crear.context import ContextBuilder, CreativeContext, Fact, Origin
from app.modules.crear.gaps.rules import Verdict
from app.modules.crear.generation.base import CreativeParams
from app.modules.detectar.storage.models import DataMode, TrendStage

GAP_FACT = "Wikipedia: 9800 visitas en inglés frente a 392 en español en 7 días: 25,0× más en inglés."


def gap_context(*, mode: DataMode = DataMode.REAL, name: str = "Tema Eta") -> CreativeContext:
    return CreativeContext(
        origen=Origin.BRECHA,
        data_mode=mode,
        tema_id="tpc_00000000000000e1",
        tema_nombre=name,
        fecha_referencia=date(2026, 9, 30),
        etapa=TrendStage.ACELERANDO,
        etapa_calibrada=False,
        veredicto_brecha=Verdict.BRECHA_CONFIRMADA,
        resumen_brecha="Hay brecha: en Wikipedia se lee 25,0× más en inglés.",
        hechos=[
            Fact(clave="etapa", texto="Etapa en DETECTAR: Acelerando (al 30 de septiembre de 2026; reglas stages-v1, sin calibrar).", fuente="DETECTAR"),
            Fact(clave="comparacion:wikimedia", texto=GAP_FACT, fuente="CREAR"),
        ],
        limitaciones=["La etapa usa reglas provisionales sin calibrar: es una señal, no una certeza."],
    )


def plain_context() -> CreativeContext:
    """Un tema de DETECTAR sin etapa ni brecha: ninguna variante puede afirmar nada."""
    return gap_context().model_copy(
        update={"origen": Origin.TEMA, "etapa": None, "etapa_calibrada": None, "veredicto_brecha": None, "resumen_brecha": None, "hechos": []}
    )


def manual_context(text: str = "Recetas con maíz") -> CreativeContext:
    return ContextBuilder.for_manual(text, data_mode=DataMode.REAL)


def params(platform: Platform = Platform.TIKTOK, *, audience: str = "general_latam", country: str | None = "MX", detail: str | None = None) -> CreativeParams:
    return CreativeParams(audiencia=audience, audiencia_detalle=detail, plataforma=platform, pais=country)
