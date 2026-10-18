"""Propuestas de contenido: generar tres (RF-09), regenerar una (RF-10) y consultarlas.

Escriben solo en la base de CREAR. Las solicitudes son síncronas: con Claude, generar puede
tardar varios segundos; con plantillas, es inmediato.
"""

import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.modules.crear.api.dependencies import (
    get_clock,
    get_creative_service,
    require_admin,
)
from app.modules.crear.api.errors import CrearError, invalid, not_found
from app.modules.crear.api.schemas import (
    BATCH_PATTERN,
    PROPOSAL_PATTERN,
    TOPIC_PATTERN,
    BatchIn,
    BatchOut,
    Mode,
    ProposalDetail,
    ProposalOut,
    ProposalPage,
    RegenerationIn,
    proposal_out,
)
from app.modules.crear.context import (
    CreativeContext,
    NoGapAnalysisError,
    TopicNotFoundError,
)
from app.modules.crear.export.pdf import PdfUnavailableError, batch_pdf
from app.modules.crear.generation.base import CreativeParams
from app.modules.crear.service import (
    KEEP,
    BatchRequest,
    CreativeService,
    ProposalNotFoundError,
    RegenerationRequest,
)
from app.modules.detectar.storage.models import DataMode

proposals_router = APIRouter(tags=["crear"], dependencies=[Depends(require_admin)])

PROPOSAL_ID = Annotated[str, Path(pattern=PROPOSAL_PATTERN)]


@proposals_router.post("/propuestas", response_model=BatchOut, status_code=201)
def create_batch(
    body: BatchIn,
    service: Annotated[CreativeService, Depends(get_creative_service)],
) -> BatchOut:
    """Tres propuestas (educativa, controversial y narrativa) para un tema o una brecha."""
    request = BatchRequest(
        data_mode=DataMode(body.data_mode),
        origin=body.origen,
        topic_id=body.tema_id,
        topic_text=body.tema_texto,
        as_of=body.fecha_referencia,
        params=CreativeParams(
            audiencia=body.audiencia,
            audiencia_detalle=body.audiencia_detalle,
            plataforma=body.plataforma,
            pais=body.pais,
        ),
    )
    try:
        result = service.create_batch(request)
    except TopicNotFoundError:
        raise not_found("El tema") from None
    except NoGapAnalysisError:
        raise invalid(
            "El tema no tiene una comparación inglés–español en esa fecha; elija el origen «tema».", "body.origen"
        ) from None
    return BatchOut(
        lote_id=result.batch_id,
        data_mode=result.context.data_mode,
        contexto=result.context,
        propuestas=[proposal_out(p) for p in result.proposals],
    )


@proposals_router.post("/propuestas/{propuesta_id}/regeneraciones", response_model=ProposalOut, status_code=201)
def regenerate(
    propuesta_id: PROPOSAL_ID,
    body: RegenerationIn,
    service: Annotated[CreativeService, Depends(get_creative_service)],
) -> ProposalOut:
    """Nueva versión con otro enfoque, audiencia, plataforma o país. La anterior no cambia."""
    sent = body.model_fields_set
    request = RegenerationRequest(
        data_mode=DataMode(body.data_mode),
        approach=body.enfoque,
        audience=body.audiencia,
        audience_detail=body.audiencia_detalle if "audiencia_detalle" in sent else KEEP,
        platform=body.plataforma,
        country=body.pais if "pais" in sent else KEEP,
        instruction=body.indicacion,
    )
    try:
        proposal = service.regenerate(propuesta_id, request)
    except ProposalNotFoundError:
        raise not_found("La propuesta") from None
    return proposal_out(proposal)


@proposals_router.get("/propuestas", response_model=ProposalPage)
def list_proposals(
    service: Annotated[CreativeService, Depends(get_creative_service)],
    data_mode: Annotated[Mode, Query()] = "real",
    tema_id: Annotated[str | None, Query(pattern=TOPIC_PATTERN)] = None,
    lote_id: Annotated[str | None, Query(pattern=BATCH_PATTERN)] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 30,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> ProposalPage:
    mode = DataMode(data_mode)
    items, total = service.list(data_mode=mode, topic_id=tema_id, batch_id=lote_id, limit=limite, offset=desplazamiento)
    return ProposalPage(
        data_mode=mode,
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=[proposal_out(p) for p in items],
    )


@proposals_router.get("/propuestas/{propuesta_id}", response_model=ProposalDetail)
def get_proposal(
    propuesta_id: PROPOSAL_ID,
    service: Annotated[CreativeService, Depends(get_creative_service)],
    data_mode: Annotated[Mode, Query()] = "real",
) -> ProposalDetail:
    """Una propuesta, todas las versiones de su historial y el contexto con que se creó."""
    try:
        proposal, lineage = service.get(propuesta_id, data_mode=DataMode(data_mode))
    except ProposalNotFoundError:
        raise not_found("La propuesta") from None
    return ProposalDetail(
        propuesta=proposal_out(proposal),
        versiones=[proposal_out(p) for p in lineage],
        contexto=CreativeContext.model_validate(proposal.context),
    )


def _filename(topic: str, batch_id: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:50].strip("-") or "tema"
    return f"propuestas-{slug}-{batch_id.removeprefix('lot_')[:8]}.pdf"


@proposals_router.get(
    "/lotes/{lote_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Documento PDF del lote"}},
)
def batch_document(
    lote_id: Annotated[str, Path(pattern=BATCH_PATTERN)],
    service: Annotated[CreativeService, Depends(get_creative_service)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    data_mode: Annotated[Mode, Query()] = "real",
) -> Response:
    """Documento PDF con las tres propuestas del lote (su versión más reciente) y los datos usados."""
    try:
        proposals, context = service.batch(lote_id, data_mode=DataMode(data_mode))
    except ProposalNotFoundError:
        raise not_found("El lote de propuestas") from None
    try:
        document = batch_pdf(proposals, context, generated_at=clock())
    except PdfUnavailableError as exc:
        raise CrearError(code="pdf_no_disponible", status=503, title="Exportación a PDF no disponible", detail=str(exc)) from None
    return Response(
        content=document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(context.tema_nombre, lote_id)}"',
            "Cache-Control": "no-store",
        },
    )
