from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text

from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.storage.db import (
    create_sqlite_engine,
    default_db_path,
    init_db,
    is_in_synced_folder,
    resolve_db_path,
)


def test_init_db_creates_expected_tables(engine: Engine) -> None:
    # E2: recolecciones y observaciones. E3: agentes. E7: temas. Todo en la misma base.
    assert set(inspect(engine).get_table_names()) == {
        "collection_runs",
        "source_runs",
        "raw_observations",
        "agent_runs",
        # E7: temas, alias y vínculos.
        "topics",
        "topic_aliases",
        "topic_links",
        # E8: métricas.
        "rules_versions",
        "metric_values",
        # E9: clasificación por etapas.
        "trend_classifications",
        "classification_evidence",
    }


def test_init_db_is_idempotent(engine: Engine) -> None:
    init_db(engine)

    assert "raw_observations" in inspect(engine).get_table_names()


def test_foreign_keys_and_wal_are_enabled(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_identity_index_is_unique_and_uses_coalesce(engine: Engine) -> None:
    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'uq_raw_observations_identity'")
        ).scalar()

    assert sql is not None
    assert sql.upper().startswith("CREATE UNIQUE INDEX")
    assert "coalesce(country, '')" in sql
    assert "coalesce(language, '')" in sql


def test_creating_engine_does_not_create_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "nueva" / "detectar.db"
    engine = create_sqlite_engine(db_file)
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_memory_engine_has_foreign_keys() -> None:
    engine = create_sqlite_engine(":memory:")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.dispose()


def test_db_path_comes_from_detectar_db_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "otra" / "detectar.db"
    monkeypatch.setenv("DETECTAR_DB_PATH", str(configured))

    assert resolve_db_path(DetectarSettings()) == configured


def test_default_db_path_is_used_when_not_configured() -> None:
    assert resolve_db_path(DetectarSettings()) == default_db_path()


def test_default_db_path_is_outside_repository() -> None:
    repo_root = Path(__file__).resolve().parents[4]

    assert not default_db_path().resolve().is_relative_to(repo_root)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (Path("C:/Users/ana/OneDrive/proyecto/detectar.db"), True),
        (Path("C:/Users/ana/OneDrive - Empresa/detectar.db"), True),
        (Path("C:/datos/hack30x/detectar.db"), False),
        # Falso positivo encontrado en E6: el nombre contiene "OneDrive" pero no es la carpeta.
        (Path("C:/Users/ana/AppData/Local/Temp/c--Users-ana-OneDrive-Proyecto/detectar.db"), False),
    ],
)
def test_is_in_synced_folder(path: Path, expected: bool) -> None:
    assert is_in_synced_folder(path) is expected
