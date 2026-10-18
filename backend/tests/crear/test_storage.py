"""Base propia de CREAR: separada de DETECTAR, con historial inmutable."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.config import CrearSettings
from app.modules.crear.storage.db import default_db_path, resolve_db_path
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.db import default_db_path as detectar_default

from .conftest import FIXED_NOW


def insert(session: Session, proposal_id: str, *, version: int = 1, parent: str | None = None, root: str | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO crear_proposals (id, data_mode, batch_id, root_id, parent_id, version, origin, topic_id,"
            " topic_name, approach, audience, platform, changes, content, context, engine, unsupported_figures, created_at)"
            " VALUES (:id, 'real', 'lot_0000000000000001', :root, :parent, :version, 'manual', NULL, 'Tema',"
            " 'educativo', 'general_latam', 'tiktok', '[]', '{}', '{}', 'plantillas-v1', '[]', :now)"
        ),
        {"id": proposal_id, "root": root or proposal_id, "parent": parent, "version": version, "now": FIXED_NOW.replace(tzinfo=None).isoformat(sep=" ")},
    )


def test_proposals_cannot_be_edited_or_deleted(crear_sessions: sessionmaker[Session]) -> None:
    with crear_sessions() as session, session.begin():
        insert(session, "prp_0000000000000001")

    for statement in (
        "UPDATE crear_proposals SET topic_name = 'otro'",
        "DELETE FROM crear_proposals",
    ):
        with crear_sessions() as session, pytest.raises(IntegrityError), session.begin():
            session.execute(text(statement))


def test_lineage_rules_are_enforced_by_the_database(crear_sessions: sessionmaker[Session]) -> None:
    with crear_sessions() as session, session.begin():
        insert(session, "prp_0000000000000001")

    with crear_sessions() as session, pytest.raises(IntegrityError), session.begin():
        insert(session, "prp_0000000000000002", version=2)  # versión 2 sin padre
    with crear_sessions() as session, pytest.raises(IntegrityError), session.begin():
        insert(session, "prp_0000000000000003", version=2, parent="prp_0000000000000009", root="prp_0000000000000001")


def test_crear_has_its_own_database(tmp_path: Path, crear_sessions: sessionmaker[Session], detectar_sessions) -> None:  # type: ignore[no-untyped-def]
    with crear_sessions() as session:
        crear_tables = set(inspect(session.connection()).get_table_names())
        user_version = session.execute(text("PRAGMA user_version")).scalar()
    with detectar_sessions() as session:
        detectar_tables = set(inspect(session.connection()).get_table_names())

    assert crear_tables == {"crear_proposals"}
    assert "crear_proposals" not in detectar_tables
    assert user_version == 0  # la versión de esquema de DETECTAR no se toca


def test_default_path_follows_detectar() -> None:
    demo = DetectarSettings(db_path=Path("/tmp/hack30x-demo-simulada/detectar.db"))

    assert default_db_path(demo) == Path("/tmp/hack30x-demo-simulada/crear.db")
    assert default_db_path(DetectarSettings()) == detectar_default().parent.parent / "crear" / "crear.db"
    assert default_db_path(DetectarSettings(db_path=Path(":memory:"))) == Path(":memory:")
    assert resolve_db_path(CrearSettings(db_path=Path("/datos/crear.db")), demo) == Path("/datos/crear.db")
