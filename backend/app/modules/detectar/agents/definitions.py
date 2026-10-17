"""Definiciones declarativas de agentes.

Una definición describe qué es un agente y qué tiene permitido hacer. No contiene estado
ni frecuencias: el estado se deriva de sus ejecuciones registradas y la frecuencia
viene de la configuración (``DETECTAR_AGENT_SCHEDULES``).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.detectar.storage.models import Source


class OfficeModule(StrEnum):
    DETECTAR = "detectar"
    ENTENDER = "entender"
    CREAR = "crear"
    VALIDAR = "validar"


class AgentScope(StrEnum):
    DETECTAR = "detectar"
    ENTENDER = "entender"
    CREAR = "crear"
    VALIDAR = "validar"
    TRANSVERSAL = "transversal"


class AgentTool(StrEnum):
    """Capacidades internas que un agente puede usar. Solo se listan las que existen."""

    DETECTAR_OBSERVATIONS_READ = "detectar_observations_read"
    AGENT_RUNS_READ = "agent_runs_read"


class ImplementationStatus(StrEnum):
    PLANNED = "planned"  # definido, sin tarea implementada: sus ejecuciones quedan bloqueadas
    AVAILABLE = "available"


class AssignmentStatus(StrEnum):
    PROVISIONAL = "provisional"  # pendiente de acordar con el equipo
    AGREED = "agreed"


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=10, max_length=500)
    responsibility: str = Field(min_length=10, max_length=500)
    scope: AgentScope
    collaborates_with: frozenset[OfficeModule]
    allowed_sources: frozenset[Source] = frozenset()
    allowed_tools: frozenset[AgentTool] = frozenset()
    implementation_status: ImplementationStatus = ImplementationStatus.PLANNED
    assignment_status: AssignmentStatus = AssignmentStatus.PROVISIONAL
    # Dudas abiertas que impiden completar la definición; se muestran tal cual.
    open_questions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "AgentDefinition":
        if not self.collaborates_with:
            raise ValueError("Un agente debe colaborar con al menos un módulo")
        if self.scope is not AgentScope.TRANSVERSAL and OfficeModule(self.scope.value) not in (
            self.collaborates_with
        ):
            raise ValueError("Un agente de un módulo debe colaborar con ese módulo")
        if Source.YOUTUBE in self.allowed_sources:
            # YouTube solo admite consulta en vivo sin métricas derivadas (políticas III.E.4).
            raise ValueError("Ningún agente puede usar YouTube como fuente en esta versión")
        return self
