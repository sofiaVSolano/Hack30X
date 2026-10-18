"""Aplicación FastAPI compartida de HACK 30X.

Importar este módulo solo construye la aplicación: no abre la base de datos, no hace
llamadas de red ni inicia tareas en segundo plano. El programador de DETECTAR (apagado por
defecto) se gestiona en el ``lifespan``.

Arranque local, desde ``backend/``::

    .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Ver ``app/modules/detectar/docs/e12-integracion-backend.md``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.modules.crear.api.errors import (
    install_exception_handlers as install_crear_exception_handlers,
)
from app.modules.crear.api.router import API_PREFIX as CREAR_PREFIX
from app.modules.crear.api.router import router as crear_router
from app.modules.detectar.api.dependencies import detectar_scheduler_lifespan
from app.modules.detectar.api.errors import install_exception_handlers
from app.modules.detectar.api.router import API_PREFIX as DETECTAR_PREFIX
from app.modules.detectar.api.router import router as detectar_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # DETECTAR: programador periódico (E11). None si DETECTAR_SCHEDULER_ENABLED=false.
    async with detectar_scheduler_lifespan() as scheduler:
        app.state.detectar_scheduler = scheduler
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="HACK 30X", lifespan=lifespan)
    app.state.detectar_scheduler = None

    # DETECTAR. El router no trae prefijo propio: se monta aquí, una sola vez.
    app.include_router(detectar_router, prefix=DETECTAR_PREFIX)
    # Errores RFC 9457 de DETECTAR. El manejador de validación solo cambia el formato bajo
    # /api/detectar; acordar con el equipo cómo combinarlo cuando se integren otros módulos.
    install_exception_handlers(app, prefix=DETECTAR_PREFIX)

    # CREAR (laboratorio creativo). Lee DETECTAR sin escribir en él. Sus manejadores se
    # instalan DESPUÉS de los de DETECTAR: el de validación atiende /api/crear y delega el resto.
    app.include_router(crear_router, prefix=CREAR_PREFIX)
    install_crear_exception_handlers(app, prefix=CREAR_PREFIX)

    # ENTENDER y VALIDAR se integrarán aquí cuando existan.
    return app


app = create_app()
