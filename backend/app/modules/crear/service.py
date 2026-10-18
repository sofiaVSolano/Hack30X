"""Servicio del laboratorio creativo: genera, regenera y consulta propuestas (RF-09, RF-10).

Orden de cada operación:

1. leer DETECTAR (sesión de solo lectura) y armar el contexto creativo;
2. generar fuera de cualquier transacción, porque con Claude puede tardar varios segundos;
3. verificar las cifras y guardar en ``crear.db`` en una sola transacción.

Regenerar usa el contexto guardado con la propuesta (los mismos hechos con los que se creó), no
una lectura nueva de DETECTAR: así todas las versiones de una propuesta son comparables.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.catalog import BATCH_APPROACHES, Approach, Platform
from app.modules.crear.context import ContextBuilder, CreativeContext, Origin
from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.generation.base import (
    CreativeParams,
    PreviousProposal,
    ProposalContent,
)
from app.modules.crear.generation.factory import Generator
from app.modules.crear.generation.verification import unsupported_figures
from app.modules.crear.storage.models import Proposal
from app.modules.crear.storage.proposals import MAX_LIMIT, ProposalRepository
from app.modules.detectar.storage.models import DataMode


class ProposalNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class BatchRequest:
    data_mode: DataMode
    origin: Origin
    params: CreativeParams
    topic_id: str | None = None
    topic_text: str | None = None
    as_of: date | None = None


# Valor de «sin cambios» en una regeneración (None ya significa «quitar» en detalle y país).
KEEP = object()


@dataclass(frozen=True)
class RegenerationRequest:
    data_mode: DataMode
    approach: Approach | None = None
    audience: str | None = None
    audience_detail: object = KEEP  # str | None | KEEP
    platform: Platform | None = None
    country: object = KEEP  # str | None | KEEP
    instruction: str | None = None


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    context: CreativeContext
    proposals: list[Proposal]


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _params(proposal: Proposal) -> CreativeParams:
    return CreativeParams(
        audiencia=proposal.audience,
        audiencia_detalle=proposal.audience_detail,
        plataforma=proposal.platform,
        pais=proposal.country,
    )


def _changes(base: Proposal, approach: Approach, params: CreativeParams, instruction: str | None) -> list[str]:
    changes = []
    if approach is not base.approach:
        changes.append("enfoque")
    if params.audiencia != base.audience or params.audiencia_detalle != base.audience_detail:
        changes.append("audiencia")
    if params.plataforma is not base.platform:
        changes.append("plataforma")
    if params.pais != base.country:
        changes.append("pais")
    if instruction:
        changes.append("indicacion")
    return changes or ["nueva_variante"]


class CreativeService:
    def __init__(
        self,
        *,
        detectar_sessions: sessionmaker[Session],
        crear_sessions: sessionmaker[Session],
        generator: Generator,
        clock: Callable[[], datetime],
    ) -> None:
        self._detectar = detectar_sessions
        self._crear = crear_sessions
        self._generator = generator
        self._clock = clock

    # --- RF-09: tres propuestas -------------------------------------------------------------

    def create_batch(self, request: BatchRequest) -> BatchResult:
        context = self._context(request)
        output = self._generator.batch(context, request.params)
        now = self._clock()
        batch_id = new_id("lot")
        stored_context = context.model_dump(mode="json")
        proposals = []
        for approach in BATCH_APPROACHES:
            content = output.contents[approach]
            proposal_id = new_id("prp")
            proposals.append(
                Proposal(
                    id=proposal_id,
                    data_mode=context.data_mode,
                    batch_id=batch_id,
                    root_id=proposal_id,
                    parent_id=None,
                    version=1,
                    origin=context.origen,
                    topic_id=context.tema_id,
                    topic_name=context.tema_nombre,
                    approach=approach,
                    audience=request.params.audiencia,
                    audience_detail=request.params.audiencia_detalle,
                    platform=request.params.plataforma,
                    country=request.params.pais,
                    instruction=None,
                    changes=[],
                    content=content.model_dump(),
                    context=stored_context,
                    engine=output.engine,
                    model=output.model,
                    engine_notice=output.notice,
                    unsupported_figures=unsupported_figures(content, context),
                    created_at=now,
                )
            )
        with self._crear() as session, session.begin():
            ProposalRepository(session).add_all(proposals)
        return BatchResult(batch_id, context, proposals)

    def _context(self, request: BatchRequest) -> CreativeContext:
        if request.origin is Origin.MANUAL:
            if not request.topic_text:
                raise ValueError("Falta el tema escrito")
            return ContextBuilder.for_manual(request.topic_text, data_mode=request.data_mode)
        if not request.topic_id:
            raise ValueError("Falta el tema de DETECTAR")
        with self._detectar() as session:
            return ContextBuilder(DetectarReader(session)).for_topic(
                request.topic_id, data_mode=request.data_mode, origin=request.origin, as_of=request.as_of
            )

    # --- RF-10: nueva versión -----------------------------------------------------------------

    def regenerate(self, proposal_id: str, request: RegenerationRequest) -> Proposal:
        with self._crear() as session:
            repo = ProposalRepository(session)
            base = repo.get(proposal_id, data_mode=request.data_mode)
            if base is None:
                raise ProposalNotFoundError(proposal_id)
            next_version = repo.last_version(base.root_id, data_mode=request.data_mode) + 1
        old_params = _params(base)
        params = CreativeParams(
            audiencia=request.audience or old_params.audiencia,
            audiencia_detalle=old_params.audiencia_detalle if request.audience_detail is KEEP else request.audience_detail,
            plataforma=request.platform or old_params.plataforma,
            pais=old_params.pais if request.country is KEEP else request.country,
        )
        approach = request.approach or base.approach
        context = CreativeContext.model_validate(base.context)
        previous = PreviousProposal(base.approach, old_params, ProposalContent.model_validate(base.content), base.version)
        output = self._generator.regenerate(context, previous, approach, params, request.instruction, next_version)
        content = output.contents[approach]
        with self._crear() as session, session.begin():
            repo = ProposalRepository(session)
            proposal = Proposal(
                id=new_id("prp"),
                data_mode=base.data_mode,
                batch_id=base.batch_id,
                root_id=base.root_id,
                parent_id=base.id,
                # Se recalcula aquí por si otra versión se guardó mientras se generaba esta.
                version=repo.last_version(base.root_id, data_mode=base.data_mode) + 1,
                origin=base.origin,
                topic_id=base.topic_id,
                topic_name=base.topic_name,
                approach=approach,
                audience=params.audiencia,
                audience_detail=params.audiencia_detalle,
                platform=params.plataforma,
                country=params.pais,
                instruction=request.instruction,
                changes=_changes(base, approach, params, request.instruction),
                content=content.model_dump(),
                context=base.context,
                engine=output.engine,
                model=output.model,
                engine_notice=output.notice,
                unsupported_figures=unsupported_figures(content, context),
                created_at=self._clock(),
            )
            repo.add_all([proposal])
        return proposal

    # --- consultas ----------------------------------------------------------------------------

    def get(self, proposal_id: str, *, data_mode: DataMode) -> tuple[Proposal, list[Proposal]]:
        with self._crear() as session:
            repo = ProposalRepository(session)
            proposal = repo.get(proposal_id, data_mode=data_mode)
            if proposal is None:
                raise ProposalNotFoundError(proposal_id)
            return proposal, repo.lineage(proposal.root_id, data_mode=data_mode)

    def batch(self, batch_id: str, *, data_mode: DataMode) -> tuple[list[Proposal], CreativeContext]:
        """Todas las propuestas y versiones de un lote, y el contexto con que se crearon."""
        with self._crear() as session:
            items = ProposalRepository(session).list(data_mode=data_mode, batch_id=batch_id, limit=MAX_LIMIT)
        if not items:
            raise ProposalNotFoundError(batch_id)
        return items, CreativeContext.model_validate(items[-1].context)

    def list(
        self,
        *,
        data_mode: DataMode,
        topic_id: str | None = None,
        batch_id: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[Proposal], int]:
        with self._crear() as session:
            repo = ProposalRepository(session)
            items = repo.list(data_mode=data_mode, topic_id=topic_id, batch_id=batch_id, limit=limit, offset=offset)
            return items, repo.count(data_mode=data_mode, topic_id=topic_id, batch_id=batch_id)
