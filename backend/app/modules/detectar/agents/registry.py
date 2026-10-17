"""Registro inicial de los seis roles de la oficina.

La asignación de módulos es PROVISIONAL hasta acordarla con el equipo. En E10,
``trend_hunter`` y ``supervisor`` tienen tarea implementada (``agents/tasks.py``); los demás
siguen en ``planned`` y sus ejecuciones quedan bloqueadas con ``not_implemented``.
VALIDAR conserva su responsabilidad de validación y no tiene un agente asignado aquí.
"""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from types import MappingProxyType

from app.modules.detectar.agents.definitions import (
    AgentDefinition,
    AgentScope,
    AgentTool,
    ImplementationStatus,
    OfficeModule,
)
from app.modules.detectar.storage.models import Source

MIN_SCHEDULE_MINUTES = 15
MAX_SCHEDULE_MINUTES = 7 * 24 * 60

_CONTRACT_PENDING = "El contrato con {module} no está definido; no se asume su formato."

INITIAL_AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        id="trend_hunter",
        name="Cazador de tendencias",
        description="Busca temas cuyo interés crece en las señales públicas recolectadas.",
        responsibility="Identificar señales de crecimiento de temas a partir de las fuentes de DETECTAR.",
        scope=AgentScope.DETECTAR,
        collaborates_with=frozenset({OfficeModule.DETECTAR}),
        allowed_sources=frozenset({Source.GOOGLE_TRENDS_RSS, Source.WIKIMEDIA, Source.GDELT}),
        allowed_tools=frozenset({AgentTool.DETECTAR_OBSERVATIONS_READ}),
        implementation_status=ImplementationStatus.AVAILABLE,  # E10
    ),
    AgentDefinition(
        id="format_hunter",
        name="Cazador de formatos",
        description="Busca patrones de formatos de contenido asociados a los temas detectados.",
        responsibility="Identificar patrones de formatos de contenido.",
        scope=AgentScope.DETECTAR,
        collaborates_with=frozenset({OfficeModule.DETECTAR}),
        open_questions=(
            (
                "No hay una fuente aprobada para observar formatos: YouTube solo se consulta "
                "en vivo sin métricas derivadas, e Instagram y X están desactivados."
            ),
        ),
    ),
    AgentDefinition(
        id="analyst",
        name="Analista",
        description="Examina los hallazgos de los cazadores y propone explicaciones sustentadas.",
        responsibility="Proponer explicaciones basadas solo en las señales registradas.",
        scope=AgentScope.ENTENDER,
        collaborates_with=frozenset({OfficeModule.DETECTAR, OfficeModule.ENTENDER}),
        allowed_tools=frozenset({AgentTool.DETECTAR_OBSERVATIONS_READ}),
        open_questions=(_CONTRACT_PENDING.format(module="ENTENDER"),),
    ),
    AgentDefinition(
        id="audience_filter",
        name="Filtro de audiencia",
        description="Evalúa si una oportunidad encaja con una audiencia configurada.",
        responsibility="Evaluar el encaje de las oportunidades con la audiencia configurada.",
        scope=AgentScope.ENTENDER,
        collaborates_with=frozenset({OfficeModule.ENTENDER}),
        open_questions=(
            _CONTRACT_PENDING.format(module="ENTENDER"),
            "No existe todavía una definición de 'audiencia configurada'.",
        ),
    ),
    AgentDefinition(
        id="strategist",
        name="Estratega",
        description="Transforma oportunidades seleccionadas en propuestas de contenido.",
        responsibility="Convertir oportunidades seleccionadas en propuestas de contenido.",
        scope=AgentScope.CREAR,
        collaborates_with=frozenset({OfficeModule.CREAR}),
        open_questions=(_CONTRACT_PENDING.format(module="CREAR"),),
    ),
    AgentDefinition(
        id="supervisor",
        name="Supervisor",
        description="Coordina las ejecuciones de los agentes y prepara un resumen consolidado.",
        responsibility="Coordinar ejecuciones y resumir sus resultados reales.",
        scope=AgentScope.TRANSVERSAL,
        collaborates_with=frozenset(OfficeModule),
        allowed_tools=frozenset({AgentTool.AGENT_RUNS_READ}),
        implementation_status=ImplementationStatus.AVAILABLE,  # E10
        open_questions=(
            "El formato del resumen (supervisor-v1) es provisional; pendiente de acordar con el equipo.",
        ),
    ),
)


class AgentRegistry:
    def __init__(self, definitions: Iterable[AgentDefinition]) -> None:
        by_id: dict[str, AgentDefinition] = {}
        for definition in definitions:
            if definition.id in by_id:
                raise ValueError(f"Id de agente duplicado: {definition.id!r}")
            by_id[definition.id] = definition
        self._by_id = MappingProxyType(by_id)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def all(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._by_id.values())

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._by_id[agent_id]
        except KeyError:
            raise LookupError(f"Agente desconocido: {agent_id!r}") from None

    def resolve_schedules(self, minutes_by_agent: Mapping[str, int]) -> dict[str, timedelta | None]:
        """Convierte la configuración en frecuencias. ``None`` = solo ejecución manual."""
        unknown = set(minutes_by_agent) - set(self._by_id)
        if unknown:
            raise ValueError(f"Agentes desconocidos en la configuración: {sorted(unknown)}")
        schedules: dict[str, timedelta | None] = {}
        for agent_id in self._by_id:
            minutes = minutes_by_agent.get(agent_id)
            if minutes is None:
                schedules[agent_id] = None
                continue
            if not MIN_SCHEDULE_MINUTES <= minutes <= MAX_SCHEDULE_MINUTES:
                raise ValueError(
                    f"Frecuencia de {agent_id!r} fuera de rango "
                    f"({MIN_SCHEDULE_MINUTES}-{MAX_SCHEDULE_MINUTES} minutos)"
                )
            schedules[agent_id] = timedelta(minutes=minutes)
        return schedules


def default_registry() -> AgentRegistry:
    return AgentRegistry(INITIAL_AGENTS)
