"""Modelos de entrada y salida de la API de CREAR y su conversión desde el dominio.

Los nombres de campo están en español, como en la API de DETECTAR. No hay campos de
puntuación, confianza ni saturación: el veredicto de brechas es una categoría con reglas.
"""

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.modules.crear.catalog import (
    AUDIENCES,
    COUNTRIES,
    DEFAULT_AUDIENCE,
    Approach,
    Platform,
)
from app.modules.crear.context import CreativeContext, Origin
from app.modules.crear.detectar_reader import StageInfo
from app.modules.crear.gaps.engine import (
    GapAnalysis,
    ScopeMeasure,
    Side,
    SourceComparison,
)
from app.modules.crear.gaps.rules import SourceResult, Verdict
from app.modules.crear.generation.base import ProposalContent
from app.modules.crear.generation.factory import Generator
from app.modules.crear.storage.models import Proposal
from app.modules.detectar.storage.models import DataMode, Source, TrendStage
from app.modules.detectar.timeutil import format_utc

Mode = Literal["real", "simulated"]
TOPIC_PATTERN = r"^tpc_[0-9a-f]{16}$"
PROPOSAL_PATTERN = r"^prp_[0-9a-f]{16}$"
BATCH_PATTERN = r"^lot_[0-9a-f]{16}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str | None) -> str | None:
    """Texto libre de una persona: sin caracteres de control y con espacios normalizados."""
    if value is None:
        return None
    if _CONTROL.search(value):
        raise ValueError("No se admiten caracteres de control")
    cleaned = " ".join(value.split())
    return cleaned or None


def _check_audience(value: str | None) -> str | None:
    if value is not None and value not in AUDIENCES:
        raise ValueError("Audiencia desconocida")
    return value


def _check_country(value: str | None) -> str | None:
    if value is not None and value not in COUNTRIES:
        raise ValueError("País no disponible en el catálogo")
    return value


Audience = Annotated[str, AfterValidator(_check_audience)]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$"), AfterValidator(_check_country)]
TopicText = Annotated[str, Field(min_length=2, max_length=120), AfterValidator(_clean)]
AudienceDetail = Annotated[str, Field(max_length=200), AfterValidator(_clean)]
Instruction = Annotated[str, Field(max_length=300), AfterValidator(_clean)]


# --- opciones ---------------------------------------------------------------------------------


class OptionOut(BaseModel):
    id: str
    nombre: str
    descripcion: str


class PlatformOut(BaseModel):
    id: Platform
    nombre: str
    formato: str
    pautas: list[str]


class AudienceOut(BaseModel):
    id: str
    nombre: str
    descripcion: str
    tono: str


class CountryOut(BaseModel):
    id: str
    nombre: str


class EngineOut(BaseModel):
    id: str
    nombre: str
    modelo: str | None
    detalle: str


def engine_out(generator: Generator) -> EngineOut:
    info = generator.info
    return EngineOut(id=info.id, nombre=info.name, modelo=info.model, detalle=info.detail)


class OptionsOut(BaseModel):
    enfoques: list[OptionOut]
    plataformas: list[PlatformOut]
    audiencias: list[AudienceOut]
    audiencia_por_defecto: str
    paises: list[CountryOut]
    motor: EngineOut


# --- etapas, temas y brechas -----------------------------------------------------------------


class StageOut(BaseModel):
    etapa: TrendStage
    motivo: str | None
    fecha_referencia: date
    version: str
    calibrado: bool


class ScopeOut(BaseModel):
    ambito: str
    valor: float | None
    crecimiento: float | None
    motivo: str | None
    capturas_con_tema: int | None
    capturas_conocidas: int | None


class SideOut(BaseModel):
    idioma: Literal["en", "es"]
    estado: Literal["medido", "insuficiente", "sin_medicion"]
    valor: float | None
    ambitos: list[ScopeOut]


class ComparisonOut(BaseModel):
    fuente: Source
    fuente_validada: bool
    metrica: str
    unidad: str
    ingles: SideOut
    espanol: SideOut
    razon: float | None
    resultado: SourceResult
    explicacion: str
    tendencia: str | None


class GapOut(BaseModel):
    tema_id: str
    tema_nombre: str
    veredicto: Verdict
    resumen: str
    etapa: StageOut | None
    comparaciones: list[ComparisonOut]
    notas: list[str]


class GapPage(BaseModel):
    data_mode: DataMode
    fecha_referencia: date | None
    version: str
    calibrado: bool
    total: int
    limite: int
    desplazamiento: int
    por_veredicto: dict[str, int]
    items: list[GapOut]
    limitaciones: list[str]


class GapRulesOut(BaseModel):
    version: str
    provisional: bool
    calibrado: bool
    parametros: dict[str, object]
    parametros_sha256: str
    veredictos: dict[str, str]
    resultados: dict[str, str]
    metricas_usadas: dict[str, list[str]]
    limitaciones: list[str]


class TopicOut(BaseModel):
    id: str
    nombre: str
    data_mode: DataMode
    ambiguo: bool
    vinculos_por_fuente: dict[str, int]
    etapa: StageOut | None
    veredicto_brecha: Verdict | None


class TopicPage(BaseModel):
    data_mode: DataMode
    fecha_referencia: date | None
    total: int
    limite: int
    desplazamiento: int
    items: list[TopicOut]


def stage_out(stage: StageInfo | None) -> StageOut | None:
    if stage is None:
        return None
    return StageOut(
        etapa=stage.stage,
        motivo=stage.reason,
        fecha_referencia=stage.as_of,
        version=stage.rules_version,
        calibrado=stage.calibrated,
    )


def _scope_out(scope: ScopeMeasure) -> ScopeOut:
    return ScopeOut(
        ambito=scope.scope,
        valor=scope.value,
        crecimiento=scope.growth,
        motivo=scope.reason,
        capturas_con_tema=scope.present,
        capturas_conocidas=scope.known,
    )


def _side_out(side: Side) -> SideOut:
    return SideOut(
        idioma=side.language.value,
        estado=side.state.value,
        valor=side.value,
        ambitos=[_scope_out(s) for s in side.scopes],
    )


def _comparison_out(c: SourceComparison) -> ComparisonOut:
    return ComparisonOut(
        fuente=c.source,
        fuente_validada=c.validated,
        metrica=c.metric,
        unidad=c.unit,
        ingles=_side_out(c.english),
        espanol=_side_out(c.spanish),
        razon=c.ratio,
        resultado=c.result,
        explicacion=c.explanation,
        tendencia=c.trend,
    )


def gap_out(analysis: GapAnalysis, stage: StageInfo | None) -> GapOut:
    return GapOut(
        tema_id=analysis.topic_id,
        tema_nombre=analysis.topic_name,
        veredicto=analysis.verdict,
        resumen=analysis.summary,
        etapa=stage_out(stage),
        comparaciones=[_comparison_out(c) for c in analysis.comparisons],
        notas=list(analysis.notes),
    )


# --- propuestas ---------------------------------------------------------------------------------


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode  # obligatorio: sin valor por defecto
    origen: Origin
    tema_id: Annotated[str, Field(pattern=TOPIC_PATTERN)] | None = None
    tema_texto: TopicText | None = None
    fecha_referencia: date | None = None
    audiencia: Audience = DEFAULT_AUDIENCE
    audiencia_detalle: AudienceDetail | None = None
    plataforma: Platform
    pais: Country | None = None

    @model_validator(mode="after")
    def _origin_fields(self) -> "BatchIn":
        if self.origen is Origin.MANUAL:
            if not self.tema_texto or self.tema_id is not None:
                raise ValueError("Un tema manual requiere tema_texto (2 a 120 caracteres) y no admite tema_id")
            if len(self.tema_texto) < 2:
                raise ValueError("tema_texto debe tener al menos 2 caracteres")
        elif self.tema_id is None or self.tema_texto is not None:
            raise ValueError("Los orígenes tema y brecha requieren tema_id y no admiten tema_texto")
        return self


class RegenerationIn(BaseModel):
    """Solo los campos enviados cambian; ``pais: null`` vuelve a «toda Latinoamérica»."""

    model_config = ConfigDict(extra="forbid")

    data_mode: Mode
    enfoque: Approach | None = None
    audiencia: Audience | None = None
    audiencia_detalle: AudienceDetail | None = None
    plataforma: Platform | None = None
    pais: Country | None = None
    indicacion: Instruction | None = None


class ProposalOut(BaseModel):
    id: str
    lote_id: str
    raiz_id: str
    padre_id: str | None
    version: int
    data_mode: DataMode
    origen: Origin
    tema_id: str | None
    tema_nombre: str
    enfoque: Approach
    audiencia: str
    audiencia_detalle: str | None
    plataforma: Platform
    pais: str | None
    indicacion: str | None
    cambios: list[str]
    contenido: ProposalContent
    motor: str
    modelo: str | None
    aviso_motor: str | None
    cifras_sin_respaldo: list[str]
    creado: str


class BatchOut(BaseModel):
    lote_id: str
    data_mode: DataMode
    contexto: CreativeContext
    propuestas: list[ProposalOut]


class ProposalDetail(BaseModel):
    propuesta: ProposalOut
    versiones: list[ProposalOut]
    contexto: CreativeContext


class ProposalPage(BaseModel):
    data_mode: DataMode
    total: int
    limite: int
    desplazamiento: int
    items: list[ProposalOut]


def proposal_out(p: Proposal) -> ProposalOut:
    return ProposalOut(
        id=p.id,
        lote_id=p.batch_id,
        raiz_id=p.root_id,
        padre_id=p.parent_id,
        version=p.version,
        data_mode=p.data_mode,
        origen=p.origin,
        tema_id=p.topic_id,
        tema_nombre=p.topic_name,
        enfoque=p.approach,
        audiencia=p.audience,
        audiencia_detalle=p.audience_detail,
        plataforma=p.platform,
        pais=p.country,
        indicacion=p.instruction,
        cambios=list(p.changes),
        contenido=ProposalContent.model_validate(p.content),
        motor=p.engine,
        modelo=p.model,
        aviso_motor=p.engine_notice,
        cifras_sin_respaldo=list(p.unsupported_figures),
        creado=format_utc(p.created_at),
    )
