"""Fixtures de las pruebas de CREAR.

Mismas garantías que las pruebas de DETECTAR:

- toda conexión de red que no sea de loopback hace fallar la prueba (Claude incluido: su motor
  se prueba con un transporte HTTP simulado);
- se aíslan las variables ``CREAR_*``, ``DETECTAR_*`` y ``ANTHROPIC_*`` del entorno;
- ninguna prueba puede crear las bases por defecto de DETECTAR ni de CREAR.
"""

import os
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.api import dependencies as crear_dependencies
from app.modules.crear.api.errors import install_exception_handlers
from app.modules.crear.api.router import API_PREFIX, router
from app.modules.crear.config import CrearSettings, get_crear_settings
from app.modules.crear.generation.factory import Generator
from app.modules.crear.storage.db import open_session_factory
from app.modules.detectar.api import dependencies as detectar_dependencies
from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)

FIXED_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
TOKEN = "token-de-prueba-crear-" + "c" * 20  # solo para pruebas
AUTH = {"Authorization": f"Bearer {TOKEN}"}
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[str] = []
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def check(host: object) -> None:
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name not in _LOOPBACK:
            attempts.append(name)
            raise RuntimeError(f"Conexión de red bloqueada en pruebas: {name}")

    def guarded_connect(self: socket.socket, address: object) -> None:
        if isinstance(address, tuple) and address:
            check(address[0])
        return real_connect(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host is not None:
            check(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield
    if attempts:
        pytest.fail(f"La prueba intentó conexiones de red reales: {attempts}")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.upper().startswith(("CREAR_", "DETECTAR_", "ANTHROPIC_")):
            monkeypatch.delenv(name)
    caches = (
        get_settings,
        get_crear_settings,
        crear_dependencies._default_crear_session_factory,
        crear_dependencies._default_generator,
        detectar_dependencies._default_session_factory,
        detectar_dependencies._default_collection_service,
        detectar_dependencies._default_agent_coordinator,
        detectar_dependencies._default_agent_scheduler,
    )
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


@pytest.fixture(autouse=True)
def never_touch_default_databases() -> Iterator[None]:
    from app.modules.crear.storage.db import default_db_path as crear_default
    from app.modules.detectar.storage.db import default_db_path as detectar_default

    paths = [detectar_default(), crear_default(DetectarSettings())]
    existed = [p.exists() for p in paths]
    yield
    for path, before in zip(paths, existed, strict=True):
        if not before and path.exists():
            pytest.fail(f"La prueba creó una base por defecto: {path}")


@pytest.fixture
def isolated_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Para pruebas con la app real (app/main.py): ambas bases en una carpeta temporal."""
    monkeypatch.setenv("DETECTAR_DB_PATH", str(tmp_path / "app" / "detectar.db"))
    monkeypatch.setenv("CREAR_DB_PATH", str(tmp_path / "app" / "crear.db"))
    monkeypatch.setenv("CREAR_MOTOR", "plantillas")
    return tmp_path / "app"


@pytest.fixture
def detectar_sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_sqlite_engine(tmp_path / "detectar.db")
    init_db(engine)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture
def crear_sessions(tmp_path: Path) -> sessionmaker[Session]:
    return open_session_factory(tmp_path / "crear.db")


@pytest.fixture
def generator() -> Generator:
    return Generator(None, reason="Plantillas en pruebas.")


@pytest.fixture
def app(
    detectar_sessions: sessionmaker[Session], crear_sessions: sessionmaker[Session], generator: Generator
) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router, prefix=API_PREFIX)
    install_exception_handlers(test_app, prefix=API_PREFIX)
    test_app.dependency_overrides[get_settings] = lambda: DetectarSettings(env="test", admin_token=TOKEN)
    test_app.dependency_overrides[get_crear_settings] = lambda: CrearSettings(motor="plantillas")
    test_app.dependency_overrides[get_session_factory] = lambda: detectar_sessions
    test_app.dependency_overrides[crear_dependencies.get_crear_session_factory] = lambda: crear_sessions
    test_app.dependency_overrides[crear_dependencies.get_generator] = lambda: generator
    test_app.dependency_overrides[crear_dependencies.get_clock] = lambda: (lambda: FIXED_NOW)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
