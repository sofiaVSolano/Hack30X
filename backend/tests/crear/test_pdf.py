"""Documento PDF de un lote: contenido, orden, nombre de archivo y aislamiento por modo."""

import sys
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.export.pdf import batch_pdf, latest_versions
from app.modules.crear.generation.factory import Generator
from app.modules.crear.service import CreativeService, ProposalNotFoundError
from app.modules.detectar.storage.models import DataMode

from .builders import seed_gaps, topic_id
from .conftest import AUTH

pytest.importorskip("reportlab")  # extra opcional «crear»

P = "/api/crear"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def batch(client: TestClient, detectar_sessions: sessionmaker[Session]) -> dict:
    seed_gaps(detectar_sessions)
    body = {"data_mode": "real", "origen": "brecha", "tema_id": topic_id("Brecha"), "plataforma": "tiktok", "pais": "MX"}
    return client.post(f"{P}/propuestas", headers=AUTH, json=body).json()


def test_download_is_a_pdf_with_a_safe_file_name(client: TestClient, batch: dict) -> None:
    response = client.get(f"{P}/lotes/{batch['lote_id']}/pdf", headers=AUTH, params={"data_mode": "real"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="propuestas-brecha-{batch["lote_id"][4:12]}.pdf"'
    assert response.content.startswith(b"%PDF-")


def test_unknown_or_other_mode_batches_are_not_found(client: TestClient, batch: dict) -> None:
    missing = client.get(f"{P}/lotes/lot_0000000000000000/pdf", headers=AUTH)
    other_mode = client.get(f"{P}/lotes/{batch['lote_id']}/pdf", headers=AUTH, params={"data_mode": "simulated"})

    assert missing.status_code == other_mode.status_code == 404


def service(crear_sessions: sessionmaker[Session], generator: Generator) -> CreativeService:
    return CreativeService(
        detectar_sessions=crear_sessions, crear_sessions=crear_sessions, generator=generator, clock=lambda: NOW
    )


def test_document_contains_every_proposal_and_its_latest_version(
    client: TestClient, crear_sessions: sessionmaker[Session], generator: Generator, batch: dict
) -> None:
    first = batch["propuestas"][0]["id"]  # la educativa se regenera como narrativa en YouTube
    client.post(
        f"{P}/propuestas/{first}/regeneraciones", headers=AUTH,
        json={"data_mode": "real", "enfoque": "narrativo", "plataforma": "youtube"},
    )

    proposals, context = service(crear_sessions, generator).batch(batch["lote_id"], data_mode=DataMode.REAL)
    latest = latest_versions(proposals)
    document = batch_pdf(proposals, context, generated_at=NOW, compress=False)

    # Cada propuesta conserva su lugar aunque una versión nueva cambie de enfoque.
    assert [(p.approach.value, p.version, n) for p, n in latest] == [
        ("narrativo", 2, 2), ("controversial", 1, 1), ("narrativo", 1, 1),
    ]
    for text in (b"Brecha", b"Enfoque narrativo", b"Enfoque controversial", b"Lo que dicen los datos", b"YouTube"):
        assert text in document
    with pytest.raises(ProposalNotFoundError):
        service(crear_sessions, generator).batch("lot_0000000000000000", data_mode=DataMode.REAL)


def test_simulated_documents_say_so_on_every_page(
    client: TestClient, detectar_sessions: sessionmaker[Session], crear_sessions: sessionmaker[Session], generator: Generator
) -> None:
    seed_gaps(detectar_sessions, mode=DataMode.SIMULATED)
    body = {"data_mode": "simulated", "origen": "brecha", "tema_id": topic_id("Brecha", DataMode.SIMULATED), "plataforma": "tiktok"}
    lote = client.post(f"{P}/propuestas", headers=AUTH, json=body).json()["lote_id"]

    proposals, context = service(crear_sessions, generator).batch(lote, data_mode=DataMode.SIMULATED)
    document = batch_pdf(proposals, context, generated_at=NOW, compress=False)

    assert document.count(b"DATOS SIMULADOS DE DEMOSTRACI") == 4  # portada y una página por propuesta


def test_without_reportlab_the_download_explains_how_to_enable_it(client: TestClient, batch: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [m for m in sys.modules if m == "reportlab" or m.startswith("reportlab.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "reportlab", None)

    response = client.get(f"{P}/lotes/{batch['lote_id']}/pdf", headers=AUTH)

    assert (response.status_code, response.json()["code"]) == (503, "pdf_no_disponible")
    assert "extra «crear»" in response.json()["detail"]
