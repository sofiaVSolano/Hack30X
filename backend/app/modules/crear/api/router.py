"""Router HTTP de CREAR.

Se monta en la app compartida con ``app.include_router(router, prefix=API_PREFIX)``. Todas las
rutas, salvo ``/health``, exigen el token administrativo.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.modules.crear import __version__
from app.modules.crear.api.dependencies import get_clock, get_generator, require_admin
from app.modules.crear.api.gaps import gaps_router
from app.modules.crear.api.proposals import proposals_router
from app.modules.crear.api.schemas import (
    AudienceOut,
    CountryOut,
    EngineOut,
    OptionOut,
    OptionsOut,
    PlatformOut,
    engine_out,
)
from app.modules.crear.api.topics import topics_router
from app.modules.crear.catalog import (
    APPROACHES,
    AUDIENCES,
    COUNTRIES,
    DEFAULT_AUDIENCE,
    PLATFORMS,
)
from app.modules.crear.gaps.rules import RULES_VERSION as GAPS_VERSION
from app.modules.crear.generation.factory import Generator
from app.modules.detectar.timeutil import format_utc

__all__ = ["API_PREFIX", "router"]

API_PREFIX = "/api/crear"

router = APIRouter(tags=["crear"])
catalog_router = APIRouter(tags=["crear"], dependencies=[Depends(require_admin)])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    module: Literal["crear"]
    version: str
    reglas_brechas: str
    motor: EngineOut
    time: str


@router.get("/health", response_model=HealthResponse)
def health(
    generator: Annotated[Generator, Depends(get_generator)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> HealthResponse:
    # No abre bases de datos ni llama a Claude: solo informa qué motor usará.
    return HealthResponse(
        status="ok",
        module="crear",
        version=__version__,
        reglas_brechas=GAPS_VERSION,
        motor=engine_out(generator),
        time=format_utc(clock()),
    )


@catalog_router.get("/opciones", response_model=OptionsOut)
def options(generator: Annotated[Generator, Depends(get_generator)]) -> OptionsOut:
    return OptionsOut(
        enfoques=[OptionOut(id=a.id.value, nombre=a.name, descripcion=a.description) for a in APPROACHES.values()],
        plataformas=[
            PlatformOut(id=p.id, nombre=p.name, formato=p.format_text, pautas=list(p.guidelines))
            for p in PLATFORMS.values()
        ],
        audiencias=[
            AudienceOut(id=a.id, nombre=a.name, descripcion=a.description, tono=a.tone) for a in AUDIENCES.values()
        ],
        audiencia_por_defecto=DEFAULT_AUDIENCE,
        paises=[CountryOut(id=code, nombre=name) for code, name in sorted(COUNTRIES.items(), key=lambda i: i[1])],
        motor=engine_out(generator),
    )


router.include_router(catalog_router)
router.include_router(topics_router)
router.include_router(gaps_router)
router.include_router(proposals_router)
