"""CREAR dentro de la app compartida (app/main.py), junto a DETECTAR."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import main
from app.modules.crear.api.errors import install_exception_handlers as install_crear
from app.modules.crear.api.router import router as crear_router
from app.modules.detectar.api.errors import (
    install_exception_handlers as install_detectar,
)
from app.modules.detectar.api.router import router as detectar_router

from .conftest import TOKEN

BACKEND = Path(__file__).resolve().parents[2]


def test_crear_routes_are_mounted_once_under_their_prefix() -> None:
    paths = [p for p in main.app.openapi()["paths"] if p.startswith("/api/crear")]

    reference = FastAPI()
    reference.include_router(crear_router, prefix="/api/crear")
    assert paths == list(reference.openapi()["paths"])
    assert "/api/crear/propuestas/{propuesta_id}/regeneraciones" in paths


def test_validation_handlers_are_chained_not_replaced() -> None:
    class Body(BaseModel):
        n: int

    app = FastAPI()
    app.include_router(detectar_router, prefix="/api/detectar")
    install_detectar(app, prefix="/api/detectar")
    app.include_router(crear_router, prefix="/api/crear")
    install_crear(app, prefix="/api/crear")

    @app.post("/otra")
    def other(body: Body) -> dict[str, int]:
        return {"n": body.n}

    with TestClient(app) as client:
        detectar = client.get("/api/detectar/temas", params={"limite": 0}, headers={"Authorization": f"Bearer {TOKEN}"})
        crear = client.get("/api/crear/health", params={})
        other_response = client.post("/otra", json={"n": "x"})

    # DETECTAR conserva su formato (aquí falla antes la autenticación, igual de problem+json).
    assert detectar.headers["content-type"].startswith("application/problem+json")
    assert crear.status_code == 200
    assert other_response.status_code == 422 and "detail" in other_response.json()  # formato de FastAPI


def test_crear_validation_errors_use_the_crear_format(monkeypatch, isolated_databases: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DETECTAR_ADMIN_TOKEN", TOKEN)
    with TestClient(main.create_app()) as client:
        response = client.post("/api/crear/propuestas", json={"data_mode": "nada"}, headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:hack30x:crear:error:validation_error"
    assert (isolated_databases / "crear.db").exists()  # la base se creó en la carpeta temporal


def test_detectar_validation_errors_keep_their_format(monkeypatch, isolated_databases: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DETECTAR_ADMIN_TOKEN", TOKEN)
    with TestClient(main.create_app()) as client:
        response = client.post("/api/detectar/recolecciones", json={"fuentes": "nada"}, headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 422
    assert response.json()["type"] == "urn:hack30x:detectar:error:validation_error"


def test_importing_main_creates_nothing(tmp_path: Path) -> None:
    detectar_db, crear_db = tmp_path / "detectar.db", tmp_path / "crear.db"
    code = (
        "import app.main as m; "
        "from app.modules.crear.api import dependencies as d; "
        "assert d._default_crear_session_factory.cache_info().currsize == 0; "
        "assert d._default_generator.cache_info().currsize == 0; "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=BACKEND,
        env={"DETECTAR_DB_PATH": str(detectar_db), "PYTHONDONTWRITEBYTECODE": "1", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert not detectar_db.exists() and not crear_db.exists()
