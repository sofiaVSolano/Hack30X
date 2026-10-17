"""API de temas (E7): autenticación, normalización explícita, lecturas y correcciones."""

import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.api.router import API_PREFIX
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.storage.models import DataMode, Topic, TopicLink

from ..topics import helpers

TOKEN = "token-de-prueba-" + "t" * 24  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = f"{API_PREFIX}/temas"


@pytest.fixture
def api(app: FastAPI, session_factory) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    with TestClient(app) as client:
        yield client


def _seed(session_factory, mode: DataMode = DataMode.REAL) -> None:
    with session_factory() as session, session.begin():
        helpers.trends(session, "México", mode=mode)
        helpers.wiki(session, "México", mode=mode)
        helpers.trends(session, "Mercurio", mode=mode)
        helpers.wiki(session, "Mercurio_(planeta)", mode=mode)


def _normalize(api: TestClient, mode: str = "real") -> dict:
    response = api.post(f"{BASE}/normalizaciones", json={"data_mode": mode}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _counts(session_factory) -> tuple[int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(Topic)),
            session.scalar(select(func.count()).select_from(TopicLink)),
        )


# --- Autenticación -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/temas"),
        ("get", "/temas/vinculos"),
        ("get", "/temas/tpc_0000000000000000"),
        ("get", "/temas/observaciones/1/vinculos"),
        ("post", "/temas/normalizaciones"),
        ("post", "/temas/vinculos/1/correccion"),
        ("post", "/temas/tpc_0000000000000000/alias"),
        ("post", "/temas/tpc_0000000000000000/ambiguedad"),
    ],
)
def test_all_topic_routes_require_the_admin_token(api: TestClient, method: str, path: str) -> None:
    response = getattr(api, method)(API_PREFIX + path, headers={"Authorization": "Bearer " + "n" * 40})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_token_never_appears_in_responses_or_logs(api, session_factory, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _seed(session_factory)

    texts = [
        api.post(f"{BASE}/normalizaciones", json={"data_mode": "real"}, headers=AUTH).text,
        api.get(BASE, headers=AUTH).text,
        api.get(f"{BASE}/vinculos", headers=AUTH).text,
        caplog.text,
    ]

    assert all(TOKEN not in t for t in texts)


# --- Normalización explícita ----------------------------------------------------------------


def test_normalization_requires_explicit_data_mode(api: TestClient) -> None:
    response = api.post(f"{BASE}/normalizaciones", json={}, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_normalization_report_and_idempotency(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    first = _normalize(api)
    second = _normalize(api)

    assert first["reglas"] == "topics-v1"
    assert first["procesadas"] == 4
    assert first["temas_creados"] == 2
    assert first["por_regla"] == {"new_topic": 2, "exact_normalized": 1, "disambiguation_base": 1}
    assert first["por_estado"] == {"linked": 3, "needs_review": 1}
    assert second["procesadas"] == 0 and second["temas_creados"] == 0


def test_reads_do_not_trigger_normalization_or_write(api: TestClient, session_factory) -> None:
    _seed(session_factory)

    api.get(BASE, headers=AUTH)
    api.get(f"{BASE}/vinculos", headers=AUTH)

    assert _counts(session_factory) == (0, 0)


# --- Lecturas ------------------------------------------------------------------------------


def test_topic_list_and_detail_show_aliases_and_sources(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _normalize(api)

    page = api.get(BASE, params={"q": "mexico"}, headers=AUTH).json()
    (topic,) = page["items"]
    assert page["total"] == 1
    assert (topic["nombre"], topic["clave_normalizada"]) == ("México", "mexico")
    assert topic["vinculos_por_fuente"] == {"google_trends_rss": 1, "wikimedia": 1}

    detail = api.get(f"{BASE}/{topic['id']}", headers=AUTH).json()
    assert detail["alias"][0]["tipo"] == "canonical"
    assert {(s["fuente"], s["sujeto_original"]) for s in detail["sujetos"]} == {
        ("google_trends_rss", "México"),
        ("wikimedia", "es.wikipedia.org:México"),
    }


def test_review_queue_lists_pending_links_with_provenance(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _normalize(api)

    queue = api.get(f"{BASE}/vinculos", params={"estado": "needs_review"}, headers=AUTH).json()["items"]

    (pending,) = queue
    assert pending["fuente"] == "wikimedia"
    assert pending["sujeto_original"] == "es.wikipedia.org:Mercurio_(planeta)"
    assert pending["candidato"] == "Mercurio (planeta)"
    assert pending["regla"] == "disambiguation_base"
    assert pending["certeza"] == "none"
    assert pending["origen"] == "normalizer:topics-v1"
    assert pending["tema_id"] is not None  # tema propuesto


def test_topics_are_isolated_by_data_mode(api: TestClient, session_factory) -> None:
    _seed(session_factory, DataMode.SIMULATED)
    _normalize(api, "simulated")

    assert api.get(BASE, headers=AUTH).json()["total"] == 0
    sim = api.get(BASE, params={"data_mode": "simulated"}, headers=AUTH).json()
    assert sim["total"] == 2 and all(t["data_mode"] == "simulated" for t in sim["items"])
    topic_id = sim["items"][0]["id"]
    assert api.get(f"{BASE}/{topic_id}", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/temas/tpc_0000000000000000", "/temas/observaciones/999/vinculos"],
)
def test_unknown_resources_are_404(api: TestClient, path: str) -> None:
    assert api.get(API_PREFIX + path, headers=AUTH).status_code == 404


# --- Correcciones, alias y ambigüedad --------------------------------------------------------


def test_correction_flow_keeps_history(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _normalize(api)
    pending = api.get(f"{BASE}/vinculos", params={"estado": "needs_review"}, headers=AUTH).json()["items"][0]

    response = api.post(
        f"{BASE}/vinculos/{pending['id']}/correccion",
        json={"data_mode": "real", "accion": "reject", "autor": "ana", "motivo": "Es el planeta, no el dios"},
        headers=AUTH,
    )

    assert response.status_code == 200
    corrected = response.json()
    assert (corrected["estado"], corrected["regla"], corrected["certeza"], corrected["origen"]) == (
        "rejected", "manual_correction", "manual", "manual:ana",
    )
    assert corrected["reemplaza_a"] == pending["id"]
    history = api.get(f"{BASE}/observaciones/{pending['observacion_id']}/vinculos", headers=AUTH).json()
    assert [h["id"] for h in history] == [pending["id"], corrected["id"]]
    assert history[0]["reemplazado"] is not None
    # Corregir de nuevo el vínculo ya reemplazado no está permitido.
    again = api.post(
        f"{BASE}/vinculos/{pending['id']}/correccion",
        json={"data_mode": "real", "accion": "unlink", "autor": "ana", "motivo": "otra vez"},
        headers=AUTH,
    )
    assert again.status_code == 422


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"data_mode": "real", "accion": "link", "tema_id": "tpc_0000000000000000", "autor": "ana", "motivo": "abc"}, 404),
        ({"data_mode": "real", "accion": "link", "autor": "ana", "motivo": "abc"}, 404),
        ({"data_mode": "real", "accion": "reject", "autor": "a b", "motivo": "abc"}, 422),
        ({"data_mode": "real", "accion": "reject", "autor": "ana", "motivo": ""}, 422),
        ({"accion": "reject", "autor": "ana", "motivo": "abc"}, 422),
        ({"data_mode": "real", "accion": "borrar", "autor": "ana", "motivo": "abc"}, 422),
    ],
)
def test_invalid_corrections(api: TestClient, session_factory, body, status) -> None:
    _seed(session_factory)
    _normalize(api)
    link_id = api.get(f"{BASE}/vinculos", headers=AUTH).json()["items"][0]["id"]

    assert api.post(f"{BASE}/vinculos/{link_id}/correccion", json=body, headers=AUTH).status_code == status


def test_alias_endpoint_and_conflict(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _normalize(api)
    topics = api.get(BASE, headers=AUTH).json()["items"]
    mercurio, mexico = sorted(topics, key=lambda t: t["clave_normalizada"])

    created = api.post(
        f"{BASE}/{mexico['id']}/alias",
        json={"data_mode": "real", "texto": "MX", "tipo": "acronym", "autor": "ana"},
        headers=AUTH,
    )
    conflict = api.post(
        f"{BASE}/{mercurio['id']}/alias",
        json={"data_mode": "real", "texto": "mx", "tipo": "variant", "autor": "ana"},
        headers=AUTH,
    )
    canonical = api.post(
        f"{BASE}/{mexico['id']}/alias",
        json={"data_mode": "real", "texto": "Otro", "tipo": "canonical", "autor": "ana"},
        headers=AUTH,
    )

    assert created.status_code == 201 and created.json()["origen"] == "manual:ana"
    assert conflict.status_code == 409 and conflict.json()["code"] == "alias_conflict"
    assert canonical.status_code == 422


def test_ambiguity_endpoint(api: TestClient, session_factory) -> None:
    _seed(session_factory)
    _normalize(api)
    topic_id = api.get(BASE, params={"q": "mercurio"}, headers=AUTH).json()["items"][0]["id"]

    missing_reason = api.post(
        f"{BASE}/{topic_id}/ambiguedad", json={"data_mode": "real", "ambiguo": True, "autor": "ana"}, headers=AUTH
    )
    marked = api.post(
        f"{BASE}/{topic_id}/ambiguedad",
        json={"data_mode": "real", "ambiguo": True, "autor": "ana", "motivo": "planeta, elemento o dios"},
        headers=AUTH,
    )

    assert missing_reason.status_code == 422
    assert marked.status_code == 200
    assert marked.json()["ambiguo"] is True
    assert marked.json()["motivo_ambiguedad"] == "planeta, elemento o dios"
