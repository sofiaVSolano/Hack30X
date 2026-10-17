"""API de clasificación (E9): autenticación, cálculo explícito, filtros y lecturas sin efectos."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.stages.rules import RULES_VERSION
from app.modules.detectar.storage.models import DataMode, TrendClassification
from app.modules.detectar.topics.linker import TopicLinker

from ..metrics.test_service import gdelt_series, wiki_series

TOKEN = "token-de-prueba-" + "c" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = f"{API_PREFIX}/clasificaciones"
AS_OF = datetime.now(UTC).date() - timedelta(days=1)
START = AS_OF - timedelta(days=20)


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def _seed(session_factory, mode: DataMode = DataMode.REAL) -> None:
    with session_factory() as session, session.begin():
        wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7, mode=mode)
        if mode is DataMode.REAL:
            gdelt_series(session, "solo prensa", START, [1] * 7 + [3] * 7 + [10] * 7)
        TopicLinker(session).process(data_mode=mode)
        MetricsService(session).compute(data_mode=mode, as_of=AS_OF)


def _classify(api: TestClient, mode: str = "real"):
    return api.post(f"{BASE}/calculos", json={"data_mode": mode, "fecha_referencia": AS_OF.isoformat()}, headers=AUTH)


def _count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(TrendClassification))


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/clasificaciones"), ("get", "/clasificaciones/reglas"), ("post", "/clasificaciones/calculos")],
)
def test_routes_require_admin_token(api: TestClient, method: str, path: str) -> None:
    response = getattr(api, method)(API_PREFIX + path, headers={"Authorization": "Bearer " + "z" * 40})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_rules_endpoint_declares_provisional_uncalibrated_rules(api: TestClient) -> None:
    body = api.get(f"{BASE}/reglas", headers=AUTH).json()

    assert (body["version"], body["version_metricas"]) == (RULES_VERSION, "metrics-v1")
    assert body["provisional"] is True and body["calibrado"] is False
    assert body["parametros"]["growth_min"] == 0.2
    assert len(body["parametros_sha256"]) == 64
    assert body["registrada"] is False  # aún no se ejecutó ninguna clasificación
    assert body["capacidades_por_fuente"]["google_trends_rss"] == ["emergente"]
    assert "NO la asigna" in body["etapas"]["saturada"]


def test_classification_is_explicit_idempotent_and_readable(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    first = _classify(api).json()
    second = _classify(api).json()

    assert first["version"] == RULES_VERSION
    assert first["creadas"] == 2
    assert first["por_etapa"] == {"acelerando": 1, "datos_insuficientes": 1}
    assert (second["creadas"], second["sin_cambios"]) == (0, 2)
    assert _count(session_factory) == 2
    assert api.get(f"{BASE}/reglas", headers=AUTH).json()["registrada"] is True

    page = api.get(BASE, params={"etapa": "acelerando"}, headers=AUTH).json()
    (item,) = page["items"]
    assert item["calibrado"] is False
    assert item["fecha_referencia"] == AS_OF.isoformat()
    wiki = next(e for e in item["evidencia"] if e["fuente"] == "wikimedia")
    assert (wiki["rol"], wiki["etapa_propuesta"], wiki["fuente_validada"]) == ("primary", "acelerando", True)
    assert item["explicacion"]["provisional"] is True


def test_filter_by_evidence_source(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _classify(api)

    by_gdelt = api.get(BASE, params={"fuente": "gdelt"}, headers=AUTH).json()["items"]
    by_wiki = api.get(BASE, params={"fuente": "wikimedia"}, headers=AUTH).json()["items"]

    assert [i["etapa"] for i in by_gdelt] == ["datos_insuficientes"]
    assert by_gdelt[0]["motivo"] == "solo_fuente_no_validada"
    assert [i["etapa"] for i in by_wiki] == ["acelerando"]
    assert api.get(BASE, params={"fuente": "google_trends_rss"}, headers=AUTH).json()["total"] == 0


def test_filters_by_version_date_and_topic(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _classify(api)
    topic_id = api.get(BASE, params={"etapa": "acelerando"}, headers=AUTH).json()["items"][0]["tema_id"]

    assert api.get(BASE, params={"version": RULES_VERSION}, headers=AUTH).json()["total"] == 2
    assert api.get(BASE, params={"version": "stages-v9"}, headers=AUTH).json()["total"] == 0
    assert api.get(BASE, params={"tema_id": topic_id}, headers=AUTH).json()["total"] == 1
    other = (AS_OF - timedelta(days=1)).isoformat()
    assert api.get(BASE, params={"fecha_referencia": other}, headers=AUTH).json()["total"] == 0


def test_reads_never_classify(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    api.get(BASE, headers=AUTH)
    api.get(f"{BASE}/reglas", headers=AUTH)

    assert _count(session_factory) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"fecha_referencia": "2026-10-01"},
        {"data_mode": "real"},
        {"data_mode": "ambos", "fecha_referencia": "2026-10-01"},
        {"data_mode": "real", "fecha_referencia": "2026-10-01", "temas": ["x"]},
        {"data_mode": "real", "fecha_referencia": "2026-10-01", "etapa": "saturada"},
    ],
)
def test_invalid_requests(api: TestClient, body: dict) -> None:
    assert api.post(f"{BASE}/calculos", json=body, headers=AUTH).status_code == 422


def test_reference_date_must_be_closed(api: TestClient) -> None:
    today = datetime.now(UTC).date().isoformat()

    response = api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": today}, headers=AUTH)

    assert response.json()["code"] == "invalid_reference_date"


@pytest.mark.parametrize("params", [{"etapa": "viral"}, {"data_mode": "todos"}, {"limite": 0}, {"tema_id": "x"}])
def test_invalid_filters(api: TestClient, params: dict) -> None:
    assert api.get(BASE, params=params, headers=AUTH).status_code == 422


def test_modes_are_isolated(api: TestClient, session_factory) -> None:
    _seed(session_factory, DataMode.SIMULATED)
    _classify(api, "simulated")

    assert api.get(BASE, headers=AUTH).json()["total"] == 0
    sim = api.get(BASE, params={"data_mode": "simulated"}, headers=AUTH).json()
    assert sim["total"] == 1 and sim["items"][0]["data_mode"] == "simulated"


def test_token_does_not_leak(api: TestClient, session_factory, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _seed(session_factory)

    texts = [_classify(api).text, api.get(BASE, headers=AUTH).text, caplog.text]

    assert all(TOKEN not in t for t in texts)
