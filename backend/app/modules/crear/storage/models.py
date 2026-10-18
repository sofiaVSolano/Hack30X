"""Modelos SQLAlchemy de CREAR: propuestas de contenido (``crear.db``).

Reglas que garantiza la propia base de datos:

- Base PROPIA: no comparte metadatos, tablas ni ``PRAGMA user_version`` con DETECTAR.
- ``data_mode`` viaja en cada fila, como en DETECTAR; una versión y su anterior tienen siempre
  el mismo modo (clave foránea compuesta).
- Una propuesta no se edita ni se borra (triggers): regenerar crea otra fila que apunta a su
  ``parent_id`` y comparte ``root_id``, así se conserva el historial de versiones (RF-10).
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from app.modules.crear.catalog import Approach, Platform
from app.modules.crear.context import Origin
from app.modules.detectar.storage.models import DataMode, UTCDateTime


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


class CrearBase(DeclarativeBase):
    pass


class Proposal(CrearBase):
    __tablename__ = "crear_proposals"
    __table_args__ = (
        UniqueConstraint("id", "data_mode", name="uq_crear_proposals_id_mode"),
        # Un número de versión por historial.
        UniqueConstraint("root_id", "version", name="uq_crear_proposals_root_version"),
        ForeignKeyConstraint(
            ["parent_id", "data_mode"],
            ["crear_proposals.id", "crear_proposals.data_mode"],
            name="fk_crear_proposals_parent_mode",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_crear_proposals_version"),
        CheckConstraint(
            "(parent_id IS NULL AND version = 1 AND root_id = id)"
            " OR (parent_id IS NOT NULL AND version > 1 AND root_id <> id)",
            name="ck_crear_proposals_lineage",
        ),
        CheckConstraint("(origin = 'manual') = (topic_id IS NULL)", name="ck_crear_proposals_origin_topic"),
        Index("ix_crear_proposals_mode_created", "data_mode", "created_at"),
        Index("ix_crear_proposals_mode_topic", "data_mode", "topic_id", "created_at"),
        Index("ix_crear_proposals_batch", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_mode: Mapped[DataMode] = mapped_column(_enum(DataMode, "data_mode"))
    # Las tres propuestas generadas juntas (RF-09) comparten lote.
    batch_id: Mapped[str] = mapped_column(String(20))
    root_id: Mapped[str] = mapped_column(String(20))
    parent_id: Mapped[str | None] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[Origin] = mapped_column(_enum(Origin, "crear_origin"))
    # Tema de DETECTAR (copia del id y del nombre: CREAR no depende de que siga existiendo).
    topic_id: Mapped[str | None] = mapped_column(String(20))
    topic_name: Mapped[str] = mapped_column(String(300))
    approach: Mapped[Approach] = mapped_column(_enum(Approach, "crear_approach"))
    audience: Mapped[str] = mapped_column(String(40))
    audience_detail: Mapped[str | None] = mapped_column(String(200))
    platform: Mapped[Platform] = mapped_column(_enum(Platform, "crear_platform"))
    country: Mapped[str | None] = mapped_column(String(2))
    instruction: Mapped[str | None] = mapped_column(String(300))
    # Qué cambió respecto de la versión anterior: "enfoque", "audiencia", "plataforma"…
    changes: Mapped[list[str]] = mapped_column(JSON)
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    # Contexto con el que se generó (hechos de DETECTAR y limitaciones), tal como se usó.
    context: Mapped[dict[str, object]] = mapped_column(JSON)
    engine: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    engine_notice: Mapped[str | None] = mapped_column(Text)
    # Cifras con aspecto de dato que no aparecen en los hechos (ver generation/verification.py).
    unsupported_figures: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


event.listen(
    Proposal.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_crear_proposals_immutable BEFORE UPDATE ON crear_proposals "
        "BEGIN SELECT RAISE(ABORT, 'crear_proposals: una propuesta no se modifica; regenere una version nueva'); END"
    ),
)
event.listen(
    Proposal.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_crear_proposals_no_delete BEFORE DELETE ON crear_proposals "
        "BEGIN SELECT RAISE(ABORT, 'crear_proposals: las propuestas no se borran'); END"
    ),
)
