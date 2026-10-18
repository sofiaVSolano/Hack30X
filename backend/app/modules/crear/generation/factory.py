"""Selección del motor y respaldo con plantillas.

``Generator`` es lo único que usa el servicio: intenta el motor principal (Claude, si está
configurado) y, si falla, genera con plantillas y deja constancia del motivo en la propuesta.
Así el laboratorio siempre responde, también sin red o sin credencial.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.crear.catalog import Approach
from app.modules.crear.config import CrearSettings
from app.modules.crear.context import CreativeContext
from app.modules.crear.generation.base import (
    CreativeParams,
    Engine,
    GenerationError,
    PreviousProposal,
    ProposalContent,
    normalize,
)
from app.modules.crear.generation.templates import TemplateEngine, describe

TEMPLATES_INSTRUCTION_NOTICE = (
    "Las plantillas no interpretan indicaciones libres: la indicación se guardó, pero el texto solo "
    "cambia con el enfoque, la audiencia o la plataforma."
)


@dataclass(frozen=True)
class EngineInfo:
    id: str
    name: str
    model: str | None
    detail: str


@dataclass(frozen=True)
class GenerationOutput:
    contents: dict[Approach, ProposalContent]
    engine: str
    model: str | None
    notice: str | None  # por qué se usó el respaldo, o qué no pudo aplicar el motor


class Generator:
    def __init__(self, primary: Engine | None, *, reason: str | None = None) -> None:
        self._primary = primary
        self._templates = TemplateEngine()
        self._reason = reason  # por qué no hay motor principal

    @property
    def info(self) -> EngineInfo:
        if self._primary is not None:
            return EngineInfo(
                self._primary.id,
                "Claude",
                self._primary.model,
                f"Claude ({self._primary.model}) con salida estructurada; si no responde, se usan plantillas.",
            )
        return EngineInfo(self._templates.id, "Plantillas (sin IA)", None, self._reason or describe())

    def batch(self, context: CreativeContext, params: CreativeParams) -> GenerationOutput:
        notice = None
        if self._primary is not None:
            try:
                contents = self._primary.generate_batch(context, params)
                return GenerationOutput(
                    {approach: normalize(c) for approach, c in contents.items()},
                    self._primary.id,
                    self._primary.model,
                    None,
                )
            except GenerationError as exc:
                notice = f"{exc} Se usaron plantillas."
        return GenerationOutput(self._templates.generate_batch(context, params), self._templates.id, None, notice)

    def regenerate(
        self,
        context: CreativeContext,
        previous: PreviousProposal,
        approach: Approach,
        params: CreativeParams,
        instruction: str | None,
        version: int,
    ) -> GenerationOutput:
        notice = None
        if self._primary is not None:
            try:
                content = self._primary.regenerate(context, previous, approach, params, instruction, version)
                return GenerationOutput({approach: normalize(content)}, self._primary.id, self._primary.model, None)
            except GenerationError as exc:
                notice = f"{exc} Se usaron plantillas."
        content = self._templates.regenerate(context, previous, approach, params, instruction, version)
        if instruction:
            notice = f"{notice} {TEMPLATES_INSTRUCTION_NOTICE}" if notice else TEMPLATES_INSTRUCTION_NOTICE
        return GenerationOutput({approach: content}, self._templates.id, None, notice)


def has_anthropic_credentials(env: Mapping[str, str] = os.environ) -> bool:
    """Credencial explícita en el entorno. ``CREAR_MOTOR=claude`` admite además perfiles de ``ant``."""
    return any(env.get(name, "").strip() for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))


def build_generator(settings: CrearSettings, env: Mapping[str, str] = os.environ) -> Generator:
    if settings.motor == "plantillas":
        return Generator(None, reason="Motor configurado: plantillas (CREAR_MOTOR=plantillas).")
    if settings.motor == "auto" and not has_anthropic_credentials(env):
        return Generator(
            None,
            reason="Sin credencial de Anthropic en el entorno: se usan plantillas. Defina ANTHROPIC_API_KEY para usar Claude.",
        )
    try:
        from app.modules.crear.generation.claude import ClaudeEngine

        return Generator(ClaudeEngine(settings))
    except ImportError:
        return Generator(None, reason="El paquete anthropic no está instalado: se usan plantillas.")
