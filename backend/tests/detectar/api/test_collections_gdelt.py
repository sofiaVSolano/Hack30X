"""POST /recolecciones con GDELT: validación y registro. Sin red real."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.detectar.api.dependencies import (
    get_collection_service,
    get_session_factory,
)
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.connectors.gdelt import GDELT_DOC_URL
from app.modules.detectar.ingestion.collection import CollectionService
from app.modules.detectar.storage.models import DataMode, Source
from app.modules.detectar.storage.repository import DetectarRepository

URL = f"{API_PREFIX}/recolecciones"
TOKEN = "token-de-prueba-" + "g" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GDELT_DOC_URL)
        return httpx.Response(
            200,
            json={"timeline": [{"series": "Article Count", "data": [
                {"date": f"{YESTERDAY:%Y%m%d}T000000Z", "value": 3, "norm": 500}
            ]}]},
        )

    return httpx.MockTransport(handler)


def _configure(app: FastAPI, session_factory, *, enabled: bool = True) -> None:
    settings = DetectarSettings(
        env="test",
        admin_token=TOKEN,
        http_max_retries=0,
        gdelt_mode="on" if enabled else "off",
        gdelt_min_interval_seconds=1,
        gdelt_max_requests=4,
    )
    service = CollectionService(session_factory, settings, http_transport=_transport())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_collection_service] = lambda: service
    app.dependency_overrides[get_session_factory] = lambda: session_factory


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    _configure(app, session_factory)
    with TestClient(app) as client:
        yield client


def _body(**overrides) -> dict:
    gdelt = {
        "terminos": ["inteligencia artificial"],
        "desde": (YESTERDAY - timedelta(days=9)).isoformat(),
        "hasta": YESTERDAY.isoformat(),
        "idioma_fuente": "spanish",
        "paises_medios": ["MX"],
    } | overrides
    return {"fuentes": ["gdelt"], "gdelt": gdelt}


def test_valid_gdelt_collection_is_recorded(api: TestClient, session_factory) -> None:
    response = api.post(URL, json=_body(), headers=AUTH)

    assert response.status_code == 201
    created = response.json()
    assert created["estado"] == "ok"
    assert created["fuentes"][0]["fuente"] == "gdelt"
    assert created["fuentes"][0]["observaciones_nuevas"] == 1
    detail = api.get(f"{URL}/{created['run_id']}", headers=AUTH).json()
    assert detail["parametros"]["gdelt"]["source_countries"] == ["MX"]
    with session_factory() as session:
        (obs,) = DetectarRepository(session).list_observations(data_mode=DataMode.REAL)
        assert obs.source is Source.GDELT
        assert obs.country == "MX"
        assert obs.country_basis.value == "publisher_country"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"fuentes": ["gdelt"]}, "missing_parameters"),
        ({"fuentes": ["google_trends_rss"], "gdelt": _body()["gdelt"]}, "parameters_not_applicable"),
        (_body(hasta=datetime.now(UTC).date().isoformat()), "invalid_interval"),
        (
            _body(
                desde=(YESTERDAY - timedelta(days=120)).isoformat(),
                hasta=(YESTERDAY - timedelta(days=100)).isoformat(),
            ),
            "invalid_interval",
        ),
        (_body(terminos=["Uno", "Dos", "Tres"], paises_medios=["MX", "CO"]), "too_many_requests_needed"),
        (_body(terminos=["x sourcecountry:mexico"]), "validation_error"),
        (_body(desde=(YESTERDAY - timedelta(days=3)).isoformat()), "validation_error"),
        (_body(paises_medios=["BR"]), "validation_error"),
        (_body(idioma_fuente="klingon"), "validation_error"),
    ],
)
def test_invalid_gdelt_requests_are_rejected(api: TestClient, session_factory, body, code) -> None:
    response = api.post(URL, json=body, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == code
    with session_factory() as session:
        assert DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL) == []


def test_gdelt_must_be_enabled_explicitly(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, enabled=False)

    with TestClient(app) as client:
        response = client.post(URL, json=_body(), headers=AUTH)

    assert response.status_code == 422
    assert "DETECTAR_GDELT_MODE" in response.json()["detail"]
