"""Modelos SQLAlchemy de DETECTAR (E2): recolecciones y observaciones originales.

Reglas de integridad que garantiza la propia base de datos:

- ``data_mode`` viaja en cada tabla y las claves foráneas compuestas obligan a que una
  ejecución por fuente y sus observaciones tengan el mismo modo que su recolección.
- YouTube nunca se guarda en ``raw_observations``; solo puede aparecer como metadato
  operativo en ``source_runs``.
- Una observación simulada siempre lleva ``dataset_id``; una real nunca.
- La identidad de una observación usa un índice único sobre expresiones con ``COALESCE``,
  porque un ``UNIQUE`` normal en SQLite trata cada ``NULL`` como distinto.
- (E7) ``topic_links`` vincula observaciones con temas sin modificar ``raw_observations``;
  un vínculo nunca se edita ni se borra: una corrección crea otro y reemplaza al anterior.
- (E3) ``agent_runs`` solo admite combinaciones coherentes de estado, fechas, resultado y
  error, y un trigger impide transiciones de estado inválidas o modificar una ejecución
  terminada.
"""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator


class DataMode(StrEnum):
    REAL = "real"
    SIMULATED = "simulated"


class Source(StrEnum):
    GOOGLE_TRENDS_RSS = "google_trends_rss"
    WIKIMEDIA = "wikimedia"
    GDELT = "gdelt"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    X = "x"


# Fuentes cuyas observaciones pueden almacenarse. YouTube queda fuera por sus políticas.
STORABLE_SOURCES = frozenset(Source) - {Source.YOUTUBE}


class CollectionTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class CollectionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceRunStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_UNCONFIGURED = "skipped_unconfigured"
    SKIPPED_BUDGET = "skipped_budget"


class Unit(StrEnum):
    VIEWS = "views"
    SEARCHES_LOWER_BOUND = "searches_lower_bound"
    PRESENCE = "presence"
    PCT_OF_COVERAGE = "pct_of_coverage"
    ARTICLES = "articles"
    POSTS = "posts"
    RANK = "rank"


class Granularity(StrEnum):
    SNAPSHOT = "snapshot"
    HOUR = "hour"
    DAY = "day"


class CountryBasis(StrEnum):
    REPORTED_BY_SOURCE = "reported_by_source"
    PUBLISHER_COUNTRY = "publisher_country"
    NONE = "none"


class LanguageBasis(StrEnum):
    REPORTED_BY_SOURCE = "reported_by_source"
    QUERY_FILTER = "query_filter"
    NONE = "none"


class SubjectType(StrEnum):
    SEARCH_TERM = "search_term"
    WIKI_ARTICLE = "wiki_article"
    NEWS_QUERY = "news_query"
    HASHTAG = "hashtag"
    TREND_NAME = "trend_name"


class AgentRunStatus(StrEnum):
    """Estado de una ejecución de agente. ``completed``, ``failed`` y ``blocked`` son finales."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


AGENT_RUN_TERMINAL_STATUSES = frozenset(
    {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.BLOCKED}
)

# Única fuente de verdad de las transiciones: la usan el código Python y el trigger SQL.
AGENT_RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.PENDING: frozenset(
        {AgentRunStatus.RUNNING, AgentRunStatus.BLOCKED, AgentRunStatus.FAILED}
    ),
    AgentRunStatus.RUNNING: frozenset(
        {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.BLOCKED}
    ),
    AgentRunStatus.COMPLETED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.BLOCKED: frozenset(),
}


class AliasKind(StrEnum):
    CANONICAL = "canonical"  # forma del nombre del tema
    SOURCE_LABEL = "source_label"  # etiqueta tal como aparece en una fuente
    ACRONYM = "acronym"
    VARIANT = "variant"  # variante ortográfica
    MANUAL = "manual"


class LinkStatus(StrEnum):
    LINKED = "linked"  # vinculada a un tema
    NEEDS_REVIEW = "needs_review"  # posible coincidencia: requiere revisión humana
    UNLINKED = "unlinked"  # no se pudo generar un candidato fiable
    REJECTED = "rejected"  # revisada: no corresponde a ningún tema


class LinkRule(StrEnum):
    EXACT_NORMALIZED = "exact_normalized"  # texto normalizado = clave canónica del tema
    ALIAS = "alias"  # texto normalizado = alias registrado (no canónico)
    NEW_TOPIC = "new_topic"  # sin relación conocida: se creó un tema nuevo
    MANUAL_PRECEDENT = "manual_precedent"  # repite una corrección manual del mismo sujeto
    AMBIGUOUS_TOPIC = "ambiguous_topic"  # coincide con un tema marcado como ambiguo
    DISAMBIGUATION_BASE = "disambiguation_base"  # "X (algo)" de Wikipedia coincide con "X"
    INSUFFICIENT_DATA = "insufficient_data"
    MANUAL_CORRECTION = "manual_correction"


class Certainty(StrEnum):
    """Categoría de certeza que la regla puede justificar. No es un porcentaje."""

    EXACT = "exact"
    ALIAS = "alias"
    MANUAL = "manual"
    NONE = "none"


class MetricStatus(StrEnum):
    OK = "ok"  # calculada con datos suficientes
    INSUFFICIENT = "insufficient"  # no se pudo calcular: el motivo queda registrado


class MetricUnit(StrEnum):
    """Unidades de métricas. Nunca se combinan entre sí ni entre fuentes."""

    CAPTURES = "captures"  # capturas RSS
    RATIO = "ratio"  # fracción entre 0 y 1
    RATIO_DIFFERENCE = "ratio_difference"  # diferencia de fracciones (no es una tasa)
    SEARCHES_LOWER_BOUND = "searches_lower_bound"  # cota inferior informada por Google
    VIEWS = "views"
    VIEWS_PER_DAY = "views_per_day"
    ARTICLES = "articles"
    ARTICLES_PER_DAY = "articles_per_day"
    GROWTH_RATE = "growth_rate"  # (actual - anterior) / anterior, como fracción
    GROWTH_RATE_DIFFERENCE = "growth_rate_difference"  # diferencia entre dos tasas
    COUNTRIES = "countries"


class TrendStage(StrEnum):
    EMERGENTE = "emergente"
    ACELERANDO = "acelerando"
    PUNTO_MAXIMO = "punto_maximo"
    SATURADA = "saturada"  # existe en el modelo; stages-v1 no la asigna
    DATOS_INSUFICIENTES = "datos_insuficientes"


class EvidenceRole(StrEnum):
    PRIMARY = "primary"  # fuente validada que puede determinar la etapa
    COMPLEMENTARY = "complementary"  # fuente no validada: solo se informa
    EXCLUDED = "excluded"  # no aporta (sin métricas utilizables, contradictoria, etc.)


class AgentRunTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    COORDINATOR = "coordinator"


class UTCDateTime(TypeDecorator[datetime]):
    """Fecha y hora que exige zona horaria al guardar y se devuelve siempre en UTC.

    SQLite no conserva la zona horaria, así que se guarda como UTC sin zona y se
    vuelve a marcar como UTC al leer.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Las fechas deben incluir zona horaria")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # Se guarda el valor (no el nombre) y se crea un CHECK en la base de datos.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=32,
    )


class Base(DeclarativeBase):
    pass


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        # Destino de las claves foráneas compuestas (id, data_mode).
        UniqueConstraint("id", "data_mode", name="uq_collection_runs_id_mode"),
        Index("ix_collection_runs_mode_created", "data_mode", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    trigger: Mapped[CollectionTrigger] = mapped_column(_enum(CollectionTrigger, "collection_trigger"))
    status: Mapped[CollectionStatus] = mapped_column(_enum(CollectionStatus, "collection_status"))
    requested_sources: Mapped[list[str]] = mapped_column(JSON)
    requested_countries: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # (E5) Parámetros explícitos de la solicitud (por ejemplo, el intervalo de Wikimedia).
    # Puede ser NULL en recolecciones creadas antes de E5.
    request_params: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))

    source_runs: Mapped[list["SourceRun"]] = relationship(
        back_populates="collection_run",
        order_by="SourceRun.source",
    )


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_run_id", "data_mode"],
            ["collection_runs.id", "collection_runs.data_mode"],
            name="fk_source_runs_collection_mode",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("collection_run_id", "source", name="uq_source_runs_run_source"),
        UniqueConstraint("id", "data_mode", name="uq_source_runs_id_mode"),
        CheckConstraint("http_calls >= 0", name="ck_source_runs_http_calls"),
        CheckConstraint("items >= 0", name="ck_source_runs_items"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_source_runs_cost"),
        Index("ix_source_runs_mode_source_started", "data_mode", "source", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    collection_run_id: Mapped[str] = mapped_column(String(36))
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[SourceRunStatus] = mapped_column(_enum(SourceRunStatus, "source_run_status"))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    http_calls: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(500))

    collection_run: Mapped[CollectionRun] = relationship(back_populates="source_runs")


class RawObservation(Base):
    __tablename__ = "raw_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_run_id", "data_mode"],
            ["source_runs.id", "source_runs.data_mode"],
            name="fk_raw_observations_source_run_mode",
            ondelete="RESTRICT",
        ),
        CheckConstraint("source <> 'youtube'", name="ck_raw_observations_no_youtube"),
        CheckConstraint(
            "value IS NOT NULL OR value_text IS NOT NULL", name="ck_raw_observations_has_value"
        ),
        CheckConstraint(
            "period_end IS NULL OR period_end >= period_start", name="ck_raw_observations_period"
        ),
        CheckConstraint(
            "country IS NULL OR (length(country) = 2 AND country = upper(country))",
            name="ck_raw_observations_country_format",
        ),
        CheckConstraint(
            "(country IS NULL) = (country_basis = 'none')", name="ck_raw_observations_country_basis"
        ),
        CheckConstraint(
            "(language IS NULL) = (language_basis = 'none')",
            name="ck_raw_observations_language_basis",
        ),
        CheckConstraint(
            "(data_mode = 'simulated') = (dataset_id IS NOT NULL)",
            name="ck_raw_observations_dataset_id",
        ),
        Index(
            "ix_raw_observations_lookup",
            "data_mode",
            "source",
            "metric_key",
            "country",
            "period_start",
        ),
        Index("ix_raw_observations_subject", "data_mode", "subject_ref"),
        # (E7) Destino de claves foráneas compuestas (id, data_mode) desde topic_links.
        Index("uq_raw_observations_id_mode", "id", "data_mode", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_run_id: Mapped[str] = mapped_column(String(36))
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    metric_key: Mapped[str] = mapped_column(String(64))
    unit: Mapped[Unit] = mapped_column(_enum(Unit, "unit"))
    value: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(64))
    # Tres fechas con significados distintos:
    # - observed_at: cuándo se consultó la fuente;
    # - period_start/period_end: periodo al que corresponde la métrica (p. ej., un día de visitas);
    # - source_published_at (E5): fecha de publicación original que informa la fuente, si existe.
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    granularity: Mapped[Granularity] = mapped_column(_enum(Granularity, "granularity"))
    country: Mapped[str | None] = mapped_column(String(2))
    country_basis: Mapped[CountryBasis] = mapped_column(_enum(CountryBasis, "country_basis"))
    language: Mapped[str | None] = mapped_column(String(35))
    language_basis: Mapped[LanguageBasis] = mapped_column(_enum(LanguageBasis, "language_basis"))
    subject_type: Mapped[SubjectType] = mapped_column(_enum(SubjectType, "subject_type"))
    subject_ref: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(Text)
    dataset_id: Mapped[str | None] = mapped_column(String(64))
    raw_excerpt: Mapped[dict[str, object] | None] = mapped_column(JSON)


class AgentRun(Base):
    """Una ejecución de un agente de la oficina.

    La definición del agente (nombre, responsabilidad, permisos) vive en código
    declarativo; aquí solo se registra lo que realmente ocurrió en cada ejecución.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        # Si la ejecución está ligada a una recolección, ambas deben tener el mismo modo.
        ForeignKeyConstraint(
            ["collection_run_id", "data_mode"],
            ["collection_runs.id", "collection_runs.data_mode"],
            name="fk_agent_runs_collection_mode",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL "
            "  AND result IS NULL AND error_code IS NULL AND error_detail IS NULL)"
            " OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL "
            "  AND result IS NULL AND error_code IS NULL AND error_detail IS NULL)"
            " OR (status = 'completed' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "  AND result IS NOT NULL AND error_code IS NULL AND error_detail IS NULL)"
            " OR (status IN ('failed', 'blocked') AND finished_at IS NOT NULL "
            "  AND result IS NULL AND error_code IS NOT NULL AND error_detail IS NOT NULL)",
            name="ck_agent_runs_state_consistency",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_agent_runs_period",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= requested_at", name="ck_agent_runs_started"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= requested_at", name="ck_agent_runs_finished"
        ),
        Index("ix_agent_runs_mode_agent_requested", "data_mode", "agent_id", "requested_at"),
        Index("ix_agent_runs_mode_status", "data_mode", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    trigger: Mapped[AgentRunTrigger] = mapped_column(_enum(AgentRunTrigger, "agent_run_trigger"))
    status: Mapped[AgentRunStatus] = mapped_column(_enum(AgentRunStatus, "agent_run_status"))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    collection_run_id: Mapped[str | None] = mapped_column(String(36))
    params: Mapped[dict[str, object]] = mapped_column(JSON)
    # none_as_null: un resultado ausente se guarda como NULL de SQL, no como JSON "null".
    result: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(String(500))


def _agent_run_transition_sql() -> str:
    allowed = " OR ".join(
        f"(OLD.status = '{old.value}' AND NEW.status IN ({', '.join(repr(n.value) for n in sorted(new))}))"
        for old, new in AGENT_RUN_TRANSITIONS.items()
        if new
    )
    return allowed


event.listen(
    AgentRun.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_agent_runs_status_transition "
        "BEFORE UPDATE OF status ON agent_runs "
        f"WHEN OLD.status <> NEW.status AND NOT ({_agent_run_transition_sql()}) "
        "BEGIN SELECT RAISE(ABORT, 'agent_runs: transicion de estado invalida'); END"
    ),
)

event.listen(
    AgentRun.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_agent_runs_terminal_immutable "
        "BEFORE UPDATE ON agent_runs "
        "WHEN OLD.status IN ('completed', 'failed', 'blocked') "
        "BEGIN SELECT RAISE(ABORT, 'agent_runs: una ejecucion terminada no se modifica'); END"
    ),
)


# --- E7: temas, alias y vínculos ---------------------------------------------------------


class Topic(Base):
    """Tema normalizado. Su id se deriva de (data_mode, clave): es estable entre reconstrucciones."""

    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("data_mode", "normalized_key", name="uq_topics_mode_key"),
        UniqueConstraint("id", "data_mode", name="uq_topics_id_mode"),
        CheckConstraint(
            "(ambiguous = 0 AND ambiguous_reason IS NULL AND ambiguous_marked_by IS NULL"
            " AND ambiguous_marked_at IS NULL)"
            " OR (ambiguous = 1 AND ambiguous_reason IS NOT NULL"
            " AND ambiguous_marked_by IS NOT NULL AND ambiguous_marked_at IS NOT NULL)",
            name="ck_topics_ambiguous",
        ),
        CheckConstraint("length(normalized_key) >= 2", name="ck_topics_key_length"),
        Index("ix_topics_mode_name", "data_mode", "canonical_name"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    canonical_name: Mapped[str] = mapped_column(String(300))
    normalized_key: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    ambiguous_reason: Mapped[str | None] = mapped_column(String(500))
    ambiguous_marked_by: Mapped[str | None] = mapped_column(String(80))
    ambiguous_marked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TopicAlias(Base):
    """Expresión que remite a un tema. Una forma normalizada apunta a un solo tema por modo."""

    __tablename__ = "topic_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "data_mode"],
            ["topics.id", "topics.data_mode"],
            name="fk_topic_aliases_topic_mode",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("data_mode", "normalized_alias", name="uq_topic_aliases_mode_alias"),
        CheckConstraint("length(normalized_alias) >= 2", name="ck_topic_aliases_length"),
        Index("ix_topic_aliases_topic", "topic_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[str] = mapped_column(String(20))
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    alias_text: Mapped[str] = mapped_column(String(300))
    normalized_alias: Mapped[str] = mapped_column(String(300))
    kind: Mapped[AliasKind] = mapped_column(_enum(AliasKind, "alias_kind"))
    origin: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TopicLink(Base):
    """Asociación entre una observación original y un tema, con su procedencia."""

    __tablename__ = "topic_links"
    __table_args__ = (
        # Observación y tema deben pertenecer al mismo data_mode que el vínculo.
        ForeignKeyConstraint(
            ["observation_id", "data_mode"],
            ["raw_observations.id", "raw_observations.data_mode"],
            name="fk_topic_links_observation_mode",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["topic_id", "data_mode"],
            ["topics.id", "topics.data_mode"],
            name="fk_topic_links_topic_mode",
            ondelete="RESTRICT",
        ),
        # Un vínculo de corrección apunta al que reemplaza (cadena de trazabilidad).
        ForeignKeyConstraint(
            ["supersedes_id"], ["topic_links.id"], name="fk_topic_links_supersedes"
        ),
        CheckConstraint(
            "(status = 'linked' AND topic_id IS NOT NULL)"
            " OR (status IN ('unlinked', 'rejected') AND topic_id IS NULL)"
            " OR status = 'needs_review'",
            name="ck_topic_links_status_topic",
        ),
        CheckConstraint(
            "(rule = 'manual_correction') = (supersedes_id IS NOT NULL)",
            name="ck_topic_links_supersedes_only_corrections",
        ),
        # Cada vínculo puede ser reemplazado una sola vez.
        Index("uq_topic_links_supersedes", "supersedes_id", unique=True),
        CheckConstraint(
            "(rule IN ('manual_correction', 'manual_precedent')) = (certainty = 'manual')",
            name="ck_topic_links_manual_certainty",
        ),
        # Un solo vínculo vigente por observación.
        Index(
            "uq_topic_links_current_observation",
            "observation_id",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
        Index("ix_topic_links_topic", "data_mode", "topic_id"),
        Index("ix_topic_links_status", "data_mode", "status"),
        Index("ix_topic_links_subject", "data_mode", "source", "subject_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observation_id: Mapped[int] = mapped_column(Integer)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    # Copias de la observación para consultar sin unir tablas; no la sustituyen.
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    subject_ref: Mapped[str] = mapped_column(String(500))
    candidate_text: Mapped[str | None] = mapped_column(String(500))
    normalized_candidate: Mapped[str | None] = mapped_column(String(300))
    topic_id: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[LinkStatus] = mapped_column(_enum(LinkStatus, "link_status"))
    rule: Mapped[LinkRule] = mapped_column(_enum(LinkRule, "link_rule"))
    certainty: Mapped[Certainty] = mapped_column(_enum(Certainty, "certainty"))
    # "normalizer:topics-v1" o "manual:<autor>".
    origin: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Se fija cuando otro vínculo lo reemplaza; es el único campo que puede cambiar.
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    supersedes_id: Mapped[int | None] = mapped_column(Integer)


# Un vínculo no se borra y solo admite, una vez, el registro de su reemplazo.
event.listen(
    TopicLink.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_topic_links_append_only "
        "BEFORE UPDATE ON topic_links "
        "WHEN OLD.superseded_at IS NOT NULL "
        "OR NEW.observation_id IS NOT OLD.observation_id OR NEW.data_mode IS NOT OLD.data_mode "
        "OR NEW.source IS NOT OLD.source OR NEW.subject_ref IS NOT OLD.subject_ref "
        "OR NEW.candidate_text IS NOT OLD.candidate_text "
        "OR NEW.normalized_candidate IS NOT OLD.normalized_candidate "
        "OR NEW.topic_id IS NOT OLD.topic_id OR NEW.status IS NOT OLD.status "
        "OR NEW.rule IS NOT OLD.rule OR NEW.certainty IS NOT OLD.certainty "
        "OR NEW.origin IS NOT OLD.origin OR NEW.reason IS NOT OLD.reason "
        "OR NEW.created_at IS NOT OLD.created_at "
        "OR NEW.supersedes_id IS NOT OLD.supersedes_id "
        "BEGIN SELECT RAISE(ABORT, 'topic_links: un vinculo solo puede marcarse como reemplazado'); END"
    ),
)
event.listen(
    TopicLink.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_topic_links_no_delete BEFORE DELETE ON topic_links "
        "BEGIN SELECT RAISE(ABORT, 'topic_links: los vinculos no se borran'); END"
    ),
)


# --- E8: métricas por tema y fuente ----------------------------------------------------


class RulesVersion(Base):
    """Parámetros exactos de una versión de reglas de métricas (inmutable)."""

    __tablename__ = "rules_versions"

    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    params: Mapped[dict[str, object]] = mapped_column(JSON)
    params_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MetricValue(Base):
    """Valor calculado (derivado y recalculable) de una métrica para un tema y una fuente."""

    __tablename__ = "metric_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "data_mode"],
            ["topics.id", "topics.data_mode"],
            name="fk_metric_values_topic_mode",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rules_version"], ["rules_versions.version"], name="fk_metric_values_rules"
        ),
        # Idempotencia: un valor por tema, fuente, ámbito, métrica, periodo y versión.
        UniqueConstraint(
            "data_mode",
            "topic_id",
            "source",
            "scope",
            "metric_key",
            "period_start",
            "period_end",
            "rules_version",
            name="uq_metric_values_identity",
        ),
        CheckConstraint(
            "(status = 'ok' AND value IS NOT NULL AND reason IS NULL)"
            " OR (status = 'insufficient' AND value IS NULL AND reason IS NOT NULL)",
            name="ck_metric_values_status",
        ),
        # Sin infinitos ni NaN (NaN no es igual a sí mismo).
        CheckConstraint(
            "value IS NULL OR (value = value AND value < 1e300 AND value > -1e300)",
            name="ck_metric_values_finite",
        ),
        CheckConstraint("period_end > period_start", name="ck_metric_values_period"),
        CheckConstraint("window_days >= 1", name="ck_metric_values_window"),
        Index("ix_metric_values_topic", "data_mode", "topic_id", "as_of"),
        Index("ix_metric_values_metric", "data_mode", "metric_key", "as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    topic_id: Mapped[str] = mapped_column(String(20))
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    # Ámbito dentro de la fuente: país (Google Trends), sujeto original (Wikimedia y
    # GDELT, que incluye proyecto o filtros) o "*" para métricas del tema completo.
    scope: Mapped[str] = mapped_column(String(500))
    metric_key: Mapped[str] = mapped_column(String(64))
    unit: Mapped[MetricUnit] = mapped_column(_enum(MetricUnit, "metric_unit"))
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[MetricStatus] = mapped_column(_enum(MetricStatus, "metric_status"))
    reason: Mapped[str | None] = mapped_column(String(300))
    # Ventana evaluada [period_start, period_end): días UTC cerrados.
    window_days: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)  # último día cerrado incluido
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    rules_version: Mapped[str] = mapped_column(String(40))
    # False si el conector de la fuente aún no se validó con la fuente real.
    source_validated: Mapped[bool] = mapped_column(Boolean)
    # Observaciones usadas (ids, acotados) y detalles para explicar el resultado.
    inputs: Mapped[dict[str, object]] = mapped_column(JSON)
    details: Mapped[dict[str, object]] = mapped_column(JSON)


# --- E9: clasificación por etapas ------------------------------------------------------


class TrendClassification(Base):
    """Etapa asignada a un tema en una fecha, con una versión de reglas y de métricas.

    Inmutable salvo ``superseded_at``: si las métricas cambian, se crea otra fila.
    """

    __tablename__ = "trend_classifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "data_mode"],
            ["topics.id", "topics.data_mode"],
            name="fk_trend_classifications_topic_mode",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rules_version"], ["rules_versions.version"], name="fk_trend_classifications_rules"
        ),
        UniqueConstraint(
            "data_mode",
            "topic_id",
            "as_of",
            "rules_version",
            "metrics_rules_version",
            "inputs_sha256",
            name="uq_trend_classifications_identity",
        ),
        # Un resultado vigente por tema, fecha y versiones.
        Index(
            "uq_trend_classifications_current",
            "data_mode",
            "topic_id",
            "as_of",
            "rules_version",
            "metrics_rules_version",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
        CheckConstraint(
            "(stage = 'datos_insuficientes') = (reason IS NOT NULL)",
            name="ck_trend_classifications_reason",
        ),
        Index("ix_trend_classifications_stage", "data_mode", "stage", "as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    topic_id: Mapped[str] = mapped_column(String(20))
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    rules_version: Mapped[str] = mapped_column(String(40))
    metrics_rules_version: Mapped[str] = mapped_column(String(40))
    stage: Mapped[TrendStage] = mapped_column(_enum(TrendStage, "trend_stage"))
    reason: Mapped[str | None] = mapped_column(String(300))
    calibrated: Mapped[bool] = mapped_column(Boolean)
    # Huella sha256 de las métricas usadas (ids, valores, estados): base de la idempotencia.
    inputs_sha256: Mapped[str] = mapped_column(String(64))
    metrics_considered: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    explanation: Mapped[dict[str, object]] = mapped_column(JSON)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ClassificationEvidence(Base):
    """Contribución de una fuente a una clasificación (sin puntuación agregada)."""

    __tablename__ = "classification_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["classification_id"],
            ["trend_classifications.id"],
            name="fk_classification_evidence_classification",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("classification_id", "source", name="uq_classification_evidence_source"),
        CheckConstraint(
            "proposed_stage IS NULL OR proposed_stage <> 'datos_insuficientes'",
            name="ck_classification_evidence_stage",
        ),
        Index("ix_classification_evidence_source", "source", "role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classification_id: Mapped[int] = mapped_column(Integer)
    source: Mapped[Source] = mapped_column(_enum(Source, "source"))
    role: Mapped[EvidenceRole] = mapped_column(_enum(EvidenceRole, "evidence_role"))
    source_validated: Mapped[bool] = mapped_column(Boolean)
    proposed_stage: Mapped[TrendStage | None] = mapped_column(_enum(TrendStage, "trend_stage"))
    reason: Mapped[str] = mapped_column(String(300))
    scopes: Mapped[list[dict[str, object]]] = mapped_column(JSON)


# Las clasificaciones solo admiten marcar su reemplazo; la evidencia no cambia.
event.listen(
    TrendClassification.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_trend_classifications_append_only "
        "BEFORE UPDATE ON trend_classifications "
        "WHEN OLD.superseded_at IS NOT NULL "
        "OR NEW.stage IS NOT OLD.stage OR NEW.reason IS NOT OLD.reason "
        "OR NEW.topic_id IS NOT OLD.topic_id OR NEW.data_mode IS NOT OLD.data_mode "
        "OR NEW.as_of IS NOT OLD.as_of OR NEW.rules_version IS NOT OLD.rules_version "
        "OR NEW.metrics_rules_version IS NOT OLD.metrics_rules_version "
        "OR NEW.inputs_sha256 IS NOT OLD.inputs_sha256 "
        "OR NEW.metrics_considered IS NOT OLD.metrics_considered "
        "OR NEW.explanation IS NOT OLD.explanation OR NEW.calibrated IS NOT OLD.calibrated "
        "OR NEW.computed_at IS NOT OLD.computed_at "
        "BEGIN SELECT RAISE(ABORT, 'trend_classifications: solo puede marcarse como reemplazada'); END"
    ),
)
event.listen(
    TrendClassification.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_trend_classifications_no_delete BEFORE DELETE ON trend_classifications "
        "BEGIN SELECT RAISE(ABORT, 'trend_classifications: no se borran'); END"
    ),
)
event.listen(
    ClassificationEvidence.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_classification_evidence_immutable "
        "BEFORE UPDATE ON classification_evidence "
        "BEGIN SELECT RAISE(ABORT, 'classification_evidence: es inmutable'); END"
    ),
)


# Clave de idempotencia. COALESCE evita que un país o idioma NULL permita duplicados.
Index(
    "uq_raw_observations_identity",
    RawObservation.data_mode,
    RawObservation.source,
    RawObservation.metric_key,
    RawObservation.subject_type,
    RawObservation.subject_ref,
    func.coalesce(RawObservation.country, ""),
    func.coalesce(RawObservation.language, ""),
    RawObservation.granularity,
    RawObservation.period_start,
    unique=True,
)
