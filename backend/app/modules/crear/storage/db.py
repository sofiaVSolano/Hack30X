"""Conexión SQLite de CREAR (``crear.db``), separada de la base de DETECTAR.

Nada se conecta ni se crea al importar este módulo. Reutiliza el motor SQLite de DETECTAR
(claves foráneas activas, WAL y aviso si la ruta está en OneDrive), pero con sus propias tablas.

Ruta por defecto:

- si ``DETECTAR_DB_PATH`` está definida, ``crear.db`` en la misma carpeta (la demostración, que
  usa una carpeta temporal, guarda allí sus propuestas y se limpia con ella);
- si no, ``<datos del usuario>/hack30x/crear/crear.db``, junto a la carpeta de DETECTAR y fuera
  del repositorio.
"""

from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.modules.crear.config import CrearSettings
from app.modules.crear.storage.models import CrearBase
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.db import (
    MEMORY_PATH,
    create_session_factory,
    create_sqlite_engine,
)
from app.modules.detectar.storage.db import default_db_path as detectar_default_db_path

DB_FILENAME = "crear.db"


def default_db_path(detectar: DetectarSettings) -> Path:
    if detectar.db_path is not None:
        if str(detectar.db_path) == MEMORY_PATH:
            return Path(MEMORY_PATH)
        return detectar.db_path.parent / DB_FILENAME
    return detectar_default_db_path().parent.parent / "crear" / DB_FILENAME


def resolve_db_path(settings: CrearSettings, detectar: DetectarSettings) -> Path:
    return settings.db_path if settings.db_path is not None else default_db_path(detectar)


def init_db(engine: Engine) -> None:
    """Crea las tablas de CREAR que falten. No toca ninguna tabla de DETECTAR."""
    CrearBase.metadata.create_all(engine)


def open_session_factory(path: Path | str) -> sessionmaker[Session]:
    engine = create_sqlite_engine(path)
    init_db(engine)
    return create_session_factory(engine)
