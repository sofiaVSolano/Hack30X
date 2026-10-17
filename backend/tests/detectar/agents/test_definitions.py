"""Definiciones declarativas y registro de los seis roles iniciales."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.modules.detectar.agents.definitions import (
    AgentDefinition,
    AgentScope,
    AssignmentStatus,
    ImplementationStatus,
    OfficeModule,
)
from app.modules.detectar.agents.registry import (
    INITIAL_AGENTS,
    AgentRegistry,
    default_registry,
)
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.models import Source

EXPECTED_ROLES = {
    "trend_hunter": ("Cazador de tendencias", AgentScope.DETECTAR),
    "format_hunter": ("Cazador de formatos", AgentScope.DETECTAR),
    "analyst": ("Analista", AgentScope.ENTENDER),
    "audience_filter": ("Filtro de audiencia", AgentScope.ENTENDER),
    "strategist": ("Estratega", AgentScope.CREAR),
    "supervisor": ("Supervisor", AgentScope.TRANSVERSAL),
}


def test_registry_contains_exactly_the_six_roles() -> None:
    registry = default_registry()

    assert set(registry.ids) == set(EXPECTED_ROLES)
    for agent_id, (name, scope) in EXPECTED_ROLES.items():
        definition = registry.get(agent_id)
        assert definition.name == name
        assert definition.scope is scope
        assert definition.responsibility
        assert definition.description


def test_module_assignment_matches_the_provisional_plan() -> None:
    registry = default_registry()

    for hunter in ("trend_hunter", "format_hunter"):
        assert OfficeModule.DETECTAR in registry.get(hunter).collaborates_with
    for agent_id in ("analyst", "audience_filter"):
        assert OfficeModule.ENTENDER in registry.get(agent_id).collaborates_with
    assert OfficeModule.CREAR in registry.get("strategist").collaborates_with
    assert registry.get("supervisor").collaborates_with == frozenset(OfficeModule)
    # VALIDAR conserva su responsabilidad: ningún agente pertenece a VALIDAR.
    assert all(d.scope is not AgentScope.VALIDAR for d in registry.all())


def test_all_roles_are_provisional_and_only_two_are_implemented() -> None:
    # E10: solo trend_hunter y supervisor tienen tarea; los demás siguen planificados.
    implemented = {
        d.id for d in INITIAL_AGENTS if d.implementation_status is ImplementationStatus.AVAILABLE
    }
    assert implemented == {"trend_hunter", "supervisor"}
    for definition in INITIAL_AGENTS:
        assert definition.assignment_status is AssignmentStatus.PROVISIONAL


def test_no_agent_uses_disabled_or_restricted_sources() -> None:
    restricted = {Source.YOUTUBE, Source.INSTAGRAM, Source.X}

    for definition in INITIAL_AGENTS:
        assert not definition.allowed_sources & restricted


def test_trend_hunter_uses_only_the_core_sources() -> None:
    assert default_registry().get("trend_hunter").allowed_sources == {
        Source.GOOGLE_TRENDS_RSS,
        Source.WIKIMEDIA,
        Source.GDELT,
    }


def test_format_hunter_declares_that_it_has_no_source_yet() -> None:
    definition = default_registry().get("format_hunter")

    assert definition.allowed_sources == frozenset()
    assert definition.open_questions


def test_definitions_are_immutable() -> None:
    definition = default_registry().get("analyst")

    with pytest.raises(ValidationError):
        definition.name = "Otro"  # type: ignore[misc]


def test_definitions_have_no_hardcoded_frequency_or_state() -> None:
    fields = set(AgentDefinition.model_fields)

    assert not fields & {"schedule", "frequency", "interval", "status", "state", "last_run"}


def _valid(**overrides: object) -> dict[str, object]:
    return {
        "id": "agente_prueba",
        "name": "Agente de prueba",
        "description": "Descripción suficientemente larga.",
        "responsibility": "Responsabilidad delimitada de prueba.",
        "scope": AgentScope.DETECTAR,
        "collaborates_with": frozenset({OfficeModule.DETECTAR}),
    } | overrides


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "Agente Con Espacios"},
        {"id": "ab"},
        {"name": ""},
        {"collaborates_with": frozenset()},
        {"scope": AgentScope.CREAR},  # su módulo no está entre los colaboradores
        {"allowed_sources": frozenset({Source.YOUTUBE})},
        {"allowed_tools": frozenset({"llm_libre"})},
        {"campo_extra": True},
    ],
)
def test_invalid_definitions_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentDefinition(**_valid(**overrides))


def test_duplicate_ids_are_rejected() -> None:
    definition = AgentDefinition(**_valid())

    with pytest.raises(ValueError, match="duplicado"):
        AgentRegistry([definition, definition])


def test_unknown_agent_lookup_fails() -> None:
    with pytest.raises(LookupError):
        default_registry().get("agente_inexistente")


# --- Frecuencias configurables --------------------------------------------------


def test_schedules_come_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETECTAR_AGENT_SCHEDULES", '{"trend_hunter": 240, "supervisor": 480}')

    schedules = default_registry().resolve_schedules(DetectarSettings().agent_schedules)

    assert schedules["trend_hunter"] == timedelta(hours=4)
    assert schedules["supervisor"] == timedelta(hours=8)
    assert schedules["analyst"] is None  # sin configuración: solo manual


def test_without_configuration_every_agent_is_manual() -> None:
    schedules = default_registry().resolve_schedules(DetectarSettings().agent_schedules)

    assert set(schedules.values()) == {None}


@pytest.mark.parametrize(
    "config",
    [{"agente_inexistente": 60}, {"trend_hunter": 5}, {"trend_hunter": 60 * 24 * 8}],
)
def test_invalid_schedules_are_rejected(config: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        default_registry().resolve_schedules(config)
