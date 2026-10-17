"""Endpoints de lectura para la futura oficina: listado de recolecciones y agentes.

Los datos de prueba se insertan en una SQLite temporal; no hay red real.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.detectar.agents.registry import INITIAL_AGENTS
from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRun,
    AgentRunTrigger,
    CollectionRun,
    CollectionStatus,
    CollectionTrigger,
    DataMode,
    Source,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository

TOKEN = "token-de-prueba-" + "w" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    settings = DetectarSettings(env="test", admin_token=TOKEN, agent_schedules={"trend_hunter": 240})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def _collection(session_factory, *, mode=DataMode.REAL, status=CollectionStatus.OK, minutes=0, error=None):
    created = T0 + timedelta(minutes=minutes)
    with session_factory() as session, session.begin():
        repo = DetectarRepository(session)
        running = status is not CollectionStatus.QUEUED
        run = repo.create_collection_run(
            data_mode=mode,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[Source.GOOGLE_TRENDS_RSS],
            requested_countries=["MX"],
            created_at=created,
            status=CollectionStatus.RUNNING if running else CollectionStatus.QUEUED,
            started_at=created if running else None,
        )
        if running:
            repo.add_source_run(
                collection_run_id=run.id,
                data_mode=mode,
                source=Source.GOOGLE_TRENDS_RSS,
                mode="on",
                status=SourceRunStatus.FAILED if error else SourceRunStatus.OK,
                started_at=created,
                finished_at=created + timedelta(seconds=5),
                items=0 if error else 4,
                error_code=error,
                error_detail="detalle" if error else None,
            )
        if status not in (CollectionStatus.RUNNING, CollectionStatus.QUEUED):
            repo.finish_collection_run(
                run.id, data_mode=mode, status=status, finished_at=created + timedelta(seconds=6)
            )
        return run.id


def _counts(session_factory) -> tuple[int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(CollectionRun)),
            session.scalar(select(func.count()).select_from(AgentRun)),
        )


# --- Autenticación y privacidad ----------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/recolecciones", "/agentes", "/agentes/trend_hunter/ejecuciones"]
)
def test_read_endpoints_require_admin_token(api: TestClient, path: str) -> None:
    missing = api.get(API_PREFIX + path)
    wrong = api.get(API_PREFIX + path, headers={"Authorization": "Bearer " + "v" * 40})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["code"] == "unauthorized"
    assert "agentes" not in missing.json().get("detail", "")


def test_read_endpoints_are_disabled_without_token(app: FastAPI, session_factory) -> None:
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test")
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    with TestClient(app) as client:
        assert client.get(f"{API_PREFIX}/agentes", headers=AUTH).status_code == 403


def test_responses_and_logs_do_not_leak_the_token(
    api: TestClient, session_factory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    _collection(session_factory)

    texts = [
        api.get(f"{API_PREFIX}/recolecciones", headers=AUTH).text,
        api.get(f"{API_PREFIX}/agentes", headers=AUTH).text,
        api.get(f"{API_PREFIX}/agentes/fantasma_x/ejecuciones", headers=AUTH).text,
        caplog.text,
    ]

    assert all(TOKEN not in text for text in texts)


# --- Listado de recolecciones ---------------------------------------------------------------


def test_list_returns_stored_summaries_most_recent_first(api: TestClient, session_factory) -> None:
    older = _collection(session_factory, minutes=0)
    newer = _collection(session_factory, minutes=10, status=CollectionStatus.FAILED, error="upstream_timeout")

    page = api.get(f"{API_PREFIX}/recolecciones", headers=AUTH).json()

    assert page["data_mode"] == "real"
    assert page["total"] == 2
    assert [item["run_id"] for item in page["items"]] == [newer, older]
    failed = page["items"][0]
    assert failed["estado"] == "failed"
    assert failed["fuentes"] == [
        {
            "fuente": "google_trends_rss",
            "estado": "failed",
            "observaciones_nuevas": 0,
            "codigo_error": "upstream_timeout",
        }
    ]
    assert failed["inicio"].endswith("Z") and failed["fin"].endswith("Z")
    assert page["items"][1]["fuentes"][0]["observaciones_nuevas"] == 4


def test_list_filters_by_status_and_mode(api: TestClient, session_factory) -> None:
    ok = _collection(session_factory)
    _collection(session_factory, minutes=1, status=CollectionStatus.PARTIAL)
    simulated = _collection(session_factory, mode=DataMode.SIMULATED, minutes=2)

    only_ok = api.get(f"{API_PREFIX}/recolecciones", params={"estado": "ok"}, headers=AUTH).json()
    sim = api.get(f"{API_PREFIX}/recolecciones", params={"data_mode": "simulated"}, headers=AUTH).json()

    assert [i["run_id"] for i in only_ok["items"]] == [ok]
    assert only_ok["total"] == 1
    assert [i["run_id"] for i in sim["items"]] == [simulated]
    assert all(i["data_mode"] == "simulated" for i in sim["items"])


def test_list_paginates_with_limits(api: TestClient, session_factory) -> None:
    ids = [_collection(session_factory, minutes=i) for i in range(5)]

    first = api.get(f"{API_PREFIX}/recolecciones", params={"limite": 2}, headers=AUTH).json()
    second = api.get(
        f"{API_PREFIX}/recolecciones", params={"limite": 2, "desplazamiento": 2}, headers=AUTH
    ).json()
    beyond = api.get(
        f"{API_PREFIX}/recolecciones", params={"desplazamiento": 50}, headers=AUTH
    ).json()

    newest_first = list(reversed(ids))
    assert [i["run_id"] for i in first["items"]] == newest_first[:2]
    assert [i["run_id"] for i in second["items"]] == newest_first[2:4]
    assert first["total"] == second["total"] == 5
    assert beyond["items"] == [] and beyond["total"] == 5


@pytest.mark.parametrize(
    "params",
    [
        {"limite": 0},
        {"limite": 101},
        {"desplazamiento": -1},
        {"desplazamiento": 10_001},
        {"data_mode": "todos"},
        {"estado": "inventado"},
    ],
)
def test_list_rejects_invalid_parameters(api: TestClient, params: dict) -> None:
    response = api.get(f"{API_PREFIX}/recolecciones", params=params, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_list_with_running_and_queued_runs(api: TestClient, session_factory) -> None:
    _collection(session_factory, status=CollectionStatus.RUNNING)
    _collection(session_factory, minutes=1, status=CollectionStatus.QUEUED)

    items = api.get(f"{API_PREFIX}/recolecciones", headers=AUTH).json()["items"]

    queued, running = items
    assert (queued["estado"], queued["inicio"], queued["fin"], queued["fuentes"]) == ("queued", None, None, [])
    assert running["estado"] == "running" and running["fin"] is None


# --- Agentes ---------------------------------------------------------------------------------


def test_agents_without_runs_are_defined_but_not_executed(api: TestClient) -> None:
    body = api.get(f"{API_PREFIX}/agentes", headers=AUTH).json()

    assert body["data_mode"] == "real"
    assert [a["id"] for a in body["agentes"]] == [d.id for d in INITIAL_AGENTS]
    for agent in body["agentes"]:
        assert agent["definido"] is True
        # E10: solo trend_hunter y supervisor tienen tarea implementada.
        assert agent["implementado"] is (agent["id"] in {"trend_hunter", "supervisor"})
        assert agent["ejecutado"] is False
        assert agent["actividad"] == "sin_ejecuciones"
        assert agent["ultima_ejecucion"] is None
    trend = body["agentes"][0]
    assert trend["nombre"] == "Cazador de tendencias"
    assert trend["frecuencia_minutos"] == 240  # viene de la configuración
    assert trend["fuentes_permitidas"] == ["gdelt", "google_trends_rss", "wikimedia"]
    assert body["agentes"][1]["preguntas_abiertas"]  # cazador de formatos sin fuente


def _agent_run(session_factory, agent_id, *, mode=DataMode.REAL, finish=None, minutes=0):
    requested = T0 + timedelta(minutes=minutes)
    with session_factory() as session, session.begin():
        runs = AgentRunRepository(session)
        run = runs.create(agent_id, data_mode=mode, trigger=AgentRunTrigger.MANUAL, requested_at=requested)
        if finish in ("running", "completed", "failed"):
            runs.mark_running(run.id, data_mode=mode, started_at=requested + timedelta(seconds=1))
        if finish == "completed":
            runs.mark_completed(run.id, data_mode=mode, finished_at=requested + timedelta(seconds=2), result={"n": 0})
        elif finish == "failed":
            runs.mark_failed(
                run.id, data_mode=mode, finished_at=requested + timedelta(seconds=2),
                error_code="task_error", error_detail="falló",
            )
        elif finish == "blocked":
            runs.mark_blocked(
                run.id, data_mode=mode, finished_at=requested + timedelta(seconds=2),
                error_code="not_implemented", error_detail="sin tarea",
            )
        return run.id


@pytest.mark.parametrize(
    ("finish", "activity"),
    [
        (None, "pendiente"),
        ("running", "en_curso"),
        ("completed", "completada"),
        ("failed", "fallida"),
        ("blocked", "bloqueada"),
    ],
)
def test_agent_activity_reflects_only_the_recorded_last_run(api, session_factory, finish, activity) -> None:
    run_id = _agent_run(session_factory, "trend_hunter", finish=finish)

    agents = {a["id"]: a for a in api.get(f"{API_PREFIX}/agentes", headers=AUTH).json()["agentes"]}

    trend = agents["trend_hunter"]
    assert trend["ejecutado"] is True
    assert trend["actividad"] == activity
    assert trend["ultima_ejecucion"]["id"] == run_id
    assert agents["analyst"]["actividad"] == "sin_ejecuciones"  # nada inventado para otros


def test_terminal_run_details_are_exposed(api: TestClient, session_factory) -> None:
    _agent_run(session_factory, "supervisor", finish="failed")

    last = {a["id"]: a for a in api.get(f"{API_PREFIX}/agentes", headers=AUTH).json()["agentes"]}[
        "supervisor"
    ]["ultima_ejecucion"]

    assert last["estado"] == "failed"
    assert last["codigo_error"] == "task_error"
    assert last["resultado"] is None
    assert last["fin"].endswith("Z")


def test_agent_status_is_isolated_by_data_mode(api: TestClient, session_factory) -> None:
    _agent_run(session_factory, "trend_hunter", mode=DataMode.SIMULATED, finish="completed")

    real = {a["id"]: a for a in api.get(f"{API_PREFIX}/agentes", headers=AUTH).json()["agentes"]}
    sim = {
        a["id"]: a
        for a in api.get(f"{API_PREFIX}/agentes", params={"data_mode": "simulated"}, headers=AUTH).json()["agentes"]
    }

    assert real["trend_hunter"]["actividad"] == "sin_ejecuciones"
    assert sim["trend_hunter"]["actividad"] == "completada"


def test_agent_run_history_is_listed_newest_first(api: TestClient, session_factory) -> None:
    first = _agent_run(session_factory, "trend_hunter", finish="blocked", minutes=0)
    second = _agent_run(session_factory, "trend_hunter", finish="completed", minutes=5)

    body = api.get(f"{API_PREFIX}/agentes/trend_hunter/ejecuciones", params={"limite": 10}, headers=AUTH).json()

    assert body["agente"] == "trend_hunter"
    assert [r["id"] for r in body["ejecuciones"]] == [second, first]
    assert body["ejecuciones"][0]["resultado"] == {"n": 0}


def test_unknown_agent_is_404(api: TestClient) -> None:
    response = api.get(f"{API_PREFIX}/agentes/fantasma_x/ejecuciones", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_read_endpoints_never_write(api: TestClient, session_factory) -> None:
    _collection(session_factory)
    _agent_run(session_factory, "trend_hunter", finish="completed")
    before = _counts(session_factory)

    for _ in range(3):
        api.get(f"{API_PREFIX}/recolecciones", headers=AUTH)
        api.get(f"{API_PREFIX}/agentes", headers=AUTH)
        api.get(f"{API_PREFIX}/agentes/trend_hunter/ejecuciones", headers=AUTH)

    assert _counts(session_factory) == before


def test_invalid_schedule_configuration_is_a_structured_error(app: FastAPI, session_factory) -> None:
    bad = DetectarSettings(env="test", admin_token=TOKEN, agent_schedules={"fantasma": 60})
    app.dependency_overrides[get_settings] = lambda: bad
    app.dependency_overrides[get_session_factory] = lambda: session_factory

    with TestClient(app) as client:
        response = client.get(f"{API_PREFIX}/agentes", headers=AUTH)

    assert response.status_code == 500
    assert response.json()["code"] == "invalid_configuration"
    assert "fantasma" not in response.text
