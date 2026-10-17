"""Dependencias de FastAPI para DETECTAR.

La base de datos y el servicio de recolección se crean de forma perezosa en la primera
solicitud que los necesite, nunca al importar. Las pruebas los sustituyen con
``app.dependency_overrides``.
"""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import LocalAgentCoordinator
from app.modules.detectar.agents.registry import default_registry
from app.modules.detectar.agents.scheduler import AgentScheduler
from app.modules.detectar.agents.tasks import TaskDependencies, build_tasks
from app.modules.detectar.api.errors import DetectarError
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.ingestion.collection import CollectionService
from app.modules.detectar.logsafety import register_secret
from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
    resolve_db_path,
)

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False, description="Token administrativo de DETECTAR")


@lru_cache
def _default_session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    engine = create_sqlite_engine(resolve_db_path(settings))
    init_db(engine)
    return create_session_factory(engine)


def get_session_factory() -> sessionmaker[Session]:
    return _default_session_factory()


@lru_cache
def _default_collection_service() -> CollectionService:
    return CollectionService(get_session_factory(), get_settings())


def get_collection_service() -> CollectionService:
    return _default_collection_service()


@lru_cache
def _default_agent_coordinator() -> LocalAgentCoordinator:
    """Coordinador con el mapa fijo de tareas (E10). Comparte el servicio de recolección
    con ``POST /recolecciones``, y con él su bloqueo contra recolecciones simultáneas."""
    registry = default_registry()
    session_factory = get_session_factory()
    deps = TaskDependencies(
        session_factory=session_factory,
        collection_service=get_collection_service(),
        registry=registry,
    )
    return LocalAgentCoordinator(
        session_factory,
        registry,
        tasks=build_tasks(deps),
        schedules_minutes=get_settings().agent_schedules,
    )


def get_agent_coordinator() -> LocalAgentCoordinator:
    return _default_agent_coordinator()


@lru_cache
def _default_agent_scheduler() -> AgentScheduler:
    """Programador (E11) sobre el MISMO coordinador que la API: comparte el control de
    ejecuciones activas y de ejecuciones simultáneas."""
    return AgentScheduler(
        get_agent_coordinator(), get_session_factory(), default_registry(), get_settings()
    )


def get_agent_scheduler() -> AgentScheduler:
    return _default_agent_scheduler()


@asynccontextmanager
async def detectar_scheduler_lifespan() -> AsyncIterator[AgentScheduler | None]:
    """``lifespan`` del programador, usado por ``app/main.py`` (E12).

    Solo crea e inicia el programador si ``DETECTAR_SCHEDULER_ENABLED=true``; al salir lo
    detiene de forma ordenada. Un error al crearlo o iniciarlo se registra y se propaga, de
    modo que la aplicación no arranca a medias. Un error al detenerlo también se registra y
    se propaga.
    """
    if not get_settings().scheduler_enabled:
        logger.info("Programador de DETECTAR deshabilitado (DETECTAR_SCHEDULER_ENABLED=false)")
        yield None
        return
    try:
        scheduler = get_agent_scheduler()
        scheduler.start()
    except Exception as exc:
        logger.error("No se pudo iniciar el programador de DETECTAR: %s", type(exc).__name__)
        raise
    logger.info("Programador de DETECTAR iniciado")
    try:
        yield scheduler
    finally:
        try:
            await scheduler.stop()
        except Exception as exc:
            logger.error("Error al detener el programador de DETECTAR: %s", type(exc).__name__)
            raise
        logger.info("Programador de DETECTAR detenido")


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[DetectarSettings, Depends(get_settings)],
) -> None:
    """Exige ``Authorization: Bearer <DETECTAR_ADMIN_TOKEN>``.

    Sin token configurado el endpoint queda deshabilitado (403). El token nunca se
    registra ni se devuelve; se compara en tiempo constante.
    """
    if settings.admin_token is None:
        raise DetectarError(
            code="collections_disabled",
            status=403,
            title="Recolecciones deshabilitadas",
            detail="Configure DETECTAR_ADMIN_TOKEN para habilitar este endpoint.",
        )
    expected = settings.admin_token.get_secret_value()
    register_secret(expected)
    provided = credentials.credentials if credentials is not None else ""
    if provided:
        register_secret(provided)
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise DetectarError(
            code="unauthorized",
            status=401,
            title="No autorizado",
            detail="Token administrativo ausente o inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
