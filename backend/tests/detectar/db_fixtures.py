"""Fixtures de base de datos reutilizables por los directorios de pruebas de E3.

Se importan desde los ``conftest.py`` de cada directorio. Cada prueba usa su propio
archivo SQLite temporal.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from app.modules.detectar.storage.repository import DetectarRepository


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    test_engine = create_sqlite_engine(tmp_path / "detectar_test.db")
    init_db(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as test_session:
        yield test_session


@pytest.fixture
def repo(session: Session) -> DetectarRepository:
    return DetectarRepository(session)
