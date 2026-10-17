"""Fixtures comunes de las pruebas de DETECTAR.

- Bloquea toda conexión de red que no sea de loopback. Cualquier intento hace fallar la
  prueba, aunque el código bajo prueba capture la excepción.
- Aísla las pruebas de variables ``DETECTAR_*`` presentes en el entorno de quien las ejecuta.
- Construye una app FastAPI de prueba independiente; no usa ``app/main.py``.
"""

import os
import socket
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Hasta que el equipo acuerde backend/pyproject.toml (configuración de pytest incluida),
# se agrega backend/ al path para poder importar app.modules.detectar.
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.detectar.api.errors import install_exception_handlers
from app.modules.detectar.api.router import API_PREFIX, get_clock, router
from app.modules.detectar.config import DetectarSettings, get_settings

# asyncio en Windows crea pares de sockets por loopback, así que se permiten.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

FIXED_NOW = datetime(2026, 10, 16, 22, 0, 0, tzinfo=UTC)


class NetworkBlockedError(RuntimeError):
    """Se lanza ante cualquier intento de red real durante las pruebas."""


def _as_host(value: object) -> str:
    # httpx/anyio pueden pasar el nombre del host como bytes.
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("ascii", errors="backslashreplace")
    return str(value)


def _host_of(address: object) -> str | None:
    if isinstance(address, tuple) and address:
        return _as_host(address[0])
    return None  # sockets AF_UNIX u otras familias locales


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(host: str | None) -> None:
        if host is not None and host not in _LOOPBACK_HOSTS:
            attempts.append(host)
            raise NetworkBlockedError(f"Conexión de red bloqueada en pruebas: {host}")

    def guarded_connect(self: socket.socket, address: object) -> None:
        _check(_host_of(address))
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        _check(_host_of(address))
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        _check(None if host is None else _as_host(host))
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)

    yield attempts

    if attempts:
        pytest.fail(f"La prueba intentó conexiones de red reales: {attempts}")


@pytest.fixture(autouse=True)
def clean_detectar_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("DETECTAR_"):
            monkeypatch.delenv(name)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def never_touch_default_database() -> Iterator[None]:
    """E12: ninguna prueba puede crear la base de datos en la ruta por defecto del usuario."""
    from app.modules.detectar.storage.db import default_db_path

    path = default_db_path()
    existed = path.exists()
    yield
    if not existed and path.exists():
        pytest.fail(f"La prueba creó la base de datos por defecto: {path}")


@pytest.fixture
def settings() -> DetectarSettings:
    return DetectarSettings(env="test")


@pytest.fixture
def app(settings: DetectarSettings) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router, prefix=API_PREFIX)
    install_exception_handlers(test_app, prefix=API_PREFIX)
    test_app.dependency_overrides[get_settings] = lambda: settings
    test_app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_NOW)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
