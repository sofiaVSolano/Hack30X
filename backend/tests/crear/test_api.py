"""API de CREAR: acceso, opciones, temas, brechas (RF-06) y propuestas (RF-09, RF-10)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.storage.models import DataMode

from .builders import AS_OF, last_days, run_detectar, seed_gaps, topic_id, trends
from .conftest import AUTH

P = "/api/crear"


@pytest.fixture
def seeded(detectar_sessions: sessionmaker[Session]) -> None:
    seed_gaps(detectar_sessions)


def create(client: TestClient, **body: object):
    payload = {"data_mode": "real", "origen": "brecha", "tema_id": topic_id("Brecha"), "plataforma": "tiktok", **body}
    return client.post(f"{P}/propuestas", headers=AUTH, json=payload)


# --- acceso y opciones ------------------------------------------------------------------------


def test_health_is_public_and_reports_the_engine(client: TestClient) -> None:
    body = client.get(f"{P}/health").json()

    assert (body["status"], body["module"], body["reglas_brechas"]) == ("ok", "crear", "brechas-v1")
    assert body["motor"]["id"] == "plantillas-v1"


def test_routes_require_the_admin_token(client: TestClient) -> None:
    missing = client.get(f"{P}/opciones")
    wrong = client.post(f"{P}/propuestas", json={}, headers={"Authorization": "Bearer " + "x" * 40})

    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["type"] == "urn:hack30x:crear:error:unauthorized"


def test_without_a_configured_token_crear_is_disabled(app, client: TestClient) -> None:  # type: ignore[no-untyped-def]
    from app.modules.detectar.config import DetectarSettings, get_settings

    app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test")

    response = client.get(f"{P}/opciones", headers=AUTH)

    assert (response.status_code, response.json()["code"]) == (403, "crear_disabled")


def test_options_publish_the_catalog(client: TestClient) -> None:
    body = client.get(f"{P}/opciones", headers=AUTH).json()

    assert [e["id"] for e in body["enfoques"]] == ["educativo", "controversial", "narrativo"]
    assert len(body["plataformas"]) == 9 and body["audiencia_por_defecto"] == "general_latam"
    assert body["paises"][0] == {"id": "AR", "nombre": "Argentina"}  # orden alfabético por nombre
    assert body["motor"]["nombre"] == "Plantillas (sin IA)"


# --- temas y brechas ------------------------------------------------------------------------


def test_gaps_are_listed_by_priority_with_counts(client: TestClient, seeded: None) -> None:
    body = client.get(f"{P}/brechas", headers=AUTH, params={"data_mode": "real"}).json()

    assert body["fecha_referencia"] == AS_OF.isoformat()
    assert (body["version"], body["calibrado"]) == ("brechas-v1", False)
    assert [i["veredicto"] for i in body["items"]] == [
        "brecha_confirmada", "brecha_por_confirmar", "senales_mixtas", "sin_brecha", "datos_insuficientes",
    ]
    assert body["por_veredicto"] == {
        "brecha_confirmada": 1, "brecha_por_confirmar": 1, "senales_mixtas": 1, "sin_brecha": 1, "datos_insuficientes": 1,
    }
    first = body["items"][0]
    wiki = next(c for c in first["comparaciones"] if c["fuente"] == "wikimedia")
    assert (wiki["ingles"]["valor"], wiki["espanol"]["valor"], wiki["razon"], wiki["unidad"]) == (7000.0, 280.0, 25.0, "views")
    assert first["etapa"]["version"] == "stages-v1"
    assert body["limitaciones"]


def test_gaps_can_be_filtered_and_paged(client: TestClient, seeded: None) -> None:
    only = client.get(f"{P}/brechas", headers=AUTH, params={"veredicto": "senales_mixtas"}).json()
    page = client.get(f"{P}/brechas", headers=AUTH, params={"limite": 2, "desplazamiento": 2}).json()

    assert [i["tema_nombre"] for i in only["items"]] == ["Mixta"] and only["total"] == 1
    assert [i["tema_nombre"] for i in page["items"]] == ["Mixta", "Pareja"] and page["total"] == 5


def test_gap_detail_and_rules(client: TestClient, seeded: None) -> None:
    detail = client.get(f"{P}/brechas/{topic_id('Solo ingles')}", headers=AUTH)
    missing = client.get(f"{P}/brechas/tpc_0000000000000000", headers=AUTH)
    rules = client.get(f"{P}/brechas/reglas", headers=AUTH).json()

    assert detail.json()["veredicto"] == "brecha_por_confirmar"
    assert missing.status_code == 404
    assert (rules["version"], rules["provisional"]) == ("brechas-v1", True)
    assert set(rules["veredictos"]) == {"brecha_confirmada", "brecha_por_confirmar", "senales_mixtas", "sin_brecha", "datos_insuficientes"}
    assert len(rules["parametros_sha256"]) == 64


def test_topics_carry_stage_and_gap_verdict(client: TestClient, seeded: None) -> None:
    body = client.get(f"{P}/temas", headers=AUTH, params={"q": "brecha"}).json()

    (topic,) = body["items"]
    assert (topic["nombre"], topic["veredicto_brecha"]) == ("Brecha", "brecha_confirmada")
    assert topic["etapa"]["etapa"] == "datos_insuficientes"  # series planas: DETECTAR no asigna etapa
    assert topic["vinculos_por_fuente"] == {"google_trends_rss": 7, "wikimedia": 42}


def test_simulated_topics_are_not_visible_in_real_mode(client: TestClient, detectar_sessions) -> None:  # type: ignore[no-untyped-def]
    seed_gaps(detectar_sessions, mode=DataMode.SIMULATED)

    assert client.get(f"{P}/brechas", headers=AUTH, params={"data_mode": "real"}).json()["items"] == []
    assert client.get(f"{P}/brechas", headers=AUTH, params={"data_mode": "simulated"}).json()["total"] == 5


# --- RF-09: tres propuestas -------------------------------------------------------------------


def test_a_gap_becomes_three_proposals(client: TestClient, seeded: None) -> None:
    response = create(client, pais="MX", audiencia="emprendedores")

    assert response.status_code == 201
    body = response.json()
    proposals = body["propuestas"]
    assert [p["enfoque"] for p in proposals] == ["educativo", "controversial", "narrativo"]
    assert {p["lote_id"] for p in proposals} == {body["lote_id"]}
    assert all(p["version"] == 1 and p["padre_id"] is None and p["raiz_id"] == p["id"] for p in proposals)
    assert all(p["cifras_sin_respaldo"] == [] and p["motor"] == "plantillas-v1" for p in proposals)
    assert body["contexto"]["veredicto_brecha"] == "brecha_confirmada"
    assert any("25,0×" in h["texto"] for h in body["contexto"]["hechos"])
    listed = client.get(f"{P}/propuestas", headers=AUTH, params={"lote_id": body["lote_id"]}).json()
    assert listed["total"] == 3


def test_a_written_topic_needs_no_detectar_data(client: TestClient) -> None:
    response = create(client, origen="manual", tema_id=None, tema_texto="  Recetas   con maíz ", pais=None)

    assert response.status_code == 201
    context = response.json()["contexto"]
    assert (context["tema_nombre"], context["tema_id"], context["hechos"]) == ("Recetas con maíz", None, [])
    assert "Tema escrito a mano" in context["limitaciones"][0]


@pytest.mark.parametrize(
    "body",
    [
        {"origen": "manual", "tema_id": None},  # falta tema_texto
        {"origen": "tema", "tema_id": None},  # falta tema_id
        {"audiencia": "astronautas"},
        {"pais": "ES"},  # España no es un país de Latinoamérica del catálogo
        {"plataforma": "myspace"},
        {"origen": "manual", "tema_id": None, "tema_texto": "con\u0007control"},
        {"extra": True},
    ],
)
def test_invalid_requests_are_problem_json(client: TestClient, body: dict[str, object]) -> None:
    response = create(client, **body)

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:hack30x:crear:error:validation_error"
    assert problem["errors"]
    for echoed in ("con\u0007control", "astronautas", "myspace"):  # nunca se devuelve el valor recibido
        assert echoed not in response.text


def test_unknown_topic_and_topic_without_comparison(client: TestClient, detectar_sessions) -> None:  # type: ignore[no-untyped-def]
    # Solo tendencias en España: DETECTAR conoce el tema, pero no hay comparación inglés–español.
    with detectar_sessions() as session, session.begin():
        trends(session, "ES", {d: ["Solo Espana"] for d in last_days(7)})
    run_detectar(detectar_sessions)

    unknown = create(client, tema_id="tpc_0000000000000000")
    no_gap = create(client, tema_id=topic_id("Solo Espana"))
    as_topic = create(client, origen="tema", tema_id=topic_id("Solo Espana"))

    assert (unknown.status_code, unknown.json()["detail"]) == (404, "El tema no existe.")
    assert (no_gap.status_code, no_gap.json()["code"]) == (422, "invalid_operation")
    assert as_topic.status_code == 201
    assert as_topic.json()["contexto"]["veredicto_brecha"] is None


# --- RF-10: regenerar ----------------------------------------------------------------------------


def test_regenerating_creates_versions_and_keeps_the_history(client: TestClient, seeded: None) -> None:
    original = create(client).json()["propuestas"][0]

    second = client.post(
        f"{P}/propuestas/{original['id']}/regeneraciones", headers=AUTH,
        json={"data_mode": "real", "plataforma": "instagram_carrusel"},
    ).json()
    third = client.post(
        f"{P}/propuestas/{original['id']}/regeneraciones", headers=AUTH,
        json={"data_mode": "real", "enfoque": "narrativo", "audiencia": "jovenes_genz", "indicacion": "más humor"},
    ).json()

    assert (second["version"], second["padre_id"], second["raiz_id"]) == (2, original["id"], original["id"])
    assert second["cambios"] == ["plataforma"]
    assert second["contenido"]["estructura"][0].startswith("Diapositiva 1")
    assert (third["version"], third["padre_id"]) == (3, original["id"])  # se ramifica desde v1
    assert third["cambios"] == ["enfoque", "audiencia", "indicacion"]
    assert "no interpretan indicaciones libres" in third["aviso_motor"]
    detail = client.get(f"{P}/propuestas/{third['id']}", headers=AUTH).json()
    assert [v["version"] for v in detail["versiones"]] == [1, 2, 3]
    assert detail["contexto"]["tema_nombre"] == "Brecha"


def test_regeneration_keeps_unsent_fields_and_can_clear_the_country(client: TestClient, seeded: None) -> None:
    original = create(client, pais="CO", audiencia_detalle="estudiantes de Medellín").json()["propuestas"][1]
    url = f"{P}/propuestas/{original['id']}/regeneraciones"

    same = client.post(url, headers=AUTH, json={"data_mode": "real"}).json()
    cleared = client.post(url, headers=AUTH, json={"data_mode": "real", "pais": None}).json()

    assert (same["pais"], same["audiencia_detalle"], same["cambios"]) == ("CO", "estudiantes de Medellín", ["nueva_variante"])
    assert (cleared["pais"], cleared["cambios"]) == (None, ["pais"])


def test_proposals_never_cross_data_modes(client: TestClient, seeded: None) -> None:
    original = create(client).json()["propuestas"][0]

    other_mode = client.post(
        f"{P}/propuestas/{original['id']}/regeneraciones", headers=AUTH, json={"data_mode": "simulated"}
    )
    listed = client.get(f"{P}/propuestas", headers=AUTH, params={"data_mode": "simulated"}).json()

    assert other_mode.status_code == 404
    assert listed["total"] == 0
    assert client.get(f"{P}/propuestas/prp_0000000000000000", headers=AUTH).status_code == 404
