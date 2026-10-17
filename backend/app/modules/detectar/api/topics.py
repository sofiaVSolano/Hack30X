"""Temas, alias y vínculos (E7).

Todas las rutas exigen el token administrativo. Las lecturas no escriben; la
normalización y las correcciones solo ocurren con un POST explícito. Ningún proceso se
ejecuta al importar el módulo, al iniciar la app ni al leer.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.api.dependencies import get_session_factory, require_admin
from app.modules.detectar.api.errors import DetectarError, FieldError
from app.modules.detectar.storage.models import (
    AliasKind,
    Certainty,
    DataMode,
    LinkRule,
    LinkStatus,
    Source,
    Topic,
    TopicAlias,
    TopicLink,
)
from app.modules.detectar.storage.topics import (
    ACTOR_RE,
    AliasConflictError,
    TopicNotFoundError,
    TopicRepository,
)
from app.modules.detectar.timeutil import format_utc
from app.modules.detectar.topics.linker import TopicLinker, correct_link
from app.modules.detectar.topics.normalize import RULES_VERSION

logger = logging.getLogger(__name__)

topics_router = APIRouter(tags=["detectar"], dependencies=[Depends(require_admin)])

TOPIC_ID = Annotated[str, Path(pattern=r"^tpc_[0-9a-f]{16}$")]
Mode = Literal["real", "simulated"]
Actor = Annotated[str, Field(pattern=ACTOR_RE.pattern)]
Reason = Annotated[str, Field(min_length=3, max_length=500)]


def _now() -> datetime:
    return datetime.now(UTC)


# --- modelos de salida -------------------------------------------------------------------


class AliasOut(BaseModel):
    texto: str
    normalizado: str
    tipo: AliasKind
    origen: str
    creado: str


class TopicOut(BaseModel):
    id: str
    data_mode: DataMode
    nombre: str
    clave_normalizada: str
    ambiguo: bool
    motivo_ambiguedad: str | None
    creado_por: str
    creado: str
    actualizado: str
    vinculos_por_fuente: dict[str, int]


class TopicPage(BaseModel):
    data_mode: DataMode
    total: int
    limite: int
    desplazamiento: int
    items: list[TopicOut]


class SubjectOut(BaseModel):
    fuente: str
    sujeto_original: str
    observaciones: int


class TopicDetail(BaseModel):
    tema: TopicOut
    alias: list[AliasOut]
    sujetos: list[SubjectOut]


class LinkOut(BaseModel):
    id: int
    observacion_id: int
    data_mode: DataMode
    fuente: Source
    sujeto_original: str
    candidato: str | None
    candidato_normalizado: str | None
    estado: LinkStatus
    tema_id: str | None
    regla: LinkRule
    certeza: Certainty
    origen: str
    motivo: str | None
    creado: str
    reemplazado: str | None
    reemplaza_a: int | None


class LinkPage(BaseModel):
    data_mode: DataMode
    limite: int
    desplazamiento: int
    items: list[LinkOut]


class NormalizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode  # obligatorio: sin valor por defecto
    fuente: Literal["google_trends_rss", "wikimedia", "gdelt"] | None = None
    limite: int = Field(default=500, ge=1, le=5000)


class NormalizationResult(BaseModel):
    data_mode: DataMode
    reglas: str
    procesadas: int
    temas_creados: int
    por_estado: dict[str, int]
    por_regla: dict[str, int]


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode
    accion: Literal["link", "reject", "unlink"]
    tema_id: str | None = Field(default=None, pattern=r"^tpc_[0-9a-f]{16}$")
    autor: Actor
    motivo: Reason


class AliasRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode
    texto: str = Field(min_length=2, max_length=300)
    tipo: Literal["source_label", "acronym", "variant", "manual"]
    autor: Actor


class AmbiguityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_mode: Mode
    ambiguo: bool
    autor: Actor
    motivo: Annotated[str, Field(max_length=500)] | None = None


# --- conversión --------------------------------------------------------------------------


def _topic_out(topic: Topic, counts: dict[str, int]) -> TopicOut:
    return TopicOut(
        id=topic.id,
        data_mode=topic.data_mode,
        nombre=topic.canonical_name,
        clave_normalizada=topic.normalized_key,
        ambiguo=topic.ambiguous,
        motivo_ambiguedad=topic.ambiguous_reason,
        creado_por=topic.created_by,
        creado=format_utc(topic.created_at),
        actualizado=format_utc(topic.updated_at),
        vinculos_por_fuente=counts,
    )


def _alias_out(alias: TopicAlias) -> AliasOut:
    return AliasOut(
        texto=alias.alias_text,
        normalizado=alias.normalized_alias,
        tipo=alias.kind,
        origen=alias.origin,
        creado=format_utc(alias.created_at),
    )


def _link_out(link: TopicLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        observacion_id=link.observation_id,
        data_mode=link.data_mode,
        fuente=link.source,
        sujeto_original=link.subject_ref,
        candidato=link.candidate_text,
        candidato_normalizado=link.normalized_candidate,
        estado=link.status,
        tema_id=link.topic_id,
        regla=link.rule,
        certeza=link.certainty,
        origen=link.origin,
        motivo=link.reason,
        creado=format_utc(link.created_at),
        reemplazado=format_utc(link.superseded_at) if link.superseded_at else None,
        reemplaza_a=link.supersedes_id,
    )


def _not_found(what: str) -> DetectarError:
    return DetectarError(code="not_found", status=404, title="No encontrado", detail=f"{what} no existe.")


def _invalid(detail: str, field: str) -> DetectarError:
    return DetectarError(
        code="invalid_operation",
        status=422,
        title="Operación no válida",
        detail=detail,
        errors=[FieldError(campo=field, mensaje=detail)],
    )


# --- normalización (escritura explícita) ---------------------------------------------------


@topics_router.post("/temas/normalizaciones", response_model=NormalizationResult)
def run_normalization(
    body: NormalizationRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> NormalizationResult:
    """Vincula observaciones sin vínculo vigente. Idempotente; síncrono."""
    with session_factory() as session, session.begin():
        report = TopicLinker(session).process(
            data_mode=body.data_mode,
            source=Source(body.fuente) if body.fuente else None,
            limit=body.limite,
        )
    return NormalizationResult(
        data_mode=report.data_mode,
        reglas=RULES_VERSION,
        procesadas=report.processed,
        temas_creados=report.topics_created,
        por_estado=dict(report.by_status),
        por_regla=dict(report.by_rule),
    )


# --- vínculos ------------------------------------------------------------------------------


@topics_router.get("/temas/vinculos", response_model=LinkPage)
def list_links(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    estado: Annotated[LinkStatus | None, Query()] = None,
    fuente: Annotated[Source | None, Query()] = None,
    tema_id: Annotated[str | None, Query(pattern=r"^tpc_[0-9a-f]{16}$")] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> LinkPage:
    """Vínculos vigentes. ``estado=needs_review`` es la cola de revisión."""
    with session_factory() as session:
        links = TopicRepository(session).list_links(
            data_mode=data_mode,
            status=estado,
            source=fuente,
            topic_id=tema_id,
            limit=limite,
            offset=desplazamiento,
        )
        return LinkPage(
            data_mode=DataMode(data_mode),
            limite=limite,
            desplazamiento=desplazamiento,
            items=[_link_out(link) for link in links],
        )


@topics_router.get("/temas/observaciones/{observation_id}/vinculos", response_model=list[LinkOut])
def observation_link_history(
    observation_id: Annotated[int, Path(ge=1)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
) -> list[LinkOut]:
    """Historial completo (vigente y reemplazados) de una observación."""
    with session_factory() as session:
        history = TopicRepository(session).link_history(observation_id, data_mode=data_mode)
        if not history:
            raise _not_found("La observación no tiene vínculos en ese data_mode o")
        return [_link_out(link) for link in history]


@topics_router.post("/temas/vinculos/{link_id}/correccion", response_model=LinkOut)
def correct(
    link_id: Annotated[int, Path(ge=1)],
    body: CorrectionRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> LinkOut:
    """Crea un vínculo nuevo con la decisión manual; el anterior queda como reemplazado."""
    try:
        with session_factory() as session, session.begin():
            link = correct_link(
                session,
                link_id,
                data_mode=body.data_mode,
                action=body.accion,
                actor=body.autor,
                reason=body.motivo,
                topic_id=body.tema_id,
                now=_now(),
            )
            return _link_out(link)
    except TopicNotFoundError:
        raise _not_found("El tema indicado") from None
    except LookupError:
        raise _not_found("El vínculo") from None
    except ValueError as exc:
        raise _invalid(str(exc), "body") from None


# --- temas ---------------------------------------------------------------------------------


@topics_router.get("/temas", response_model=TopicPage)
def list_topics(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> TopicPage:
    with session_factory() as session:
        repo = TopicRepository(session)
        topics = repo.list_topics(data_mode=data_mode, query=q, limit=limite, offset=desplazamiento)
        counts = repo.linked_counts([t.id for t in topics], data_mode=data_mode)
        return TopicPage(
            data_mode=DataMode(data_mode),
            total=repo.count_topics(data_mode=data_mode, query=q),
            limite=limite,
            desplazamiento=desplazamiento,
            items=[_topic_out(t, counts.get(t.id, {})) for t in topics],
        )


@topics_router.get("/temas/{topic_id}", response_model=TopicDetail)
def get_topic(
    topic_id: TOPIC_ID,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    data_mode: Annotated[Mode, Query()] = "real",
) -> TopicDetail:
    with session_factory() as session:
        repo = TopicRepository(session)
        topic = repo.get_topic(topic_id, data_mode=data_mode)
        if topic is None:
            raise _not_found("El tema")
        counts = repo.linked_counts([topic.id], data_mode=data_mode)
        return TopicDetail(
            tema=_topic_out(topic, counts.get(topic.id, {})),
            alias=[_alias_out(a) for a in repo.list_aliases(topic.id, data_mode=data_mode)],
            sujetos=[
                SubjectOut(fuente=f, sujeto_original=ref, observaciones=n)
                for f, ref, n in repo.subjects_for_topic(topic.id, data_mode=data_mode)
            ],
        )


@topics_router.post("/temas/{topic_id}/alias", response_model=AliasOut, status_code=201)
def add_alias(
    topic_id: TOPIC_ID,
    body: AliasRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> AliasOut:
    """Registra un alias. No re-vincula observaciones ya procesadas (ver limitaciones)."""
    try:
        with session_factory() as session, session.begin():
            alias, _created = TopicRepository(session).add_alias(
                topic_id,
                body.texto,
                data_mode=body.data_mode,
                kind=AliasKind(body.tipo),
                origin=f"manual:{body.autor}",
                now=_now(),
            )
            return _alias_out(alias)
    except TopicNotFoundError:
        raise _not_found("El tema") from None
    except AliasConflictError as exc:
        raise DetectarError(
            code="alias_conflict", status=409, title="Alias en uso", detail=str(exc)
        ) from None
    except ValueError as exc:
        raise _invalid(str(exc), "body.texto") from None


@topics_router.post("/temas/{topic_id}/ambiguedad", response_model=TopicOut)
def set_ambiguity(
    topic_id: TOPIC_ID,
    body: AmbiguityRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> TopicOut:
    """Marca o desmarca un tema como ambiguo: las nuevas coincidencias irán a revisión."""
    try:
        with session_factory() as session, session.begin():
            repo = TopicRepository(session)
            topic = repo.set_ambiguous(
                topic_id,
                data_mode=body.data_mode,
                ambiguous=body.ambiguo,
                actor=body.autor,
                reason=body.motivo,
                now=_now(),
            )
            counts = repo.linked_counts([topic.id], data_mode=body.data_mode)
            return _topic_out(topic, counts.get(topic.id, {}))
    except TopicNotFoundError:
        raise _not_found("El tema") from None
    except ValueError as exc:
        raise _invalid(str(exc), "body.motivo") from None
