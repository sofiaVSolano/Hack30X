"""API de métricas (E8): autenticación, cálculo explícito y lecturas sin efectos."""

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
from app.modules.detectar.metrics.definitions import DEFINITIONS, RULES_VERSION
from app.modules.detectar.storage.models import DataMode, MetricValue
from app.modules.detectar.topics.linker import TopicLinker

from ..metrics.test_service import wiki_series

TOKEN = "token-de-prueba-" + "m" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = f"{API_PREFIX}/metricas"
AS_OF = datetime.now(UTC).date() - timedelta(days=1)


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def _seed(session_factory, mode: DataMode = DataMode.REAL) -> None:
    with session_factory() as session, session.begin():
        wiki_series(session, "Tema", AS_OF - timedelta(days=13), [10] * 7 + [20] * 7, mode=mode)
        TopicLinker(session).process(data_mode=mode)


def _count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(MetricValue))


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/metricas"), ("get", "/metricas/definiciones"), ("post", "/metricas/calculos")],
)
def test_routes_require_admin_token(api: TestClient, method: str, path: str) -> None:
    response = getattr(api, method)(API_PREFIX + path, headers={"Authorization": "Bearer " + "q" * 40})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_definitions_document_every_metric(api: TestClient) -> None:
    body = api.get(f"{BASE}/definiciones", headers=AUTH).json()

    assert body["version"] == RULES_VERSION
    assert body["parametros"]["window_days"] == 7
    assert [m["key"] for m in body["metricas"]] == [d.key for d in DEFINITIONS]
    for metric in body["metricas"]:
        for field in ("source", "unit", "formula", "required_data", "min_period", "insufficient_when", "limitations"):
            assert metric[field]


def test_calculation_is_explicit_idempotent_and_readable(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    first = api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": AS_OF.isoformat()}, headers=AUTH)
    second = api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": AS_OF.isoformat()}, headers=AUTH)

    assert first.status_code == 200
    report = first.json()
    assert report["version"] == RULES_VERSION
    assert report["valores_escritos"] == 5
    assert report["por_estado"] == {"ok": 4, "insufficient": 1}  # aceleración: falta 3.ª ventana
    assert second.json()["valores_escritos"] == 5
    assert _count(session_factory) == 5

    page = api.get(BASE, params={"metrica": "wiki_views_growth"}, headers=AUTH).json()
    (growth,) = page["items"]
    assert growth["valor"] == pytest.approx(1.0)
    assert growth["unidad"] == "growth_rate"
    assert growth["ambito"] == "es.wikipedia.org:Tema"
    assert growth["fecha_referencia"] == AS_OF.isoformat()
    assert growth["fuente_validada"] is True
    assert growth["observaciones_usadas"] == 14

    insufficient = api.get(BASE, params={"estado": "insufficient"}, headers=AUTH).json()["items"]
    assert insufficient[0]["metrica"] == "wiki_views_acceleration"
    assert insufficient[0]["valor"] is None and insufficient[0]["motivo"].startswith("earlier_")


def test_reads_never_compute(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    api.get(BASE, headers=AUTH)
    api.get(f"{BASE}/definiciones", headers=AUTH)

    assert _count(session_factory) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"fecha_referencia": "2026-10-01"},  # sin data_mode
        {"data_mode": "real"},  # sin fecha
        {"data_mode": "todos", "fecha_referencia": "2026-10-01"},
        {"data_mode": "real", "fecha_referencia": "2026-10-01", "temas": ["no-es-un-id"]},
        {"data_mode": "real", "fecha_referencia": "2026-10-01", "extra": 1},
    ],
)
def test_invalid_calculation_requests(api: TestClient, body: dict) -> None:
    assert api.post(f"{BASE}/calculos", json=body, headers=AUTH).status_code == 422


def test_reference_date_must_be_a_closed_day(api: TestClient) -> None:
    today = datetime.now(UTC).date().isoformat()

    response = api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": today}, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_reference_date"


def test_metrics_are_isolated_by_data_mode(api: TestClient, session_factory) -> None:
    _seed(session_factory, DataMode.SIMULATED)
    api.post(f"{BASE}/calculos", json={"data_mode": "simulated", "fecha_referencia": AS_OF.isoformat()}, headers=AUTH)

    assert api.get(BASE, headers=AUTH).json()["total"] == 0
    sim = api.get(BASE, params={"data_mode": "simulated"}, headers=AUTH).json()
    assert sim["total"] == 5 and all(m["data_mode"] == "simulated" for m in sim["items"])


def test_unknown_metric_filter_is_rejected(api: TestClient) -> None:
    response = api.get(BASE, params={"metrica": "puntuacion_global"}, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_metric"


def test_token_does_not_leak(api: TestClient, session_factory, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _seed(session_factory)

    texts = [
        api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": AS_OF.isoformat()}, headers=AUTH).text,
        api.get(BASE, headers=AUTH).text,
        caplog.text,
    ]

    assert all(TOKEN not in t for t in texts)


def test_filters_by_topic_source_and_date(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    api.post(f"{BASE}/calculos", json={"data_mode": "real", "fecha_referencia": AS_OF.isoformat()}, headers=AUTH)
    topic_id = api.get(BASE, headers=AUTH).json()["items"][0]["tema_id"]

    assert api.get(BASE, params={"tema_id": topic_id}, headers=AUTH).json()["total"] == 5
    assert api.get(BASE, params={"fuente": "gdelt"}, headers=AUTH).json()["total"] == 0
    other_day = (AS_OF - timedelta(days=1)).isoformat()
    assert api.get(BASE, params={"fecha_referencia": other_day}, headers=AUTH).json()["total"] == 0
