"""GET /api/detectar/agentes/programador y ciclo de vida preparado para main.py (E11)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.detectar.agents.registry import default_registry
from app.modules.detectar.agents.scheduler import AgentScheduler
from app.modules.detectar.api import dependencies
from app.modules.detectar.api.agents import get_scheduler_for_status
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings

from ..agents.test_tasks import coordinator

TOKEN = "token-de-prueba-" + "p" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = f"{API_PREFIX}/agentes/programador"
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)


def _settings(**overrides) -> DetectarSettings:
    return DetectarSettings(env="test", admin_token=TOKEN, **overrides)


def _client(app: FastAPI, session_factory, cfg: DetectarSettings) -> tuple[TestClient, AgentScheduler]:
    sched = AgentScheduler(coordinator(session_factory, clock=lambda: NOW), session_factory, default_registry(), cfg, clock=lambda: NOW)
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[get_scheduler_for_status] = lambda: sched
    return TestClient(app), sched


@pytest.fixture
def default_api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    client, _ = _client(app, session_factory, _settings())
    with client:
        yield client


def test_status_requires_admin_token(default_api: TestClient) -> None:
    assert default_api.get(URL).status_code == 401
    assert default_api.get(URL, headers={"Authorization": "Bearer " + "q" * 40}).status_code == 401


def test_default_status_is_disabled_with_nothing_scheduled(default_api: TestClient) -> None:
    body = default_api.get(URL, headers=AUTH).json()

    assert (body["habilitado"], body["en_ejecucion"], body["ultimo_tick"]) == (False, False, None)
    assert all(a["programado"] is False and a["motivo_omision"] == "sin_frecuencia" for a in body["agentes"])
    assert body["umbral_abandono_segundos"] == 3600


def test_status_shows_plan_reasons_and_last_tick(app: FastAPI, session_factory) -> None:
    cfg = _settings(
        scheduler_enabled=True,
        agent_schedules={"supervisor": 60, "analyst": 60, "trend_hunter": 240},
        scheduler_agent_modes={"supervisor": "simulated"},
    )
    client, sched = _client(app, session_factory, cfg)
    asyncio.run(sched.tick())

    with client:
        body = client.get(URL, headers=AUTH).json()

    agents = {a["agente"]: a for a in body["agentes"]}
    assert agents["supervisor"] == {
        "agente": "supervisor", "programado": True, "motivo_omision": None, "frecuencia_minutos": 60, "data_mode": "simulated",
    }
    assert agents["analyst"]["motivo_omision"] == "no_implementado"
    assert agents["trend_hunter"]["motivo_omision"] == "sin_data_mode"
    assert body["habilitado"] is True and body["en_ejecucion"] is False  # sin lifespan no arranca
    assert body["ultimo_tick"]["lanzadas"][0]["agente"] == "supervisor"
    assert body["ultimo_tick"]["momento"].endswith("Z")


def test_invalid_configuration_is_a_structured_error(app: FastAPI, session_factory, monkeypatch) -> None:
    app.dependency_overrides[get_settings] = lambda: _settings()

    def broken():
        raise ValueError("Frecuencia fuera de rango")

    monkeypatch.setattr("app.modules.detectar.api.agents.get_agent_scheduler", broken)
    with TestClient(app) as client:
        response = client.get(URL, headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "invalid_configuration"
    assert "Frecuencia" not in response.text


def test_status_endpoint_does_not_create_runs(default_api: TestClient, session_factory) -> None:
    from sqlalchemy import func, select

    from app.modules.detectar.storage.models import AgentRun

    default_api.get(URL, headers=AUTH)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0


# --- ciclo de vida para main.py (integración pendiente) -----------------------------------------


@pytest.mark.anyio
async def test_lifespan_does_nothing_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "get_settings", lambda: DetectarSettings(scheduler_enabled=False))
    monkeypatch.setattr(dependencies, "get_agent_scheduler", lambda: pytest.fail("no debía crear el programador"))

    async with dependencies.detectar_scheduler_lifespan() as scheduler:
        assert scheduler is None


@pytest.mark.anyio
async def test_lifespan_starts_and_stops_the_scheduler(monkeypatch, session_factory) -> None:
    cfg = DetectarSettings(scheduler_enabled=True, scheduler_tick_seconds=3600)
    sched = AgentScheduler(coordinator(session_factory, clock=lambda: NOW), session_factory, default_registry(), cfg, clock=lambda: NOW)
    monkeypatch.setattr(dependencies, "get_settings", lambda: cfg)
    monkeypatch.setattr(dependencies, "get_agent_scheduler", lambda: sched)

    async with dependencies.detectar_scheduler_lifespan() as running:
        assert running is sched and sched.running is True

    assert sched.running is False
