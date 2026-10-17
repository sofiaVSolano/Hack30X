"""POST /api/detectar/agentes/{agent_id}/ejecuciones (E10). Sin red real."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.modules.detectar.api.dependencies import (
    get_agent_coordinator,
    get_session_factory,
)
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import AgentRun, AgentRunTrigger, DataMode

from ..agents.test_tasks import coordinator, rss_transport
from ..metrics.test_service import wiki_series

TOKEN = "token-de-prueba-" + "a" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


def url(agent_id: str) -> str:
    return f"{API_PREFIX}/agentes/{agent_id}/ejecuciones"


def _settings() -> DetectarSettings:
    return DetectarSettings(env="test", admin_token=TOKEN, http_max_retries=0)


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    coord = coordinator(session_factory, transport=rss_transport({"MX": "two_trends.xml", "AR": 503}), settings=_settings())
    app.dependency_overrides[get_agent_coordinator] = lambda: coord
    with TestClient(app) as client:
        yield client


def _count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(AgentRun))


# --- casos válidos ------------------------------------------------------------------------


def test_supervisor_run_is_recorded_and_returned(api: TestClient, session_factory) -> None:
    response = api.post(url("supervisor"), json={"data_mode": "real", "parametros": {"limite_por_agente": 5}}, headers=AUTH)

    assert response.status_code == 201
    body = response.json()
    assert (body["agente"], body["data_mode"], body["estado"], body["disparador"]) == ("supervisor", "real", "completed", "manual")
    assert body["resultado"]["version_resumen"] == "supervisor-v1"
    assert body["solicitado"].endswith("Z") and body["fin"].endswith("Z")
    assert body["codigo_error"] is None
    assert _count(session_factory) == 1


def test_trend_hunter_with_collection(api: TestClient) -> None:
    body = {
        "data_mode": "real",
        "parametros": {"fecha_referencia": YESTERDAY.isoformat(), "recoleccion": {"fuentes": ["google_trends_rss"], "paises": ["MX"]}},
    }

    response = api.post(url("trend_hunter"), json=body, headers=AUTH)

    assert response.status_code == 201
    result = response.json()["resultado"]
    assert response.json()["estado"] == "completed"
    assert result["pasos"]["recoleccion"]["estado"] == "ok"
    assert result["pasos"]["recoleccion"]["fuentes"]["google_trends_rss"]["observaciones_nuevas"] == 3


def test_trend_hunter_on_simulated_data(api: TestClient, session_factory) -> None:
    with session_factory() as session, session.begin():
        wiki_series(session, "Tema", YESTERDAY - timedelta(days=20), [10] * 7 + [20] * 7 + [50] * 7, mode=DataMode.SIMULATED)

    response = api.post(
        url("trend_hunter"), json={"data_mode": "simulated", "parametros": {"fecha_referencia": YESTERDAY.isoformat()}}, headers=AUTH
    )

    assert response.status_code == 201
    assert response.json()["resultado"]["pasos"]["clasificacion"]["por_etapa"] == {"acelerando": 1}


def test_failed_task_is_reported_as_failed_not_success(api: TestClient) -> None:
    body = {
        "data_mode": "real",
        "parametros": {"fecha_referencia": YESTERDAY.isoformat(), "recoleccion": {"fuentes": ["google_trends_rss"], "paises": ["AR"]}},
    }

    response = api.post(url("trend_hunter"), json=body, headers=AUTH)

    assert response.status_code == 201  # la ejecución existe; el estado dice qué pasó
    assert response.json()["estado"] == "failed"
    assert response.json()["resultado"] is None
    assert "collection_failed" in response.json()["detalle_error"]


def test_registered_but_unimplemented_agent_is_blocked(api: TestClient) -> None:
    response = api.post(url("analyst"), json={"data_mode": "real"}, headers=AUTH)

    assert response.status_code == 201
    assert (response.json()["estado"], response.json()["codigo_error"]) == ("blocked", "not_implemented")


# --- autenticación y seguridad ---------------------------------------------------------------


def test_missing_or_invalid_token(api: TestClient, session_factory) -> None:
    missing = api.post(url("supervisor"), json={"data_mode": "real"})
    wrong = api.post(url("supervisor"), json={"data_mode": "real"}, headers={"Authorization": "Bearer " + "x" * 40})

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert _count(session_factory) == 0


@pytest.mark.parametrize("agent_id", ["fantasma", "build_tasks", "run_trend_hunter", "default_registry"])
def test_unknown_agents_and_function_names_are_rejected(api: TestClient, session_factory, agent_id: str) -> None:
    response = api.post(url(agent_id), json={"data_mode": "real"}, headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert _count(session_factory) == 0


@pytest.mark.parametrize("agent_id", ["__import__", "os.system", "A", "x" * 70])
def test_malformed_agent_ids_are_rejected(api: TestClient, agent_id: str) -> None:
    assert api.post(url(agent_id), json={"data_mode": "real"}, headers=AUTH).status_code in (404, 422)


def test_token_never_appears_in_responses_or_logs(api: TestClient, caplog) -> None:
    caplog.set_level(logging.DEBUG)

    texts = [
        api.post(url("supervisor"), json={"data_mode": "real"}, headers=AUTH).text,
        api.post(url("supervisor"), json={"data_mode": "real", "token": TOKEN}, headers=AUTH).text,
        caplog.text,
    ]

    assert all(TOKEN not in t for t in texts)


# --- validación de entradas --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("agent_id", "body", "code"),
    [
        ("supervisor", {}, "validation_error"),  # sin data_mode
        ("supervisor", {"data_mode": "ambos"}, "validation_error"),
        ("supervisor", {"data_mode": "real", "token": "x"}, "validation_error"),
        ("supervisor", {"data_mode": "real", "parametros": {"limite_por_agente": 0}}, "invalid_parameters"),
        ("supervisor", {"data_mode": "real", "parametros": {"funcion": "os.system"}}, "invalid_parameters"),
        ("trend_hunter", {"data_mode": "real", "parametros": {}}, "invalid_parameters"),
        ("trend_hunter", {"data_mode": "real", "parametros": {"fecha_referencia": datetime.now(UTC).date().isoformat()}}, "invalid_parameters"),
        (
            "trend_hunter",
            {"data_mode": "simulated", "parametros": {"fecha_referencia": YESTERDAY.isoformat(), "recoleccion": {"fuentes": ["google_trends_rss"]}}},
            "invalid_parameters",
        ),
        (
            "trend_hunter",
            {"data_mode": "real", "parametros": {"fecha_referencia": YESTERDAY.isoformat(), "recoleccion": {"fuentes": ["youtube"]}}},
            "source_not_enabled",
        ),
        ("analyst", {"data_mode": "real", "parametros": {"x": 1}}, "invalid_parameters"),
    ],
)
def test_invalid_input_is_rejected_before_creating_a_run(api: TestClient, session_factory, agent_id, body, code) -> None:
    response = api.post(url(agent_id), json=body, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == code
    assert _count(session_factory) == 0


# --- concurrencia y persistencia ---------------------------------------------------------------


def test_agent_with_active_run_returns_409(api: TestClient, session_factory) -> None:
    with session_factory() as session, session.begin():
        AgentRunRepository(session).create(
            "supervisor", data_mode="real", trigger=AgentRunTrigger.MANUAL, requested_at=datetime.now(UTC)
        )

    response = api.post(url("supervisor"), json={"data_mode": "real"}, headers=AUTH)

    assert response.status_code == 409
    assert response.json()["code"] == "agent_busy"


class BrokenCoordinator:
    async def start(self, *args: Any, **kwargs: Any):
        raise OperationalError("INSERT INTO agent_runs ...", {}, Exception("database is locked"))


def test_persistence_error_is_a_structured_500_without_internals(app: FastAPI, session_factory) -> None:
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_agent_coordinator] = lambda: BrokenCoordinator()

    with TestClient(app) as client:
        response = client.post(url("supervisor"), json={"data_mode": "real"}, headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "database is locked" not in response.text and "INSERT" not in response.text


# --- separación de modos y regresión de lecturas -------------------------------------------------


def test_runs_are_isolated_by_mode_and_visible_in_read_api(api: TestClient) -> None:
    api.post(url("supervisor"), json={"data_mode": "simulated"}, headers=AUTH)

    real = {a["id"]: a for a in api.get(f"{API_PREFIX}/agentes", headers=AUTH).json()["agentes"]}
    sim = {a["id"]: a for a in api.get(f"{API_PREFIX}/agentes", params={"data_mode": "simulated"}, headers=AUTH).json()["agentes"]}

    assert real["supervisor"]["actividad"] == "sin_ejecuciones"
    assert sim["supervisor"]["actividad"] == "completada"
    assert sim["supervisor"]["implementado"] is True
    history = api.get(f"{API_PREFIX}/agentes/supervisor/ejecuciones", params={"data_mode": "simulated"}, headers=AUTH).json()
    assert history["ejecuciones"][0]["data_mode"] == "simulated"
