"""Fixtures de almacenamiento: cada prueba usa un archivo SQLite temporal propio."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from app.modules.detectar.storage.models import (
    CollectionTrigger,
    DataMode,
    Source,
    SourceRun,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository

from .factories import T1


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "detectar_test.db"


@pytest.fixture
def engine(db_path: Path) -> Iterator[Engine]:
    test_engine = create_sqlite_engine(db_path)
    init_db(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as test_session:
        yield test_session


@pytest.fixture
def repo(session: Session) -> DetectarRepository:
    return DetectarRepository(session)


@pytest.fixture
def make_source_run(repo: DetectarRepository) -> Callable[..., SourceRun]:
    def _make(data_mode: DataMode, source: Source = Source.WIKIMEDIA) -> SourceRun:
        run = repo.create_collection_run(
            data_mode=data_mode,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[source],
            requested_countries=["MX"],
            created_at=T1,
        )
        return repo.add_source_run(
            collection_run_id=run.id,
            data_mode=data_mode,
            source=source,
            mode="on",
            status=SourceRunStatus.OK,
            started_at=T1,
            finished_at=T1,
        )

    return _make
