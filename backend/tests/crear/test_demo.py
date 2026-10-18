"""Complemento de demostración: un veredicto por escenario sin cambiar los temas de DETECTAR."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.crear.demo import DATASET, prepare
from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.simulation.dataset import load_dataset
from app.modules.detectar.simulation.loader import MARKER, UnsafeTargetError, load
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.db import create_session_factory, create_sqlite_engine
from app.modules.detectar.storage.models import DataMode, Topic, TrendClassification
from app.modules.detectar.topics.linker import TopicLinker

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def detectar_demo(tmp_path: Path) -> Path:
    """Lo mismo que «npm run demo:preparar» deja en la base: conjunto de DETECTAR y su flujo."""
    folder = tmp_path / "hack30x-demo-simulada"
    folder.mkdir()
    (folder / MARKER).write_text(json.dumps({"proposito": "demo-simulada-hack30x"}), encoding="utf-8")
    db = folder / "detectar.db"
    dataset = load_dataset()
    load(dataset, db, now=NOW)
    engine = create_sqlite_engine(db)
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        TopicLinker(session, clock=lambda: NOW).process(data_mode=DataMode.SIMULATED, limit=5000)
    for day in dataset.fechas_metricas:
        with factory() as session, session.begin():
            MetricsService(session, clock=lambda: NOW).compute(data_mode=DataMode.SIMULATED, as_of=day)
    with factory() as session, session.begin():
        ClassificationService(session, clock=lambda: NOW).classify(data_mode=DataMode.SIMULATED, as_of=dataset.fecha_clasificacion)
    engine.dispose()
    return db


def stages(db: Path) -> dict[str, str]:
    engine = create_sqlite_engine(db)
    with create_session_factory(engine)() as session:
        rows = session.execute(
            select(Topic.canonical_name, TrendClassification.stage)
            .join(TrendClassification, TrendClassification.topic_id == Topic.id)
            .where(TrendClassification.superseded_at.is_(None))
        ).all()
    engine.dispose()
    return {name: stage.value for name, stage in rows}


def test_complement_shows_every_verdict_and_keeps_detectar_stages(tmp_path: Path) -> None:
    db = detectar_demo(tmp_path)
    before = stages(db)

    summary = prepare(db, now=NOW)

    assert summary["brechas"] == {
        "Tema demo Eta": "brecha_confirmada",
        "Tema demo Zeta": "brecha_por_confirmar",
        "Tema demo Theta": "senales_mixtas",
        "Tema demo Alfa": "sin_brecha",
        "Tema demo Épsilon": "sin_brecha",
        "Tema demo Beta": "datos_insuficientes",
        "Tema demo Delta": "datos_insuficientes",
        "Tema demo Gamma": "datos_insuficientes",
    }
    after = stages(db)
    assert {name: after[name] for name in before} == before  # los temas de DETECTAR no cambian
    assert (before["Tema demo Alfa"], before["Tema demo Beta"]) == ("acelerando", "punto_maximo")
    assert (after["Tema demo Eta"], after["Tema demo Zeta"], after["Tema demo Theta"]) == ("acelerando", "emergente", "emergente")
    assert summary["clasificacion"]["sin_cambios"] == len(before)


def test_complement_is_idempotent(tmp_path: Path) -> None:
    db = detectar_demo(tmp_path)
    prepare(db, now=NOW)

    again = prepare(db, now=NOW)

    assert again["carga"]["status"] == "ya_cargado"
    assert again["observaciones_normalizadas"] == 0


def test_refuses_a_database_that_is_not_a_demo(tmp_path: Path) -> None:
    with pytest.raises(UnsafeTargetError):
        prepare(tmp_path / "detectar.db")


def test_dataset_declares_itself_synthetic() -> None:
    dataset = load_dataset(DATASET)

    assert (dataset.key, dataset.naturaleza) == ("crear_demo_brechas@1.0.0", "sintetico_demostracion")
    assert dataset.fecha_clasificacion.isoformat() == "2026-09-30"
