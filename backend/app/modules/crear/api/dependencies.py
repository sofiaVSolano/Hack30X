"""Dependencias de FastAPI para CREAR.

Como en DETECTAR, nada se crea al importar: la base de CREAR, el generador y el servicio se
crean de forma perezosa en la primera solicitud que los necesita, y las pruebas los sustituyen
con ``app.dependency_overrides``.

- La lectura de DETECTAR usa SU fábrica de sesiones (``get_session_factory``): misma base y
  misma configuración que el resto de la oficina.
- El acceso exige el mismo token administrativo que DETECTAR (``DETECTAR_ADMIN_TOKEN``): el
  intermediario de la oficina ya lo envía y no hace falta otro secreto.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.api.errors import CrearError
from app.modules.crear.config import get_crear_settings
from app.modules.crear.generation.factory import Generator, build_generator
from app.modules.crear.service import CreativeService
from app.modules.crear.storage.db import open_session_factory, resolve_db_path
from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.api.dependencies import (
    require_admin as detectar_require_admin,
)
from app.modules.detectar.api.errors import DetectarError
from app.modules.detectar.config import DetectarSettings, get_settings

_bearer = HTTPBearer(auto_error=False, description="Token administrativo de HACK 30X (el de DETECTAR)")


@lru_cache
def _default_crear_session_factory() -> sessionmaker[Session]:
    return open_session_factory(resolve_db_path(get_crear_settings(), get_settings()))


def get_crear_session_factory() -> sessionmaker[Session]:
    return _default_crear_session_factory()


@lru_cache
def _default_generator() -> Generator:
    return build_generator(get_crear_settings())


def get_generator() -> Generator:
    return _default_generator()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    return _utc_now


def get_creative_service(
    detectar_sessions: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    crear_sessions: Annotated[sessionmaker[Session], Depends(get_crear_session_factory)],
    generator: Annotated[Generator, Depends(get_generator)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> CreativeService:
    return CreativeService(
        detectar_sessions=detectar_sessions, crear_sessions=crear_sessions, generator=generator, clock=clock
    )


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[DetectarSettings, Depends(get_settings)],
) -> None:
    """La misma comprobación de DETECTAR (tiempo constante, sin registrar el token), con
    mensajes de CREAR."""
    try:
        detectar_require_admin(credentials, settings)
    except DetectarError as exc:
        if exc.status == 403:
            raise CrearError(
                code="crear_disabled",
                status=403,
                title="CREAR deshabilitado",
                detail="Configure DETECTAR_ADMIN_TOKEN para habilitar CREAR.",
            ) from None
        raise CrearError(
            code=exc.code, status=exc.status, title=exc.title, detail=exc.detail, headers=exc.headers
        ) from None
