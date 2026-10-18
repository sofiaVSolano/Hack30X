"""Complemento de demostración de CREAR para la base SIMULADA de DETECTAR.

El conjunto de DETECTAR (``detectar_demo_sintetico``) solo tiene señales en español; sin
mediciones en inglés no hay brechas que mostrar. Este complemento:

1. carga el conjunto sintético ``crear_demo_brechas`` con el CARGADOR DE DETECTAR (mismas
   protecciones: carpeta marcada como demostración, sin registros reales, idempotente);
2. ejecuta el flujo real de DETECTAR en modo ``simulated``: normalización, métricas de cada
   fecha del conjunto y clasificación.

No usa la red ni la API, no toca la base real y no modifica los temas de DETECTAR: solo añade
temas nuevos (Eta, Zeta y Theta) y capturas de EE. UU.
"""

import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.modules.crear.detectar_reader import DetectarReader
from app.modules.crear.gaps.service import GapService
from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.simulation.dataset import load_dataset
from app.modules.detectar.simulation.loader import check_target, load
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.db import create_session_factory, create_sqlite_engine
from app.modules.detectar.storage.models import DataMode
from app.modules.detectar.topics.linker import TopicLinker

DATASET = Path(__file__).parent / "crear_demo_brechas-1.0.0.json"
DEMO_DIR_NAME = "hack30x-demo-simulada"  # la misma carpeta que crea «npm run demo:preparar»
BATCH = 5000


def default_demo_db() -> Path:
    """Igual que scripts/demo/rutas.mjs: %TEMP% o %TMP%; si no, el temporal del sistema."""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    return Path(base) / DEMO_DIR_NAME / "detectar.db"


def prepare(db_path: Path, *, now: datetime | None = None) -> dict[str, object]:
    dataset = load_dataset(DATASET)
    report = load(dataset, db_path, now=now)
    moment = now or datetime.now(UTC)

    def clock() -> datetime:
        return moment

    engine = create_sqlite_engine(check_target(db_path))
    try:
        factory = create_session_factory(engine)
        processed = 0
        while True:
            with factory() as session, session.begin():
                batch = TopicLinker(session, clock=clock).process(data_mode=DataMode.SIMULATED, limit=BATCH)
            processed += batch.processed
            if batch.processed < BATCH:
                break
        for day in dataset.fechas_metricas:
            with factory() as session, session.begin():
                MetricsService(session, clock=clock).compute(data_mode=DataMode.SIMULATED, as_of=day)
        with factory() as session, session.begin():
            stages = ClassificationService(session, clock=clock).classify(
                data_mode=DataMode.SIMULATED, as_of=dataset.fecha_clasificacion
            )
        with factory() as session:
            gaps = GapService(DetectarReader(session)).analyze(
                data_mode=DataMode.SIMULATED, as_of=dataset.fecha_clasificacion
            )
    finally:
        engine.dispose()
    return {
        "carga": asdict(report),
        "observaciones_normalizadas": processed,
        "clasificacion": {"creadas": stages.created, "sin_cambios": stages.unchanged, "por_etapa": dict(stages.by_stage)},
        "brechas": {a.topic_name: a.verdict.value for a in gaps.analyses},
    }
