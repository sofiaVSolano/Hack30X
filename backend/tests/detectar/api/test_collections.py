"""POST /api/detectar/recolecciones: autenticación, validación y registro. Sin red real."""

import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.detectar.api.dependencies import get_collection_service
from app.modules.detectar.api.errors import PROBLEM_MEDIA_TYPE
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.connectors.google_trends_rss import GTR_RSS_URL
from app.modules.detectar.ingestion.collection import CollectionService
from app.modules.detectar.storage.models import DataMode
from app.modules.detectar.storage.repository import DetectarRepository

URL = f"{API_PREFIX}/recolecciones"
TOKEN = "token-de-prueba-" + "x" * 24  # solo para pruebas; nunca un secreto real
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "google_trends_rss"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"fuentes": ["google_trends_rss"], "paises": ["MX"]}


def _transport(status: int = 200, name: str = "two_trends.xml") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GTR_RSS_URL)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    return httpx.MockTransport(handler)


def _configure(app: FastAPI, session_factory, *, token: str | None = TOKEN, status: int = 200) -> None:
    settings = DetectarSettings(env="test", admin_token=token, http_max_retries=0)
    service = CollectionService(session_factory, settings, http_transport=_transport(status))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_collection_service] = lambda: service


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    _configure(app, session_factory)
    with TestClient(app) as client:
        yield client


# --- Autenticación --------------------------------------------------------------


def test_missing_token_is_rejected(api: TestClient) -> None:
    response = api.post(URL, json=BODY)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize(
    "header",
    [
        f"Bearer {TOKEN}x",
        "Bearer otro-token-incorrecto-de-mas-de-32-caracteres",
        f"Basic {TOKEN}",
        TOKEN,
        "Bearer ",
    ],
)
def test_invalid_token_is_rejected(api: TestClient, header: str) -> None:
    response = api.post(URL, json=BODY, headers={"Authorization": header})

    assert response.status_code == 401


def test_endpoint_is_disabled_without_configured_token(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, token=None)

    with TestClient(app) as client:
        response = client.post(URL, json=BODY, headers=AUTH)

    assert response.status_code == 403
    assert response.json()["code"] == "collections_disabled"


def test_short_admin_token_is_rejected_by_configuration() -> None:
    with pytest.raises(ValueError):
        DetectarSettings(admin_token="corto")


def test_tokens_never_appear_in_responses_or_logs(
    api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    wrong = "token-equivocado-que-no-debe-filtrarse-123"
    caplog.set_level(logging.DEBUG)

    bad = api.post(URL, json=BODY, headers={"Authorization": f"Bearer {wrong}"})
    good = api.post(URL, json=BODY, headers=AUTH)

    assert bad.status_code == 401 and good.status_code == 201
    for text in (bad.text, good.text, caplog.text):
        assert TOKEN not in text
        assert wrong not in text


# --- Recolección válida -----------------------------------------------------------


def test_valid_request_runs_and_records_a_real_collection(api: TestClient, session_factory) -> None:
    response = api.post(URL, json=BODY, headers=AUTH)

    assert response.status_code == 201
    body = response.json()
    assert body["run_id"].startswith("run_")
    assert body["data_mode"] == "real"
    assert body["sincrono"] is True
    assert body["estado"] == "ok"
    assert body["paises"] == ["MX"]
    assert body["inicio"].endswith("Z") and body["fin"].endswith("Z")
    assert body["fuentes"] == [
        {
            "fuente": "google_trends_rss",
            "estado": "ok",
            "observaciones_nuevas": 3,
            "observaciones_repetidas": 0,
            "llamadas_http": 1,
            "error": None,
        }
    ]
    with session_factory() as session:
        repo = DetectarRepository(session)
        run = repo.get_collection_run(body["run_id"], data_mode=DataMode.REAL)
        assert run is not None and run.status.value == "ok"
        assert len(repo.list_observations(data_mode=DataMode.REAL)) == 3
        assert repo.list_observations(data_mode=DataMode.SIMULATED) == []


def test_default_countries_are_used_when_none_are_given(api: TestClient) -> None:
    response = api.post(URL, json={"fuentes": ["google_trends_rss"]}, headers=AUTH)

    assert response.status_code == 201
    assert response.json()["paises"] == ["CO", "MX", "AR", "CL", "PE", "EC", "VE", "US"]


def test_failed_source_is_reported_as_failed_not_success(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, status=503)

    with TestClient(app) as client:
        response = client.post(URL, json=BODY, headers=AUTH)

    assert response.status_code == 201  # la recolección existe; el estado dice qué pasó
    body = response.json()
    assert body["estado"] == "failed"
    assert body["fuentes"][0]["estado"] == "failed"
    assert body["fuentes"][0]["error"]["codigo"] == "upstream_unavailable"


# --- Validación ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"fuentes": ["google_trends_rss"], "paises": ["mx"]}, "validation_error"),
        ({"fuentes": ["google_trends_rss"], "paises": ["MEX"]}, "validation_error"),
        ({"fuentes": ["google_trends_rss"], "paises": ["MX", "MX"]}, "validation_error"),
        ({"fuentes": ["google_trends_rss"], "paises": []}, "validation_error"),
        ({"fuentes": ["google_trends_rss"], "paises": ["BR"]}, "country_not_allowed"),
        ({"fuentes": []}, "validation_error"),
        ({"fuentes": ["fuente_inventada"]}, "validation_error"),
        ({"fuentes": ["youtube"]}, "source_not_enabled"),
        ({"fuentes": ["x"]}, "source_not_enabled"),
        ({"fuentes": ["google_trends_rss"], "data_mode": "simulated"}, "validation_error"),
    ],
)
def test_invalid_requests_are_rejected(api: TestClient, session_factory, body, code) -> None:
    response = api.post(URL, json=body, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == code
    with session_factory() as session:
        assert DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL) == []


def test_country_limit_per_request(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory)
    limited = DetectarSettings(env="test", admin_token=TOKEN, max_countries_per_request=2)
    app.dependency_overrides[get_settings] = lambda: limited

    with TestClient(app) as client:
        response = client.post(
            URL, json={"fuentes": ["google_trends_rss"], "paises": ["MX", "CO", "AR"]}, headers=AUTH
        )

    assert response.status_code == 422
    assert response.json()["code"] == "too_many_countries"
