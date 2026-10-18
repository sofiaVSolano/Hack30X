"""Contrato común de los motores de generación de CREAR.

Un motor recibe el contexto creativo (solo datos con procedencia) y los parámetros elegidos, y
devuelve el contenido de cada propuesta con el esquema ``ProposalContent``. Ningún motor
escribe en una base de datos: el servicio decide qué se guarda.

``ProposalContent`` es también el esquema de salida estructurada de Claude: sus
descripciones forman parte de las instrucciones que recibe el modelo.
"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.crear.catalog import AUDIENCES, COUNTRIES, Approach, Platform
from app.modules.crear.context import CreativeContext


class ProposalContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(description="Título de trabajo, concreto y atractivo; como máximo 90 caracteres.")
    gancho: str = Field(description="Primera frase o primeros segundos: lo que hace que la audiencia se quede.")
    idea_central: str = Field(description="La idea de la pieza en una o dos frases.")
    estructura: list[str] = Field(
        description="De 4 a 8 pasos en orden, con marcas de tiempo, diapositivas o bloques según el formato."
    )
    formato: str = Field(description="Formato de la pieza en la plataforma elegida (duración, extensión, estilo).")
    llamado_a_la_accion: str = Field(description="Qué se le pide a la audiencia al final.")
    adaptacion_latam: list[str] = Field(
        description="De 2 a 5 indicaciones para adaptar la pieza al país o a Latinoamérica."
    )
    palabras_clave: list[str] = Field(description="De 3 a 6 palabras clave o etiquetas, sin el símbolo #.")
    precauciones: list[str] = Field(
        description="De 1 a 4 riesgos concretos de la pieza: datos a verificar, sensibilidad del tema, derechos."
    )


class CreativeParams(BaseModel):
    """Para quién y dónde: lo que la persona elige en el laboratorio."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audiencia: str
    audiencia_detalle: str | None = None
    plataforma: Platform
    pais: str | None = None

    @field_validator("audiencia")
    @classmethod
    def _known_audience(cls, value: str) -> str:
        if value not in AUDIENCES:
            raise ValueError("Audiencia desconocida")
        return value

    @field_validator("pais")
    @classmethod
    def _known_country(cls, value: str | None) -> str | None:
        if value is not None and value not in COUNTRIES:
            raise ValueError("País no disponible en el catálogo")
        return value


@dataclass(frozen=True)
class PreviousProposal:
    """La versión que se regenera (RF-10)."""

    approach: Approach
    params: CreativeParams
    content: ProposalContent
    version: int


class GenerationError(RuntimeError):
    """El motor no pudo generar. El mensaje es apto para mostrarse: sin secretos ni datos."""


class Engine(Protocol):
    id: str
    model: str | None

    def generate_batch(self, context: CreativeContext, params: CreativeParams) -> dict[Approach, ProposalContent]: ...

    def regenerate(
        self,
        context: CreativeContext,
        previous: PreviousProposal,
        approach: Approach,
        params: CreativeParams,
        instruction: str | None,
        version: int,
    ) -> ProposalContent: ...


# --- normalización ------------------------------------------------------------------------

_TEXT_LIMITS = {"titulo": 160, "gancho": 400, "idea_central": 700, "formato": 400, "llamado_a_la_accion": 400}
_LIST_LIMITS = {"estructura": (10, 400), "adaptacion_latam": (6, 300), "palabras_clave": (8, 60), "precauciones": (6, 300)}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize(content: ProposalContent) -> ProposalContent:
    """Recorta longitudes, quita vacíos y repetidos. No cambia el sentido del contenido."""
    data: dict[str, object] = {}
    for name, limit in _TEXT_LIMITS.items():
        data[name] = _clip(getattr(content, name), limit)
    for name, (max_items, limit) in _LIST_LIMITS.items():
        seen: set[str] = set()
        items: list[str] = []
        for raw in getattr(content, name):
            item = _clip(raw, limit)
            if name == "palabras_clave":
                item = item.lstrip("#").strip()
            key = item.casefold()
            if item and key not in seen:
                seen.add(key)
                items.append(item)
        data[name] = items[:max_items]
    return ProposalContent.model_validate(data)
