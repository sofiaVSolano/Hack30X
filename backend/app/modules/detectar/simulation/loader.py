"""Carga de un conjunto sintético en una base de DEMOSTRACIÓN (solo ``simulated``).

Protecciones (todas antes de abrir la base):
- ruta absoluta a un ``.db`` cuya carpeta contiene la marca ``.hack30x-demo-simulada``;
- fuera de OneDrive, del repositorio y de la carpeta de la base real por defecto;
- la base no contiene ningún registro ``real``;
- idempotente: si el conjunto (id@versión) ya está cargado, no escribe nada.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.modules.detectar.storage.db import (
    create_session_factory,
    create_sqlite_engine,
    default_db_path,
    init_db,
    is_in_synced_folder,
)
from app.modules.detectar.storage.models import (
    AgentRun,
    CollectionRun,
    CollectionStatus,
    CollectionTrigger,
    DataMode,
    RawObservation,
    SourceRunStatus,
    Topic,
)
from app.modules.detectar.storage.repository import DetectarRepository

from .dataset import SyntheticDataset

MARKER = ".hack30x-demo-simulada"
MARKER_PURPOSE = "demo-simulada-hack30x"
# backend/app/modules/detectar/simulation/loader.py -> raíz del repositorio
REPO_ROOT = Path(__file__).resolve().parents[5]


class UnsafeTargetError(ValueError):
    """La base objetivo no es una base de demostración confirmada."""


@dataclass
class LoadReport:
    dataset: str
    db_path: str
    status: str  # "cargado" | "ya_cargado"
    observations: dict[str, int] = field(default_factory=dict)
    collection_runs: list[str] = field(default_factory=list)


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def check_target(db_path: Path) -> Path:
    """Valida la ruta de la base de demostración o lanza ``UnsafeTargetError``."""
    if not db_path.is_absolute():
        raise UnsafeTargetError("La ruta de la base debe ser absoluta.")
    path = db_path.resolve()
    if path.suffix != ".db":
        raise UnsafeTargetError("La base de demostración debe ser un archivo .db.")
    if is_in_synced_folder(path) or any(part.lower().startswith("onedrive") for part in path.parts):
        raise UnsafeTargetError("La base no puede estar dentro de OneDrive.")
    if _inside(path, REPO_ROOT):
        raise UnsafeTargetError("La base no puede estar dentro del repositorio.")
    real_dir = default_db_path().resolve().parent
    if path == default_db_path().resolve() or _inside(path, real_dir) or _inside(real_dir, path.parent):
        raise UnsafeTargetError("La ruta coincide con la base real por defecto de DETECTAR.")
    marker = path.parent / MARKER
    try:
        purpose = json.loads(marker.read_text(encoding="utf-8")).get("proposito")
    except (OSError, ValueError, AttributeError):
        purpose = None
    if purpose != MARKER_PURPOSE:
        raise UnsafeTargetError(f"La carpeta de la base no tiene la marca {MARKER}: no se confirma que sea de demostración.")
    return path


def load(dataset: SyntheticDataset, db_path: Path, *, now: datetime | None = None) -> LoadReport:
    path = check_target(db_path)
    moment = now or datetime.now(UTC)
    engine = create_sqlite_engine(path)
    try:
        init_db(engine)
        factory = create_session_factory(engine)
        with factory() as session, session.begin():
            for model in (RawObservation, CollectionRun, AgentRun, Topic):
                real = session.scalar(select(func.count()).select_from(model).where(model.data_mode == DataMode.REAL))
                if real:
                    raise UnsafeTargetError(f"La base contiene registros reales ({model.__tablename__}); no es una base de demostración.")

            report = LoadReport(dataset=dataset.key, db_path=str(path), status="cargado")
            existing = session.scalars(
                select(CollectionRun).where(CollectionRun.data_mode == DataMode.SIMULATED)
            ).all()
            loaded = [r.id for r in existing if (r.request_params or {}).get("dataset") == dataset.key]
            if loaded:
                report.status = "ya_cargado"
                report.collection_runs = loaded
                report.observations = {
                    source.value: session.scalar(
                        select(func.count()).select_from(RawObservation).where(
                            RawObservation.data_mode == DataMode.SIMULATED,
                            RawObservation.dataset_id == dataset.key,
                            RawObservation.source == source,
                        )
                    )
                    or 0
                    for source in dataset.sources()
                }
                return report

            repo = DetectarRepository(session)
            run = repo.create_collection_run(
                data_mode=DataMode.SIMULATED,
                trigger=CollectionTrigger.MANUAL,
                requested_sources=dataset.sources(),
                requested_countries=sorted({s.pais for s in dataset.series if getattr(s, "pais", None)}),
                created_at=moment,
                status=CollectionStatus.RUNNING,
                started_at=moment,
                request_params={
                    "dataset": dataset.key,
                    "naturaleza": dataset.naturaleza,
                    "proposito": dataset.proposito,
                    "periodo": [dataset.periodo.inicio.isoformat(), dataset.periodo.fin.isoformat()],
                },
            )
            for source in dataset.sources():
                source_run = repo.add_source_run(
                    collection_run_id=run.id,
                    data_mode=DataMode.SIMULATED,
                    source=source,
                    mode="dataset",
                    status=SourceRunStatus.OK,
                    started_at=moment,
                    finished_at=moment,
                )
                inserted = repo.add_observations(
                    source_run.id, dataset.observations(source), data_mode=DataMode.SIMULATED, dataset_id=dataset.key
                )
                repo.set_source_run_items(source_run.id, inserted.inserted, data_mode=DataMode.SIMULATED)
                report.observations[source.value] = inserted.inserted
            repo.finish_collection_run(run.id, data_mode=DataMode.SIMULATED, status=CollectionStatus.OK, finished_at=moment)
            report.collection_runs = [run.id]
            return report
    finally:
        engine.dispose()
