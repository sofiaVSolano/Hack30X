"""Brechas inglés–español (RF-06). Solo lectura sobre los datos de DETECTAR.

El análisis no se guarda: se calcula en cada consulta con las métricas persistidas de la fecha
de referencia indicada (o de la última con métricas).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.api.dependencies import require_admin
from app.modules.crear.api.errors import not_found
from app.modules.crear.api.schemas import (
    TOPIC_PATTERN,
    GapOut,
    GapPage,
    GapRulesOut,
    Mode,
    gap_out,
)
from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.gaps.rules import (
    PARAMS,
    RESULT_DEFINITIONS,
    RULES_VERSION,
    SOURCE_METRICS,
    VERDICT_DEFINITIONS,
    VERDICT_ORDER,
    Verdict,
    params_sha256,
)
from app.modules.crear.gaps.service import GapService
from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.storage.models import DataMode

gaps_router = APIRouter(tags=["crear"], dependencies=[Depends(require_admin)])

LIMITATIONS = (
    f"Reglas {RULES_VERSION} provisionales y no calibradas con datos reales.",
    "Compara atención (lecturas, prensa y presencia en tendencias), no la cantidad de contenido publicado en cada idioma.",
    "«Sin medición» significa que DETECTAR no recolectó ese idioma, no que no exista contenido.",
    "EE. UU. cuenta como mercado en inglés aunque tenga una gran audiencia hispanohablante.",
)


@gaps_router.get("/brechas/reglas", response_model=GapRulesOut)
def rules() -> GapRulesOut:
    return GapRulesOut(
        version=RULES_VERSION,
        provisional=not PARAMS["calibrated"],
        calibrado=bool(PARAMS["calibrated"]),
        parametros=dict(PARAMS),
        parametros_sha256=params_sha256(),
        veredictos={v.value: VERDICT_DEFINITIONS[v] for v in VERDICT_ORDER},
        resultados={r.value: text for r, text in RESULT_DEFINITIONS.items()},
        metricas_usadas={s.value: list(keys) for s, keys in SOURCE_METRICS.items()},
        limitaciones=list(LIMITATIONS),
    )


@gaps_router.get("/brechas", response_model=GapPage)
def list_gaps(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    fecha_referencia: Annotated[date | None, Query()] = None,
    veredicto: Annotated[Verdict | None, Query()] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> GapPage:
    with session_factory() as session:
        report = GapService(DetectarReader(session)).analyze(data_mode=data_mode, as_of=fecha_referencia)
    counts = {v.value: 0 for v in VERDICT_ORDER}
    for analysis in report.analyses:
        counts[analysis.verdict.value] += 1
    selected = [a for a in report.analyses if veredicto is None or a.verdict is veredicto]
    page = selected[desplazamiento : desplazamiento + limite]
    return GapPage(
        data_mode=DataMode(data_mode),
        fecha_referencia=report.as_of,
        version=RULES_VERSION,
        calibrado=bool(PARAMS["calibrated"]),
        total=len(selected),
        limite=limite,
        desplazamiento=desplazamiento,
        por_veredicto=counts,
        items=[gap_out(a, report.stages.get(a.topic_id)) for a in page],
        limitaciones=list(LIMITATIONS),
    )


@gaps_router.get("/brechas/{tema_id}", response_model=GapOut)
def get_gap(
    tema_id: Annotated[str, Path(pattern=TOPIC_PATTERN)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    fecha_referencia: Annotated[date | None, Query()] = None,
) -> GapOut:
    with session_factory() as session:
        reader = DetectarReader(session)
        if reader.topic(tema_id, data_mode=data_mode) is None:
            raise not_found("El tema")
        report = GapService(reader).analyze_one(tema_id, data_mode=data_mode, as_of=fecha_referencia)
    if not report.analyses:
        raise not_found("Una comparación inglés–español para este tema en esa fecha")
    analysis = report.analyses[0]
    return gap_out(analysis, report.stages.get(analysis.topic_id))
