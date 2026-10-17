"""Actualización explícita y mínima del esquema SQLite de DETECTAR (sin Alembic).

``create_all()`` solo crea tablas que no existen; no agrega columnas a tablas ya creadas.
Por eso cada cambio sobre una tabla existente se aplica aquí, de forma idempotente, y la
versión aplicada se guarda en ``PRAGMA user_version``.

Versiones:

- 0: esquema de E2 a E4.
- 1 (E5):
  - ``raw_observations.source_published_at`` (nullable);
  - ``collection_runs.request_params`` (nullable);
  - triggers de coherencia de ``collection_runs``. Se usan triggers porque SQLite no
    permite añadir restricciones CHECK a una tabla existente sin reconstruirla. Solo
    validan escrituras futuras: las filas existentes no se modifican ni se borran.
- 2 (E7):
  - índice único ``raw_observations(id, data_mode)`` (``CREATE UNIQUE INDEX IF NOT EXISTS``),
    destino de la clave foránea compuesta de ``topic_links``; ``id`` ya es clave primaria,
    así que no puede fallar con datos existentes;
  - tablas nuevas ``topics``, ``topic_aliases`` y ``topic_links`` (se crean solo si faltan;
    ninguna tabla existente se modifica).
- 3 (E8): tablas nuevas ``rules_versions`` y ``metric_values`` (solo si faltan).
- 4 (E9): tablas nuevas ``trend_classifications`` y ``classification_evidence`` (solo
  si faltan), con sus triggers de inmutabilidad.
"""

import logging

from sqlalchemy import Connection, Engine, text

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 4

_NEW_COLUMNS = (
    ("raw_observations", "source_published_at", "DATETIME"),
    ("collection_runs", "request_params", "JSON"),
)

_COLLECTION_TRIGGERS = (
    # Estado coherente con sus fechas al insertar.
    """
    CREATE TRIGGER IF NOT EXISTS trg_collection_runs_insert_consistency
    BEFORE INSERT ON collection_runs
    WHEN NOT (
        (NEW.status = 'queued' AND NEW.started_at IS NULL AND NEW.finished_at IS NULL)
        OR (NEW.status = 'running' AND NEW.started_at IS NOT NULL AND NEW.finished_at IS NULL)
        OR (NEW.status IN ('ok', 'partial', 'failed') AND NEW.finished_at IS NOT NULL
            AND (NEW.started_at IS NULL OR NEW.finished_at >= NEW.started_at))
    )
    BEGIN SELECT RAISE(ABORT, 'collection_runs: estado incoherente con sus fechas'); END
    """,
    # Mismas reglas al actualizar, más transiciones válidas.
    """
    CREATE TRIGGER IF NOT EXISTS trg_collection_runs_update_consistency
    BEFORE UPDATE ON collection_runs
    WHEN NOT (
        (NEW.status = 'queued' AND NEW.started_at IS NULL AND NEW.finished_at IS NULL)
        OR (NEW.status = 'running' AND NEW.started_at IS NOT NULL AND NEW.finished_at IS NULL)
        OR (NEW.status IN ('ok', 'partial', 'failed') AND NEW.finished_at IS NOT NULL
            AND (NEW.started_at IS NULL OR NEW.finished_at >= NEW.started_at))
    )
    OR NOT (
        OLD.status = NEW.status
        OR (OLD.status = 'queued' AND NEW.status IN ('running', 'failed'))
        OR (OLD.status = 'running' AND NEW.status IN ('ok', 'partial', 'failed'))
    )
    BEGIN SELECT RAISE(ABORT, 'collection_runs: actualizacion de estado invalida'); END
    """,
    # Una recolección terminada no cambia.
    """
    CREATE TRIGGER IF NOT EXISTS trg_collection_runs_terminal_immutable
    BEFORE UPDATE ON collection_runs
    WHEN OLD.status IN ('ok', 'partial', 'failed')
    BEGIN SELECT RAISE(ABORT, 'collection_runs: una recoleccion terminada no se modifica'); END
    """,
)

_INCONSISTENT_COLLECTIONS = """
SELECT count(*) FROM collection_runs WHERE NOT (
    (status = 'queued' AND started_at IS NULL AND finished_at IS NULL)
    OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL)
    OR (status IN ('ok', 'partial', 'failed') AND finished_at IS NOT NULL
        AND (started_at IS NULL OR finished_at >= started_at))
)
"""


def _columns(conn: Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _create_missing_tables(conn: Connection, names: tuple[str, ...]) -> None:
    """Crea tablas NUEVAS que falten (con sus índices y triggers). No altera las existentes."""
    from app.modules.detectar.storage.models import Base  # evita importación circular

    existing = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    missing = [Base.metadata.tables[name] for name in names if name not in existing]
    if missing:
        Base.metadata.create_all(conn, tables=missing)
        logger.info("Esquema: tablas creadas: %s", ", ".join(t.name for t in missing))


def schema_version(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("PRAGMA user_version")).scalar() or 0)


def upgrade_schema(engine: Engine) -> int:
    """Lleva la base a ``SCHEMA_VERSION``. Devuelve el número de filas incoherentes previas."""
    with engine.begin() as conn:
        current = int(conn.execute(text("PRAGMA user_version")).scalar() or 0)
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"La base tiene la versión {current}, posterior a la que conoce este código "
                f"({SCHEMA_VERSION}); no se modifica."
            )
        for table, column, sql_type in _NEW_COLUMNS:
            if column not in _columns(conn, table):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
                logger.info("Esquema: columna %s.%s agregada", table, column)
        inconsistent = int(conn.execute(text(_INCONSISTENT_COLLECTIONS)).scalar() or 0)
        if inconsistent:
            # No se corrigen ni borran: se informa para revisión manual.
            logger.warning(
                "Esquema: %d recolecciones existentes no cumplen las reglas de coherencia", inconsistent
            )
        for ddl in _COLLECTION_TRIGGERS:
            conn.execute(text(ddl))
        # v2 (E7)
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_observations_id_mode "
                "ON raw_observations (id, data_mode)"
            )
        )
        _create_missing_tables(conn, ("topics", "topic_aliases", "topic_links"))
        # v3 (E8)
        _create_missing_tables(conn, ("rules_versions", "metric_values"))
        # v4 (E9)
        _create_missing_tables(conn, ("trend_classifications", "classification_evidence"))
        if current != SCHEMA_VERSION:
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
    return inconsistent
