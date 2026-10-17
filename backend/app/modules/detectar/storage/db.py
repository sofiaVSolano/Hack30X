"""Conexión SQLite de DETECTAR.

Nada se conecta ni se crea al importar este módulo: el motor se construye con
:func:`create_sqlite_engine` y las tablas con :func:`init_db`, ambas llamadas explícitas.
"""

import logging
import os
import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.migrations import upgrade_schema
from app.modules.detectar.storage.models import Base

logger = logging.getLogger(__name__)

MEMORY_PATH = ":memory:"
DB_FILENAME = "detectar.db"


def default_db_path() -> Path:
    """Ruta por defecto fuera del repositorio y de carpetas sincronizadas."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "hack30x" / "detectar" / DB_FILENAME


def resolve_db_path(settings: DetectarSettings) -> Path:
    return settings.db_path if settings.db_path is not None else default_db_path()


def is_in_synced_folder(path: Path) -> bool:
    """Detecta rutas dentro de OneDrive, donde la sincronización puede bloquear SQLite."""
    # Solo carpetas llamadas "OneDrive" u "OneDrive - <organización>"; no cualquier nombre
    # que contenga la palabra (p. ej. "c--Users-x-OneDrive-proyecto" no es sincronizada).
    return any(
        part.lower() == "onedrive" or part.lower().startswith("onedrive - ")
        for part in path.resolve().parts
    )


def _apply_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA busy_timeout = 5000")
    finally:
        cursor.close()


def _apply_file_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
    finally:
        cursor.close()


def create_sqlite_engine(path: Path | str) -> Engine:
    """Crea un motor SQLite con claves foráneas activas en cada conexión."""
    if str(path) == MEMORY_PATH:
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        db_path = Path(path)
        if is_in_synced_folder(db_path):
            logger.warning(
                "La base de datos de DETECTAR está dentro de OneDrive; "
                "configure DETECTAR_DB_PATH con una ruta no sincronizada."
            )
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            f"sqlite+pysqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        event.listen(engine, "connect", _apply_file_pragmas)
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def init_db(engine: Engine) -> None:
    """Crea las tablas que falten y aplica las actualizaciones mínimas de esquema.

    ``create_all`` no modifica tablas existentes; ``upgrade_schema`` agrega las columnas y
    triggers nuevos de forma idempotente. No hay migraciones generales (Alembic).
    """
    Base.metadata.create_all(engine)
    upgrade_schema(engine)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
