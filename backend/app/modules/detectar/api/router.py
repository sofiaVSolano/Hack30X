"""Router HTTP de DETECTAR.

Se monta en la app compartida con ``app.include_router(router, prefix=API_PREFIX)``.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.modules.detectar import __version__
from app.modules.detectar.config import DetectarSettings, get_settings
from app.modules.detectar.timeutil import format_utc

__all__ = ["API_PREFIX", "format_utc", "get_clock", "router"]

API_PREFIX = "/api/detectar"

router = APIRouter(tags=["detectar"])


class ComponentCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "error", "not_configured", "not_checked", "not_loaded"]
    detail: str


class HealthChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database: ComponentCheck
    rules: ComponentCheck


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    module: Literal["detectar"]
    version: str
    rules_version: str
    time: str
    checks: HealthChecks


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    return utc_now


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[DetectarSettings, Depends(get_settings)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> HealthResponse:
    # "ok" indica que el módulo responde. /health todavía no comprueba la base de datos ni
    # hay reglas cargadas, así que no se declaran operativas.
    return HealthResponse(
        status="ok",
        module="detectar",
        version=__version__,
        rules_version=settings.rules_version,
        time=format_utc(clock()),
        checks=HealthChecks(
            database=ComponentCheck(
                status="not_checked",
                detail="Esta versión de /health no comprueba la base de datos.",
            ),
            rules=ComponentCheck(
                status="not_loaded",
                detail="El archivo de reglas versionadas se implementa en E8.",
            ),
        ),
    )


# Al final para evitar importaciones circulares: el router de recolecciones usa este módulo.
from app.modules.detectar.api.agents import agents_router
from app.modules.detectar.api.classifications import classifications_router
from app.modules.detectar.api.collections import collections_router
from app.modules.detectar.api.metrics import metrics_router
from app.modules.detectar.api.topics import topics_router

router.include_router(collections_router)
router.include_router(agents_router)
router.include_router(topics_router)
router.include_router(metrics_router)
router.include_router(classifications_router)
