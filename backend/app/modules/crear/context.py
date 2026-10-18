"""Contexto creativo: lo que se sabe de un tema, con su procedencia, antes de generar.

Es lo único que reciben los motores de generación. Cada hecho es una frase con cifras de
DETECTAR (o del análisis ``brechas-v1`` hecho sobre esas cifras); la verificación de cifras de
una propuesta solo admite números que aparezcan en estos hechos o en las pautas del catálogo.
El contexto se guarda con cada propuesta: así se sabe con qué datos se creó.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.gaps.engine import GapAnalysis
from app.modules.crear.gaps.rules import RULES_VERSION as GAPS_VERSION
from app.modules.crear.gaps.rules import Verdict
from app.modules.crear.gaps.service import GapService
from app.modules.crear.text import fmt_day
from app.modules.detectar.storage.models import DataMode, Source, TrendStage

STAGE_LABELS: dict[TrendStage, str] = {
    TrendStage.EMERGENTE: "Emergente",
    TrendStage.ACELERANDO: "Acelerando",
    TrendStage.PUNTO_MAXIMO: "Punto máximo",
    TrendStage.SATURADA: "Saturada",
    TrendStage.DATOS_INSUFICIENTES: "Datos insuficientes",
}

SOURCE_LABELS: dict[Source, str] = {
    Source.WIKIMEDIA: "Wikipedia",
    Source.GDELT: "GDELT (prensa)",
    Source.GOOGLE_TRENDS_RSS: "Google Trends",
}

MANUAL_LIMITATION = (
    "Tema escrito a mano: DETECTAR no tiene datos que lo respalden. Las propuestas no citan cifras "
    "ni afirman que sea tendencia."
)

# Veredictos en los que la atención en inglés supera a la del español en alguna fuente.
ENGLISH_LEADS = frozenset({Verdict.BRECHA_CONFIRMADA, Verdict.BRECHA_POR_CONFIRMAR, Verdict.SENALES_MIXTAS})


class Origin(StrEnum):
    TEMA = "tema"  # un tema detectado por DETECTAR
    BRECHA = "brecha"  # el análisis de brechas inglés–español de un tema (RF-06)
    MANUAL = "manual"  # un tema escrito por la persona: sin datos de DETECTAR


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clave: str
    texto: str
    fuente: str


class CreativeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origen: Origin
    data_mode: DataMode
    tema_id: str | None
    tema_nombre: str
    fecha_referencia: date | None
    etapa: TrendStage | None
    etapa_calibrada: bool | None
    veredicto_brecha: Verdict | None
    resumen_brecha: str | None
    hechos: list[Fact]
    limitaciones: list[str]

    @property
    def english_leads(self) -> bool:
        return self.veredicto_brecha in ENGLISH_LEADS


class TopicNotFoundError(LookupError):
    pass


class NoGapAnalysisError(LookupError):
    """Se pidió partir de una brecha, pero el tema no tiene comparación inglés–español."""


def _gap_facts(analysis: GapAnalysis) -> list[Fact]:
    source = f"CREAR · {GAPS_VERSION} sobre métricas de DETECTAR"
    facts = [Fact(clave="brecha", texto=analysis.summary, fuente=source)]
    for comparison in analysis.comparisons:
        label = SOURCE_LABELS.get(comparison.source, comparison.source.value)
        validated = "" if comparison.validated else " (fuente no validada)"
        facts.append(
            Fact(
                clave=f"comparacion:{comparison.source.value}",
                texto=f"{label}{validated}: {comparison.explanation}",
                fuente=source,
            )
        )
        if comparison.trend:
            facts.append(Fact(clave=f"tendencia:{comparison.source.value}", texto=comparison.trend, fuente="DETECTAR · métricas"))
    return facts


class ContextBuilder:
    def __init__(self, reader: DetectarReader) -> None:
        self._reader = reader

    def for_topic(
        self, topic_id: str, *, data_mode: DataMode | str, origin: Origin, as_of: date | None = None
    ) -> CreativeContext:
        if origin is Origin.MANUAL:
            raise ValueError("Un tema manual no se lee de DETECTAR")
        mode = DataMode(data_mode)
        topic = self._reader.topic(topic_id, data_mode=mode)
        if topic is None:
            raise TopicNotFoundError(topic_id)
        report = GapService(self._reader).analyze_one(topic_id, data_mode=mode, as_of=as_of)
        analysis = report.analyses[0] if report.analyses else None
        if origin is Origin.BRECHA and analysis is None:
            raise NoGapAnalysisError(topic_id)
        stage = self._reader.current_stages([topic_id], data_mode=mode).get(topic_id)

        facts: list[Fact] = []
        limitations: list[str] = []
        if stage is not None:
            calibration = "" if stage.calibrated else ", sin calibrar"
            facts.append(
                Fact(
                    clave="etapa",
                    texto=(
                        f"Etapa en DETECTAR: {STAGE_LABELS[stage.stage]} "
                        f"(al {fmt_day(stage.as_of)}; reglas {stage.rules_version}{calibration})."
                    ),
                    fuente="DETECTAR · clasificación",
                )
            )
            if not stage.calibrated:
                limitations.append("La etapa usa reglas provisionales sin calibrar: es una señal, no una certeza.")
        if analysis is not None:
            facts.extend(_gap_facts(analysis))
            limitations.extend(analysis.notes)
        if mode is DataMode.SIMULATED:
            limitations.append(
                "Datos simulados de demostración: el tema y sus cifras son inventados y no describen hechos reales."
            )
        return CreativeContext(
            origen=origin,
            data_mode=mode,
            tema_id=topic.id,
            tema_nombre=topic.name,
            fecha_referencia=report.as_of or (stage.as_of if stage else None),
            etapa=stage.stage if stage else None,
            etapa_calibrada=stage.calibrated if stage else None,
            veredicto_brecha=analysis.verdict if analysis else None,
            resumen_brecha=analysis.summary if analysis else None,
            hechos=facts,
            limitaciones=limitations,
        )

    @staticmethod
    def for_manual(text: str, *, data_mode: DataMode | str) -> CreativeContext:
        return CreativeContext(
            origen=Origin.MANUAL,
            data_mode=DataMode(data_mode),
            tema_id=None,
            tema_nombre=" ".join(text.split()),
            fecha_referencia=None,
            etapa=None,
            etapa_calibrada=None,
            veredicto_brecha=None,
            resumen_brecha=None,
            hechos=[],
            limitaciones=[MANUAL_LIMITATION],
        )
