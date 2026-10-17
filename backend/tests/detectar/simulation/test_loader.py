"""Cargador de conjuntos sintéticos (cierre de DETECTAR): formato, protecciones, idempotencia,
aislamiento y recorrido real normalización → métricas → clasificación."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.simulation.__main__ import main
from app.modules.detectar.simulation.dataset import (
    DEFAULT_DATASET,
    SyntheticDataset,
    load_dataset,
)
from app.modules.detectar.simulation.loader import (
    MARKER,
    MARKER_PURPOSE,
    REPO_ROOT,
    UnsafeTargetError,
    check_target,
    load,
)
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from app.modules.detectar.storage.models import (
    CollectionRun,
    CollectionTrigger,
    DataMode,
    MetricStatus,
    MetricValue,
    RawObservation,
    Source,
    Topic,
    TrendClassification,
    TrendStage,
)
from app.modules.detectar.storage.repository import DetectarRepository
from app.modules.detectar.topics.linker import TopicLinker

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def demo_db(tmp_path: Path, purpose: str = MARKER_PURPOSE) -> Path:
    folder = tmp_path / "hack30x-demo-simulada"
    folder.mkdir()
    (folder / MARKER).write_text(json.dumps({"proposito": purpose}), encoding="utf-8")
    return folder / "detectar.db"


def raw_dataset() -> dict:
    return json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))


def count(db: Path, model, **where) -> int:
    engine = create_sqlite_engine(db)
    try:
        with create_session_factory(engine)() as session:
            stmt = select(func.count()).select_from(model)
            for key, value in where.items():
                stmt = stmt.where(getattr(model, key) == value)
            return session.scalar(stmt) or 0
    finally:
        engine.dispose()


# --- formato ----------------------------------------------------------------------------------


def test_bundled_dataset_declares_synthetic_nature_and_version() -> None:
    dataset = load_dataset()
    assert dataset.naturaleza == "sintetico_demostracion"
    assert dataset.key == "detectar_demo_sintetico@1.0.0"
    assert dataset.procedencia and dataset.proposito and dataset.limitaciones
    # Temas inventados y señalados como demostración; sin personas reales.
    assert all(name.startswith("Tema demo ") for name in dataset.escenarios)
    assert dataset.sources() == [Source.GDELT, Source.GOOGLE_TRENDS_RSS, Source.WIKIMEDIA]


def test_observations_are_marked_synthetic_and_in_period() -> None:
    dataset = load_dataset()
    for source in dataset.sources():
        for obs in dataset.observations(source):
            assert obs.raw_excerpt["sintetico"] is True
            assert obs.raw_excerpt["dataset"] == dataset.key
            assert dataset.periodo.inicio <= obs.period_start.date() <= dataset.periodo.fin
            assert obs.value is not None and obs.value >= 0


def test_dataset_without_synthetic_declaration_is_rejected() -> None:
    data = raw_dataset()
    data["naturaleza"] = "real"
    with pytest.raises(ValidationError):
        SyntheticDataset.model_validate(data)
    del data["naturaleza"]
    with pytest.raises(ValidationError):
        SyntheticDataset.model_validate(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["series"][0]["diario"].update({"2026-09-05": -1}), "greater than or equal"),
        (lambda d: d["series"][0]["diario"].update({"2026-10-05": 10}), "fuera del periodo"),
        (lambda d: d.update({"fecha_clasificacion": "2026-12-01"}), "dentro del periodo"),
        (lambda d: d.update({"campo_extra": 1}), "Extra inputs"),
    ],
)
def test_invalid_dataset_values_are_rejected(mutate, message: str) -> None:
    data = raw_dataset()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        SyntheticDataset.model_validate(data)


# --- protecciones de la base objetivo -----------------------------------------------------------


def test_target_must_be_absolute_db_with_marker(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTargetError, match="absoluta"):
        check_target(Path("relativa/detectar.db"))
    db = demo_db(tmp_path)
    with pytest.raises(UnsafeTargetError, match=r"\.db"):
        check_target(db.with_suffix(".sqlite"))
    assert check_target(db) == db.resolve()


def test_target_without_or_with_foreign_marker_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTargetError, match="marca"):
        check_target(tmp_path / "detectar.db")
    other = tmp_path / "otra"
    other.mkdir()
    (other / MARKER).write_text(json.dumps({"proposito": "otro"}), encoding="utf-8")
    with pytest.raises(UnsafeTargetError, match="marca"):
        check_target(other / "detectar.db")
    (other / MARKER).write_text("no es json", encoding="utf-8")
    with pytest.raises(UnsafeTargetError, match="marca"):
        check_target(other / "detectar.db")


def test_target_in_onedrive_or_repository_is_rejected(tmp_path: Path) -> None:
    synced = tmp_path / "OneDrive" / "demo"
    synced.mkdir(parents=True)
    (synced / MARKER).write_text(json.dumps({"proposito": MARKER_PURPOSE}), encoding="utf-8")
    with pytest.raises(UnsafeTargetError, match="OneDrive"):
        check_target(synced / "detectar.db")
    with pytest.raises(UnsafeTargetError, match="(repositorio|OneDrive)"):
        check_target(REPO_ROOT / "backend" / "demo" / "detectar.db")


def test_target_matching_real_default_database_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "lad"))
    real_dir = tmp_path / "lad" / "hack30x" / "detectar"
    real_dir.mkdir(parents=True)
    (real_dir / MARKER).write_text(json.dumps({"proposito": MARKER_PURPOSE}), encoding="utf-8")
    with pytest.raises(UnsafeTargetError, match="base real"):
        check_target(real_dir / "detectar.db")


def test_unsafe_target_is_never_created(tmp_path: Path) -> None:
    target = tmp_path / "detectar.db"
    with pytest.raises(UnsafeTargetError):
        load(load_dataset(), target, now=NOW)
    assert not target.exists()


def test_database_with_real_records_is_refused_without_writing(tmp_path: Path) -> None:
    db = demo_db(tmp_path)
    engine = create_sqlite_engine(db)
    init_db(engine)
    with create_session_factory(engine)() as session, session.begin():
        DetectarRepository(session).create_collection_run(
            data_mode=DataMode.REAL, trigger=CollectionTrigger.MANUAL, requested_sources=[Source.WIKIMEDIA],
            requested_countries=[], created_at=NOW,
        )
    engine.dispose()
    with pytest.raises(UnsafeTargetError, match="registros reales"):
        load(load_dataset(), db, now=NOW)
    assert count(db, RawObservation) == 0
    assert count(db, CollectionRun, data_mode=DataMode.SIMULATED) == 0


# --- carga, idempotencia y aislamiento --------------------------------------------------------


def test_load_is_simulated_only_and_idempotent(tmp_path: Path) -> None:
    db = demo_db(tmp_path)
    dataset = load_dataset()
    first = load(dataset, db, now=NOW)
    assert first.status == "cargado"
    assert first.observations == {"gdelt": 60, "google_trends_rss": 34, "wikimedia": 65}
    total = sum(first.observations.values())

    second = load(dataset, db, now=NOW)
    assert second.status == "ya_cargado"
    assert second.observations == first.observations
    assert second.collection_runs == first.collection_runs

    assert count(db, RawObservation) == total
    assert count(db, RawObservation, data_mode=DataMode.SIMULATED, dataset_id=dataset.key) == total
    assert count(db, RawObservation, data_mode=DataMode.REAL) == 0
    assert count(db, CollectionRun) == 1


def test_cli_describes_and_refuses_unsafe_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["describir"]) == 0
    meta = json.loads(capsys.readouterr().out)
    assert meta["naturaleza"] == "sintetico_demostracion"
    assert "series" not in meta
    assert main(["cargar", "--db", str(tmp_path / "detectar.db")]) == 2
    assert "marca" in capsys.readouterr().err
    assert main(["cargar", "--db", str(demo_db(tmp_path))]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cargado"


# --- recorrido real: normalización, métricas y clasificación ------------------------------------


def test_real_services_produce_expected_stages_without_changing_rules(tmp_path: Path) -> None:
    db = demo_db(tmp_path)
    dataset = load_dataset()
    load(dataset, db, now=NOW)
    engine = create_sqlite_engine(db)
    factory = create_session_factory(engine)
    try:
        with factory() as session, session.begin():
            TopicLinker(session, clock=lambda: NOW).process(data_mode=DataMode.SIMULATED, limit=5000)
            for day in dataset.fechas_metricas:
                MetricsService(session, clock=lambda: NOW).compute(data_mode=DataMode.SIMULATED, as_of=day)
            ClassificationService(session, clock=lambda: NOW).classify(
                data_mode=DataMode.SIMULATED, as_of=dataset.fecha_clasificacion
            )
        with factory() as session:
            names = {t.id: t.canonical_name for t in session.scalars(select(Topic))}
            result = {
                names[row.topic_id]: (row.stage, row.reason, row.calibrated)
                for row in session.scalars(select(TrendClassification))
            }
            assert result == {
                "Tema demo Alfa": (TrendStage.ACELERANDO, None, False),
                "Tema demo Beta": (TrendStage.PUNTO_MAXIMO, None, False),
                "Tema demo Gamma": (TrendStage.DATOS_INSUFICIENTES, "solo_fuente_no_validada", False),
                "Tema demo Delta": (TrendStage.DATOS_INSUFICIENTES, "sin_evidencia_temporal_suficiente", False),
                "Tema demo Épsilon": (TrendStage.DATOS_INSUFICIENTES, "sin_evidencia_temporal_suficiente", False),
            }
            by_name = {v: k for k, v in names.items()}

            def series(topic: str) -> list[MetricValue]:
                stmt = (
                    select(MetricValue)
                    .where(MetricValue.topic_id == by_name[topic], MetricValue.metric_key == "wiki_views_total")
                    .order_by(MetricValue.as_of)
                )
                return list(session.scalars(stmt))

            alfa = series("Tema demo Alfa")
            assert [v.as_of.date() for v in alfa] == dataset.fechas_metricas
            assert all(v.status is MetricStatus.OK and v.value is not None for v in alfa)
            assert [v.value for v in alfa] == sorted(v.value for v in alfa)
            # Historia insuficiente: valor nulo con motivo, nunca cero.
            delta = series("Tema demo Delta")
            assert delta and all(v.status is MetricStatus.INSUFFICIENT and v.value is None and v.reason for v in delta)
            # Todo en modo simulado.
            assert session.scalar(select(func.count()).select_from(MetricValue).where(MetricValue.data_mode == DataMode.REAL)) == 0
            assert session.scalar(
                select(func.count()).select_from(TrendClassification).where(TrendClassification.data_mode == DataMode.REAL)
            ) == 0
    finally:
        engine.dispose()
    assert date(2026, 9, 30) == dataset.fecha_clasificacion
