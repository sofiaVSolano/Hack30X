"""Actualización de esquema de E5 sobre bases existentes y triggers de collection_runs."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.modules.detectar.storage.db import create_sqlite_engine, init_db
from app.modules.detectar.storage.migrations import (
    SCHEMA_VERSION,
    schema_version,
    upgrade_schema,
)

E5_TRIGGERS = {
    "trg_collection_runs_insert_consistency",
    "trg_collection_runs_update_consistency",
    "trg_collection_runs_terminal_immutable",
}


def _triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}


def _legacy_database(path: Path) -> Engine:
    """Reproduce una base de E4: sin las columnas ni los triggers de E5, user_version 0."""
    engine = create_sqlite_engine(path)
    init_db(engine)
    with engine.begin() as conn:
        for trigger in E5_TRIGGERS:
            conn.execute(text(f"DROP TRIGGER {trigger}"))
        conn.execute(text("ALTER TABLE raw_observations DROP COLUMN source_published_at"))
        conn.execute(text("ALTER TABLE collection_runs DROP COLUMN request_params"))
        conn.execute(text("PRAGMA user_version = 0"))
        conn.execute(
            text(
                "INSERT INTO collection_runs (id, data_mode, trigger, status, requested_sources, "
                "requested_countries, created_at, started_at, finished_at) VALUES "
                "('run_legado', 'real', 'manual', 'ok', '[\"google_trends_rss\"]', '[\"MX\"]', "
                "'2026-10-16 00:00:00', '2026-10-16 00:00:00', '2026-10-16 00:01:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO source_runs (id, collection_run_id, data_mode, source, mode, status, "
                "http_calls, items, estimated_cost_usd) VALUES ('srn_legado', 'run_legado', 'real', "
                "'google_trends_rss', 'on', 'ok', 1, 1, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO raw_observations (source_run_id, data_mode, source, metric_key, unit, "
                "value, observed_at, period_start, granularity, country, country_basis, "
                "language_basis, subject_type, subject_ref) VALUES ('srn_legado', 'real', "
                "'google_trends_rss', 'gtr_trending_presence', 'presence', 1, '2026-10-16 00:00:00', "
                "'2026-10-16 00:00:00', 'snapshot', 'MX', 'reported_by_source', 'none', "
                "'search_term', 'tema legado')"
            )
        )
    return engine


def test_new_database_is_created_at_current_version(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "nueva.db")
    init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION
    columns = {c["name"] for c in inspect(engine).get_columns("raw_observations")}
    assert "source_published_at" in columns
    assert E5_TRIGGERS <= _triggers(engine)
    engine.dispose()


def test_existing_database_is_upgraded_without_losing_rows(tmp_path: Path) -> None:
    engine = _legacy_database(tmp_path / "legado.db")
    assert schema_version(engine) == 0
    assert "source_published_at" not in {c["name"] for c in inspect(engine).get_columns("raw_observations")}

    init_db(engine)  # create_all no toca tablas existentes; upgrade_schema sí

    assert schema_version(engine) == SCHEMA_VERSION
    assert "source_published_at" in {c["name"] for c in inspect(engine).get_columns("raw_observations")}
    assert "request_params" in {c["name"] for c in inspect(engine).get_columns("collection_runs")}
    assert E5_TRIGGERS <= _triggers(engine)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT subject_ref, source_published_at FROM raw_observations")
        ).one()
        assert row == ("tema legado", None)  # las filas antiguas quedan con NULL
        assert conn.execute(text("SELECT request_params FROM collection_runs")).scalar() is None
    engine.dispose()


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = _legacy_database(tmp_path / "legado.db")

    upgrade_schema(engine)
    upgrade_schema(engine)
    init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION
    engine.dispose()


def test_inconsistent_legacy_rows_are_reported_not_modified(tmp_path: Path) -> None:
    engine = _legacy_database(tmp_path / "legado.db")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO collection_runs (id, data_mode, trigger, status, requested_sources, "
                "requested_countries, created_at) VALUES ('run_raro', 'real', 'manual', 'running', "
                "'[]', '[]', '2026-10-16 00:00:00')"
            )
        )

    assert upgrade_schema(engine) == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM collection_runs WHERE id='run_raro'")).scalar() == "running"
    engine.dispose()


def test_newer_database_is_not_downgraded(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "futura.db")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION + 1}"))

    with pytest.raises(RuntimeError, match="posterior"):
        upgrade_schema(engine)
    engine.dispose()


# --- Triggers de coherencia de collection_runs -------------------------------------

_INSERT = (
    "INSERT INTO collection_runs (id, data_mode, trigger, status, requested_sources, "
    "requested_countries, created_at, started_at, finished_at) VALUES "
    "(:id, 'real', 'manual', :status, '[]', '[]', '2026-10-16 00:00:00', :started, :finished)"
)


@pytest.mark.parametrize(
    ("status", "started", "finished"),
    [
        ("queued", "2026-10-16 00:00:00", None),
        ("running", None, None),
        ("running", "2026-10-16 00:00:00", "2026-10-16 00:01:00"),
        ("ok", "2026-10-16 00:00:00", None),
        ("failed", "2026-10-16 00:05:00", "2026-10-16 00:01:00"),
    ],
)
def test_inconsistent_collection_rows_are_rejected(engine: Engine, status, started, finished) -> None:
    with engine.begin() as conn, pytest.raises(IntegrityError, match="incoherente"):
        conn.execute(text(_INSERT), {"id": "run_x", "status": status, "started": started, "finished": finished})


@pytest.mark.parametrize(
    ("status", "started", "finished"),
    [
        ("queued", None, None),
        ("running", "2026-10-16 00:00:00", None),
        ("partial", "2026-10-16 00:00:00", "2026-10-16 00:01:00"),
        ("failed", None, "2026-10-16 00:01:00"),
    ],
)
def test_consistent_collection_rows_are_accepted(engine: Engine, status, started, finished) -> None:
    with engine.begin() as conn:
        conn.execute(text(_INSERT), {"id": "run_x", "status": status, "started": started, "finished": finished})


def test_invalid_transitions_and_terminal_changes_are_rejected(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_INSERT), {"id": "run_q", "status": "queued", "started": None, "finished": None})
        conn.execute(
            text(_INSERT),
            {"id": "run_ok", "status": "ok", "started": "2026-10-16 00:00:00", "finished": "2026-10-16 00:01:00"},
        )

    with engine.begin() as conn, pytest.raises(IntegrityError, match="invalida"):
        # queued -> ok sin pasar por running
        conn.execute(
            text("UPDATE collection_runs SET status='ok', finished_at='2026-10-16 00:02:00' WHERE id='run_q'")
        )
    with engine.begin() as conn, pytest.raises(IntegrityError, match="terminada"):
        conn.execute(text("UPDATE collection_runs SET status='failed' WHERE id='run_ok'"))


# --- E7: migración v1 -> v2 ------------------------------------------------------------

E7_TABLES = ("topic_links", "topic_aliases", "topics")


def _v1_database(path: Path) -> Engine:
    """Base de E5/E6 (versión 1) con datos y sin las tablas ni el índice de E7."""
    engine = _legacy_database(path)
    upgrade_schema_to_v1 = text("PRAGMA user_version = 1")
    with engine.begin() as conn:
        for table in E7_TABLES:
            conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text("DROP INDEX uq_raw_observations_id_mode"))
        conn.execute(upgrade_schema_to_v1)
    return engine


def test_v1_database_is_upgraded_to_v2_keeping_observations(tmp_path: Path) -> None:
    engine = _v1_database(tmp_path / "v1.db")
    assert not set(E7_TABLES) & set(inspect(engine).get_table_names())

    init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION >= 2
    assert set(E7_TABLES) <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(raw_observations)"))}
        triggers = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
        assert conn.execute(text("SELECT subject_ref FROM raw_observations")).scalar() == "tema legado"
    assert "uq_raw_observations_id_mode" in indexes
    assert {"trg_topic_links_append_only", "trg_topic_links_no_delete"} <= triggers
    engine.dispose()


def test_legacy_observations_can_be_linked_after_upgrade(tmp_path: Path) -> None:
    from app.modules.detectar.storage.db import create_session_factory
    from app.modules.detectar.topics.linker import TopicLinker

    engine = _v1_database(tmp_path / "v1.db")
    init_db(engine)

    with create_session_factory(engine)() as session, session.begin():
        report = TopicLinker(session).process(data_mode="real")

    assert report.processed == 1 and report.topics_created == 1
    engine.dispose()


def test_v2_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = _v1_database(tmp_path / "v1.db")

    for _ in range(3):
        init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION
    engine.dispose()


# --- E8: migración v2 -> v3 ------------------------------------------------------------

E8_TABLES = ("metric_values", "rules_versions")
E9_TABLES = ("classification_evidence", "trend_classifications")


def test_v2_database_is_upgraded_to_v3_keeping_topics(tmp_path: Path) -> None:
    from app.modules.detectar.storage.db import create_session_factory
    from app.modules.detectar.topics.linker import TopicLinker

    engine = _legacy_database(tmp_path / "v2.db")
    init_db(engine)
    with create_session_factory(engine)() as session, session.begin():
        TopicLinker(session).process(data_mode="real")
    with engine.begin() as conn:
        for table in (*E9_TABLES, *E8_TABLES):
            conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text("PRAGMA user_version = 2"))

    init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION >= 3
    assert set(E8_TABLES) <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM topics")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM topic_links")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM raw_observations")).scalar() == 1
    engine.dispose()


# --- E9: migración v3 -> v4 ------------------------------------------------------------


def test_v3_database_is_upgraded_to_v4_keeping_metrics(tmp_path: Path) -> None:
    from datetime import UTC, date, datetime

    from app.modules.detectar.metrics.service import MetricsService
    from app.modules.detectar.storage.db import create_session_factory
    from app.modules.detectar.topics.linker import TopicLinker

    engine = _legacy_database(tmp_path / "v3.db")
    init_db(engine)
    clock = lambda: datetime(2026, 10, 20, tzinfo=UTC)
    with create_session_factory(engine)() as session, session.begin():
        TopicLinker(session).process(data_mode="real")
        MetricsService(session, clock=clock).compute(data_mode="real", as_of=date(2026, 10, 16))
    with engine.connect() as conn:
        metrics_before = conn.execute(text("SELECT * FROM metric_values ORDER BY id")).all()
    assert metrics_before
    with engine.begin() as conn:
        for table in E9_TABLES:
            conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text("PRAGMA user_version = 3"))

    init_db(engine)

    assert schema_version(engine) == SCHEMA_VERSION == 4
    assert set(E9_TABLES) <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM metric_values ORDER BY id")).all() == metrics_before
        assert conn.execute(text("SELECT count(*) FROM topic_links")).scalar() == 1
        triggers = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert {"trg_trend_classifications_append_only", "trg_classification_evidence_immutable"} <= triggers
    init_db(engine)  # idempotente
    assert schema_version(engine) == 4
    engine.dispose()
