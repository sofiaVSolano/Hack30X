"""GET /api/detectar/recolecciones/{run_id} y POST con Wikimedia. Sin red real."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.detectar.api.dependencies import (
    get_collection_service,
    get_session_factory,
)
from app.modules.detectar.api.errors import PROBLEM_MEDIA_TYPE
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.connectors.google_trends_rss import GTR_RSS_URL
from app.modules.detectar.connectors.wikimedia import PAGEVIEWS_BASE_URL
from app.modules.detectar.ingestion.collection import CollectionService
from app.modules.detectar.storage.models import CollectionTrigger, DataMode, Source
from app.modules.detectar.storage.repository import DetectarRepository

URL = f"{API_PREFIX}/recolecciones"
TOKEN = "token-de-prueba-" + "y" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "google_trends_rss"
YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


def _transport(*, trends_status: int = 200, wiki_status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(GTR_RSS_URL):
            if trends_status != 200:
                return httpx.Response(trends_status)
            return httpx.Response(200, content=(FIXTURES / "two_trends.xml").read_bytes())
        if url.startswith(PAGEVIEWS_BASE_URL):
            if wiki_status != 200:
                return httpx.Response(wiki_status)
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "project": "es.wikipedia.org",
                            "article": "Tema_de_prueba",
                            "granularity": "daily",
                            "timestamp": f"{YESTERDAY:%Y%m%d}00",
                            "access": "all-access",
                            "agent": "user",
                            "views": 42,
                        }
                    ]
                },
            )
        raise AssertionError(f"URL inesperada: {url}")

    return httpx.MockTransport(handler)


def _configure(app: FastAPI, session_factory, *, wikimedia: bool = True, **status) -> None:
    settings = DetectarSettings(
        env="test",
        admin_token=TOKEN,
        http_max_retries=0,
        wikimedia_mode="on" if wikimedia else "off",
        http_contact="equipo@hack30x.example",
    )
    service = CollectionService(session_factory, settings, http_transport=_transport(**status))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_collection_service] = lambda: service
    app.dependency_overrides[get_session_factory] = lambda: session_factory


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    _configure(app, session_factory)
    with TestClient(app) as client:
        yield client


def _wiki_body(**overrides) -> dict:
    wikimedia = {
        "articulos": ["Tema de prueba"],
        "desde": YESTERDAY.isoformat(),
        "hasta": YESTERDAY.isoformat(),
    } | overrides
    return {"fuentes": ["wikimedia"], "wikimedia": wikimedia}


# --- GET: autenticación y 404 --------------------------------------------------------


def test_get_requires_token(api: TestClient) -> None:
    run_id = api.post(URL, json={"fuentes": ["google_trends_rss"], "paises": ["MX"]}, headers=AUTH).json()["run_id"]

    missing = api.get(f"{URL}/{run_id}")
    wrong = api.get(f"{URL}/{run_id}", headers={"Authorization": "Bearer " + "z" * 40})
    unknown = api.get(f"{URL}/run_{'0' * 32}")

    assert missing.status_code == wrong.status_code == unknown.status_code == 401
    assert missing.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    # Sin token no se revela si la recolección existe ni nada de su contenido.
    assert missing.json()["code"] == unknown.json()["code"] == "unauthorized"
    assert missing.json()["detail"] == unknown.json()["detail"]
    assert "google_trends_rss" not in missing.text and "estado" not in missing.text


def test_unknown_run_is_404(api: TestClient) -> None:
    response = api.get(f"{URL}/run_{'0' * 32}", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("bad_id", ["123", "run_ABC", "run_" + "0" * 31, "../collection_runs"])
def test_malformed_run_id_is_rejected(api: TestClient, bad_id: str) -> None:
    response = api.get(f"{URL}/{bad_id}", headers=AUTH)

    assert response.status_code in (404, 422)
    assert TOKEN not in response.text


# --- GET: contenido registrado ---------------------------------------------------------


def test_get_returns_what_was_recorded_for_a_successful_run(api: TestClient) -> None:
    created = api.post(
        URL, json={"fuentes": ["google_trends_rss"], "paises": ["MX"]}, headers=AUTH
    ).json()

    response = api.get(f"{URL}/{created['run_id']}", headers=AUTH)

    assert response.status_code == 200
    detail = response.json()
    assert detail["run_id"] == created["run_id"]
    assert detail["data_mode"] == "real"
    assert detail["estado"] == "ok"
    assert detail["inicio"] == created["inicio"] and detail["fin"] == created["fin"]
    assert detail["fuentes_solicitadas"] == ["google_trends_rss"]
    assert detail["paises"] == ["MX"]
    assert detail["parametros"] == {"paises": ["MX"], "wikimedia": None, "gdelt": None}
    (source,) = detail["fuentes"]
    assert source["fuente"] == "google_trends_rss"
    assert source["estado"] == "ok"
    assert source["observaciones_nuevas"] == 3
    assert source["llamadas_http"] == 1
    assert source["error"] is None
    # No se reconstruyen datos que no se guardaron.
    assert "observaciones_repetidas" not in source


def test_get_reports_failed_runs(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, trends_status=503)
    with TestClient(app) as client:
        run_id = client.post(
            URL, json={"fuentes": ["google_trends_rss"], "paises": ["MX"]}, headers=AUTH
        ).json()["run_id"]
        detail = client.get(f"{URL}/{run_id}", headers=AUTH).json()

    assert detail["estado"] == "failed"
    assert detail["fuentes"][0]["error"]["codigo"] == "upstream_unavailable"


def test_get_reports_partial_runs_and_keeps_valid_observations(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, wiki_status=503)
    body = _wiki_body() | {"fuentes": ["google_trends_rss", "wikimedia"], "paises": ["MX"]}
    with TestClient(app) as client:
        created = client.post(URL, json=body, headers=AUTH).json()
        detail = client.get(f"{URL}/{created['run_id']}", headers=AUTH).json()

    assert created["estado"] == detail["estado"] == "partial"
    by_source = {s["fuente"]: s for s in detail["fuentes"]}
    assert by_source["google_trends_rss"]["estado"] == "ok"
    assert by_source["wikimedia"]["estado"] == "failed"
    with session_factory() as session:
        stored = DetectarRepository(session).list_observations(data_mode=DataMode.REAL)
        assert {o.source for o in stored} == {Source.GOOGLE_TRENDS_RSS}


def test_get_does_not_mix_data_modes(api: TestClient, session_factory) -> None:
    with session_factory() as session, session.begin():
        simulated = DetectarRepository(session).create_collection_run(
            data_mode=DataMode.SIMULATED,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[],
            requested_countries=[],
            created_at=datetime(2026, 10, 16, tzinfo=UTC),
        )

    as_real = api.get(f"{URL}/{simulated.id}", headers=AUTH)
    as_simulated = api.get(f"{URL}/{simulated.id}", params={"data_mode": "simulated"}, headers=AUTH)

    assert as_real.status_code == 404
    assert as_simulated.status_code == 200
    assert as_simulated.json()["data_mode"] == "simulated"
    assert api.get(f"{URL}/{simulated.id}", params={"data_mode": "todos"}, headers=AUTH).status_code == 422


def test_get_is_read_only(api: TestClient, session_factory) -> None:
    run_id = api.post(URL, json={"fuentes": ["google_trends_rss"], "paises": ["MX"]}, headers=AUTH).json()["run_id"]
    with session_factory() as session:
        before = len(DetectarRepository(session).list_observations(data_mode=DataMode.REAL))

    for _ in range(3):
        api.get(f"{URL}/{run_id}", headers=AUTH)

    with session_factory() as session:
        repo = DetectarRepository(session)
        assert len(repo.list_observations(data_mode=DataMode.REAL)) == before
        assert len(repo.list_collection_runs(data_mode=DataMode.REAL)) == 1


# --- POST con Wikimedia ------------------------------------------------------------------


def test_wikimedia_collection_records_interval_and_observations(api: TestClient, session_factory) -> None:
    response = api.post(URL, json=_wiki_body(), headers=AUTH)

    assert response.status_code == 201
    created = response.json()
    assert created["estado"] == "ok"
    assert created["paises"] == []
    detail = api.get(f"{URL}/{created['run_id']}", headers=AUTH).json()
    assert detail["parametros"]["wikimedia"] == {
        "articles": ["Tema_de_prueba"],
        "start": YESTERDAY.isoformat(),
        "end": YESTERDAY.isoformat(),
        "projects": [],
    }
    with session_factory() as session:
        (obs,) = DetectarRepository(session).list_observations(data_mode=DataMode.REAL)
        assert obs.source is Source.WIKIMEDIA
        assert obs.value == 42.0
        assert obs.country is None
        assert obs.period_start.date() == YESTERDAY


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"fuentes": ["wikimedia"]}, "missing_parameters"),
        (
            {"fuentes": ["google_trends_rss"], "wikimedia": _wiki_body()["wikimedia"]},
            "parameters_not_applicable",
        ),
        (_wiki_body() | {"paises": ["MX"]}, "parameters_not_applicable"),
        (_wiki_body(hasta=datetime.now(UTC).date().isoformat()), "invalid_interval"),
        (_wiki_body(desde=(YESTERDAY - timedelta(days=200)).isoformat()), "invalid_interval"),
        (_wiki_body(proyectos=["en.wikipedia.org"]), "project_not_allowed"),
        (_wiki_body(articulos=[f"Tema {i}" for i in range(21)]), "too_many_articles"),
        (_wiki_body(articulos=["Tema|malo"]), "validation_error"),
        (_wiki_body(desde="2026-13-01"), "validation_error"),
        (_wiki_body(proyectos=["evil.example.com"]), "validation_error"),
        (_wiki_body(extra=True), "validation_error"),
    ],
)
def test_invalid_wikimedia_requests_are_rejected(api: TestClient, session_factory, body, code) -> None:
    response = api.post(URL, json=body, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == code
    with session_factory() as session:
        assert DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL) == []


def test_wikimedia_must_be_enabled_explicitly(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory, wikimedia=False)

    with TestClient(app) as client:
        response = client.post(URL, json=_wiki_body(), headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == "source_not_enabled"
    assert "DETECTAR_WIKIMEDIA_MODE" in response.json()["detail"]


def test_wikimedia_requires_contact(app: FastAPI, session_factory) -> None:
    _configure(app, session_factory)
    no_contact = DetectarSettings(env="test", admin_token=TOKEN, wikimedia_mode="on")
    app.dependency_overrides[get_settings] = lambda: no_contact

    with TestClient(app) as client:
        response = client.post(URL, json=_wiki_body(), headers=AUTH)

    assert response.status_code == 422
    assert "DETECTAR_HTTP_CONTACT" in response.json()["detail"]


def test_wikimedia_is_off_by_default() -> None:
    assert DetectarSettings().wikimedia_mode == "off"
    assert DetectarSettings().wikimedia_projects == ("es.wikipedia.org",)


def test_dates_are_iso(api: TestClient) -> None:
    detail = api.get(
        f"{URL}/{api.post(URL, json=_wiki_body(), headers=AUTH).json()['run_id']}", headers=AUTH
    ).json()

    for key in ("creado", "inicio", "fin"):
        assert detail[key].endswith("Z")
        datetime.fromisoformat(detail[key])
    assert date.fromisoformat(detail["parametros"]["wikimedia"]["start"]) == YESTERDAY
