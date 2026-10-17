"""Integración en la app compartida (E12): app/main.py, ciclo de vida y configuración."""

import logging
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main
from app.modules.detectar.agents.registry import default_registry
from app.modules.detectar.agents.scheduler import AgentScheduler
from app.modules.detectar.api import dependencies
from app.modules.detectar.api.router import router as detectar_router
from app.modules.detectar.config import DetectarSettings, get_settings

from ..agents.test_tasks import coordinator

BACKEND = Path(__file__).resolve().parents[3]
TOKEN = "token-de-prueba-" + "i" * 24  # solo para pruebas
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)


@pytest.fixture
def fresh_caches() -> Iterator[None]:
    """Limpia las instancias únicas por proceso antes y después de cada prueba."""
    caches = [
        dependencies._default_session_factory,
        dependencies._default_collection_service,
        dependencies._default_agent_coordinator,
        dependencies._default_agent_scheduler,
        get_settings,
    ]
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


def _scheduler(session_factory, cfg: DetectarSettings) -> AgentScheduler:
    return AgentScheduler(coordinator(session_factory, clock=lambda: NOW), session_factory, default_registry(), cfg, clock=lambda: NOW)


# --- aplicación y rutas ---------------------------------------------------------------------


def test_importing_main_has_no_side_effects(tmp_path: Path) -> None:
    """En un proceso aparte: importar la app no crea la base ni el programador."""
    db = tmp_path / "no_debe_crearse.db"
    code = (
        "import app.main as m; "
        "from app.modules.detectar.api import dependencies as d; "
        "assert m.app.state.detectar_scheduler is None; "
        "assert d._default_agent_scheduler.cache_info().currsize == 0; "
        "assert d._default_agent_coordinator.cache_info().currsize == 0; "
        "assert d._default_session_factory.cache_info().currsize == 0; "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=BACKEND,
        env={"DETECTAR_DB_PATH": str(db), "PYTHONDONTWRITEBYTECODE": "1", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert not db.exists()


def test_detectar_routes_are_mounted_once_under_the_prefix() -> None:
    paths = list(main.app.openapi()["paths"])

    assert paths and all(p.startswith("/api/detectar/") for p in paths)
    assert not any(p.startswith("/api/detectar/api/detectar") for p in paths)
    assert "/api/detectar/health" in paths
    reference = FastAPI()
    reference.include_router(detectar_router, prefix="/api/detectar")
    assert paths == list(reference.openapi()["paths"])  # mismas rutas, sin copias ni extras


def test_health_keeps_its_contract_through_the_shared_app() -> None:
    with TestClient(main.create_app()) as client:
        body = client.get("/api/detectar/health").json()

    assert (body["status"], body["module"]) == ("ok", "detectar")
    assert body["checks"]["database"]["status"] == "not_checked"
    assert body["time"].endswith("Z")


def test_protected_routes_keep_authentication(fresh_caches, monkeypatch) -> None:
    monkeypatch.setenv("DETECTAR_ADMIN_TOKEN", TOKEN)
    app = main.create_app()

    with TestClient(app) as client:
        missing = client.get("/api/detectar/agentes")
        wrong = client.post("/api/detectar/recolecciones", json={"fuentes": ["google_trends_rss"]}, headers={"Authorization": "Bearer " + "w" * 40})

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "unauthorized"


def test_read_endpoints_work_through_the_shared_app(fresh_caches, monkeypatch, session_factory) -> None:
    app = main.create_app()
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    app.dependency_overrides[dependencies.get_session_factory] = lambda: session_factory

    with TestClient(app) as client:
        response = client.get("/api/detectar/agentes", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert {a["id"] for a in response.json()["agentes"]} >= {"trend_hunter", "supervisor"}


# --- errores RFC 9457 -----------------------------------------------------------------------


def test_validation_errors_are_problem_json_without_echoing_input(fresh_caches, session_factory) -> None:
    app = main.create_app()
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    # FastAPI resuelve las dependencias antes de responder 422: nunca la base por defecto.
    app.dependency_overrides[dependencies.get_session_factory] = lambda: session_factory

    with TestClient(app) as client:
        response = client.get(
            "/api/detectar/recolecciones", params={"limite": "SECRETO-123"}, headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_error"
    assert "SECRETO-123" not in response.text


class _ExplodingCoordinator:
    async def start(self, *args: Any, **kwargs: Any):
        raise RuntimeError("traza interna con token=VALOR-SECRETO")


def test_unexpected_errors_are_500_problem_json_without_internals(fresh_caches) -> None:
    app = main.create_app()
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    app.dependency_overrides[dependencies.get_agent_coordinator] = lambda: _ExplodingCoordinator()

    with TestClient(app) as client:
        response = client.post(
            "/api/detectar/agentes/supervisor/ejecuciones", json={"data_mode": "real"}, headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "VALOR-SECRETO" not in response.text and "Traceback" not in response.text


# --- ciclo de vida --------------------------------------------------------------------------


def test_lifespan_with_scheduler_disabled(fresh_caches, monkeypatch) -> None:
    monkeypatch.setattr(dependencies, "get_agent_scheduler", lambda: pytest.fail("no debía crearse"))
    app = main.create_app()

    with TestClient(app):
        assert app.state.detectar_scheduler is None


def test_lifespan_starts_and_stops_the_enabled_scheduler(fresh_caches, monkeypatch, session_factory) -> None:
    cfg = DetectarSettings(scheduler_enabled=True, scheduler_tick_seconds=3600)
    sched = _scheduler(session_factory, cfg)
    monkeypatch.setattr(dependencies, "get_settings", lambda: cfg)
    monkeypatch.setattr(dependencies, "get_agent_scheduler", lambda: sched)
    app = main.create_app()

    with TestClient(app):
        assert app.state.detectar_scheduler is sched
        assert sched.running is True

    assert sched.running is False  # sin tareas del programador tras el apagado


def test_scheduler_and_api_share_one_coordinator(fresh_caches, monkeypatch, session_factory) -> None:
    monkeypatch.setattr(dependencies, "get_session_factory", lambda: session_factory)

    scheduler = dependencies.get_agent_scheduler()

    assert scheduler._coordinator is dependencies.get_agent_coordinator()
    assert dependencies.get_agent_scheduler() is scheduler  # una instancia por proceso


def test_startup_error_aborts_the_app_and_leaves_nothing_running(fresh_caches, monkeypatch, caplog) -> None:
    monkeypatch.setattr(dependencies, "get_settings", lambda: DetectarSettings(scheduler_enabled=True))

    def broken():
        raise ValueError("Frecuencia de 'trend_hunter' fuera de rango")

    monkeypatch.setattr(dependencies, "get_agent_scheduler", broken)
    app = main.create_app()

    with pytest.raises(ValueError), TestClient(app):
        pass
    assert "No se pudo iniciar el programador de DETECTAR: ValueError" in caplog.text
    assert app.state.detectar_scheduler is None


def test_shutdown_error_is_reported(fresh_caches, monkeypatch, session_factory, caplog) -> None:
    cfg = DetectarSettings(scheduler_enabled=True, scheduler_tick_seconds=3600)
    sched = _scheduler(session_factory, cfg)
    original_stop = sched.stop

    async def failing_stop(timeout: float = 30.0) -> None:
        await original_stop(timeout)
        raise RuntimeError("fallo al detener")

    sched.stop = failing_stop  # type: ignore[method-assign]
    monkeypatch.setattr(dependencies, "get_settings", lambda: cfg)
    monkeypatch.setattr(dependencies, "get_agent_scheduler", lambda: sched)
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError), TestClient(main.create_app()):
        pass
    assert "Error al detener el programador de DETECTAR: RuntimeError" in caplog.text
    assert sched.running is False


# --- configuración y dependencias -----------------------------------------------------------


def test_default_configuration_keeps_the_scheduler_off(monkeypatch) -> None:
    for name in ("DETECTAR_SCHEDULER_ENABLED", "DETECTAR_AGENT_SCHEDULES"):
        monkeypatch.delenv(name, raising=False)

    assert DetectarSettings().scheduler_enabled is False


def test_valid_scheduler_configuration_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DETECTAR_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DETECTAR_AGENT_SCHEDULES", '{"supervisor": 60}')
    monkeypatch.setenv("DETECTAR_SCHEDULER_AGENT_MODES", '{"supervisor": "simulated"}')

    cfg = DetectarSettings()

    assert (cfg.scheduler_enabled, cfg.agent_schedules, cfg.scheduler_agent_modes) == (
        True, {"supervisor": 60}, {"supervisor": "simulated"},
    )


def test_declared_dependencies_match_the_installed_ones() -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    declared = [*project["project"]["dependencies"], *project["dependency-groups"]["dev"]]

    assert declared, "pyproject.toml debe declarar dependencias"
    for requirement in declared:
        name, pinned = requirement.split("==")
        assert version(name) == pinned, f"{name}: instalado {version(name)} != declarado {pinned}"


def test_pytest_configuration_is_declared() -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["tool"]["pytest"]["ini_options"]["pythonpath"] == ["."]
    assert project["project"]["requires-python"] == ">=3.12"
