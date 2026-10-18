"""Temas de DETECTAR disponibles para crear, con su etapa y su veredicto de brechas.

Solo lectura: no normaliza, no recalcula y no escribe nada en DETECTAR.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.api.dependencies import require_admin
from app.modules.crear.api.schemas import Mode, TopicOut, TopicPage, stage_out
from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.gaps.service import GapService
from app.modules.detectar.api.dependencies import get_session_factory
from app.modules.detectar.storage.models import DataMode

topics_router = APIRouter(tags=["crear"], dependencies=[Depends(require_admin)])


@topics_router.get("/temas", response_model=TopicPage)
def list_topics(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> TopicPage:
    mode = DataMode(data_mode)
    with session_factory() as session:
        reader = DetectarReader(session)
        topics, total = reader.topics(data_mode=mode, query=q, limit=limite, offset=desplazamiento)
        ids = [t.id for t in topics]
        stages = reader.current_stages(ids, data_mode=mode)
        report = GapService(reader).analyze(data_mode=mode, topic_ids=ids) if ids else None
    verdicts = {a.topic_id: a.verdict for a in report.analyses} if report else {}
    return TopicPage(
        data_mode=mode,
        fecha_referencia=report.as_of if report else None,
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=[
            TopicOut(
                id=t.id,
                nombre=t.name,
                data_mode=t.data_mode,
                ambiguo=t.ambiguous,
                vinculos_por_fuente=t.links_by_source,
                etapa=stage_out(stages.get(t.id)),
                veredicto_brecha=verdicts.get(t.id),
            )
            for t in topics
        ],
    )
