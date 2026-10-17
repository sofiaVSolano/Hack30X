from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.modules.detectar import __version__
from app.modules.detectar.api.errors import (
    PROBLEM_MEDIA_TYPE,
    DetectarError,
    FieldError,
)
from app.modules.detectar.api.router import API_PREFIX, format_utc, get_clock
from app.modules.detectar.config import DetectarSettings, get_settings

HEALTH_URL = f"{API_PREFIX}/health"


# --- /health ---------------------------------------------------------------


def test_health_returns_module_status(client: TestClient) -> None:
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "module": "detectar",
        "version": __version__,
        "rules_version": "v1",
        "time": "2026-10-16T22:00:00Z",
        "checks": {
            "database": {
                "status": "not_checked",
                "detail": "Esta versión de /health no comprueba la base de datos.",
            },
            "rules": {
                "status": "not_loaded",
                "detail": "El archivo de reglas versionadas se implementa en E8.",
            },
        },
    }


def test_health_does_not_claim_database_or_rules_are_operational(client: TestClient) -> None:
    checks = client.get(HEALTH_URL).json()["checks"]

    assert checks["database"]["status"] != "ok"
    assert checks["rules"]["status"] != "ok"


def test_health_reports_configured_rules_version(app: FastAPI) -> None:
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", rules_version="v2")

    with TestClient(app) as client:
        assert client.get(HEALTH_URL).json()["rules_version"] == "v2"


def test_health_time_is_converted_to_utc(app: FastAPI) -> None:
    bogota = timezone(timedelta(hours=-5))
    app.dependency_overrides[get_clock] = lambda: (lambda: datetime(2026, 10, 16, 17, 0, tzinfo=bogota))

    with TestClient(app) as client:
        assert client.get(HEALTH_URL).json()["time"] == "2026-10-16T22:00:00Z"


def test_format_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        format_utc(datetime(2026, 10, 16, 22, 0))


# --- Configuración -----------------------------------------------------------


def test_settings_read_detectar_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETECTAR_ENV", "staging")
    monkeypatch.setenv("DETECTAR_RULES_VERSION", "v3")

    settings = DetectarSettings()

    assert settings.env == "staging"
    assert settings.rules_version == "v3"


def test_settings_ignore_variables_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RULES_VERSION", "v9")

    assert DetectarSettings().rules_version == "v1"


@pytest.mark.parametrize(
    ("name", "value"),
    [("DETECTAR_ENV", "produccion"), ("DETECTAR_RULES_VERSION", "uno")],
)
def test_settings_reject_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        DetectarSettings()


# --- Errores RFC 9457 --------------------------------------------------------


def _add_probe_routes(app: FastAPI) -> None:
    probe = APIRouter()

    @probe.get(f"{API_PREFIX}/_probe/error")
    def raise_domain_error() -> None:
        raise DetectarError(
            code="not_found",
            status=404,
            title="Recurso no encontrado",
            detail="El tema solicitado no existe.",
            errors=[FieldError(campo="topic_id", mensaje="no existe")],
        )

    @probe.get(f"{API_PREFIX}/_probe/validacion")
    def detectar_validation(limite: int) -> dict[str, int]:
        return {"limite": limite}

    @probe.get("/otro-modulo/validacion")
    def other_module_validation(limite: int) -> dict[str, int]:
        return {"limite": limite}

    app.include_router(probe)


def test_domain_error_is_problem_json(app: FastAPI) -> None:
    _add_probe_routes(app)

    with TestClient(app) as client:
        response = client.get(f"{API_PREFIX}/_probe/error")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json() == {
        "type": "urn:hack30x:detectar:error:not_found",
        "title": "Recurso no encontrado",
        "status": 404,
        "code": "not_found",
        "detail": "El tema solicitado no existe.",
        "instance": f"{API_PREFIX}/_probe/error",
        "errors": [{"campo": "topic_id", "mensaje": "no existe"}],
    }


def test_validation_error_under_detectar_prefix_is_problem_json(app: FastAPI) -> None:
    _add_probe_routes(app)

    with TestClient(app) as client:
        response = client.get(f"{API_PREFIX}/_probe/validacion", params={"limite": "secreto-123"})

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert body["code"] == "validation_error"
    assert body["errors"][0]["campo"] == "query.limite"
    # El valor recibido no se refleja en la respuesta.
    assert "secreto-123" not in response.text


def test_validation_error_outside_prefix_keeps_fastapi_default(app: FastAPI) -> None:
    _add_probe_routes(app)

    with TestClient(app) as client:
        response = client.get("/otro-modulo/validacion", params={"limite": "x"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()
    assert "code" not in response.json()


# --- Red bloqueada -----------------------------------------------------------


def test_real_network_calls_are_blocked(block_network: list[str]) -> None:
    # Se compara por mensaje: conftest se importa como módulo de pytest, no por ruta de paquete.
    with pytest.raises(RuntimeError, match="Conexión de red bloqueada"):
        httpx.get("https://example.org", timeout=1)

    assert block_network == ["example.org"]
    # Se limpia para que la verificación final del fixture no marque esta prueba como fallida.
    block_network.clear()
