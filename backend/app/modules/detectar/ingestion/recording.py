"""Registro de los resultados de los conectores en el almacenamiento de E2."""

from app.modules.detectar.connectors.base import Availability, ConnectorResult, Outcome
from app.modules.detectar.storage.models import DataMode, SourceRun, SourceRunStatus
from app.modules.detectar.storage.repository import DetectarRepository, InsertResult

_STATUS_BY_OUTCOME = {
    Outcome.OK: SourceRunStatus.OK,
    Outcome.EMPTY: SourceRunStatus.OK,
    Outcome.PARTIAL: SourceRunStatus.PARTIAL,
    Outcome.TRANSIENT_ERROR: SourceRunStatus.FAILED,
    Outcome.PERMANENT_ERROR: SourceRunStatus.FAILED,
}

_STATUS_BY_SKIP = {
    Availability.DISABLED: SourceRunStatus.SKIPPED_DISABLED,
    Availability.UNCONFIGURED: SourceRunStatus.SKIPPED_UNCONFIGURED,
}


def source_run_status(result: ConnectorResult) -> SourceRunStatus:
    if result.outcome is Outcome.SKIPPED:
        assert result.skipped_reason is not None  # garantizado por ConnectorResult
        return _STATUS_BY_SKIP[result.skipped_reason]
    return _STATUS_BY_OUTCOME[result.outcome]


def record_connector_result(
    repo: DetectarRepository,
    *,
    collection_run_id: str,
    result: ConnectorResult,
    mode: str,
    data_mode: DataMode | str,
) -> tuple[SourceRun, InsertResult]:
    """Guarda la ejecución de una fuente y sus observaciones.

    Los conectores solo producen datos reales, así que se rechaza registrarlos en una
    recolección simulada. Así ningún dato real termina marcado como simulado ni al revés.
    """
    if DataMode(data_mode) is not DataMode.REAL:
        raise ValueError("Los resultados de conectores solo se registran en recolecciones reales")

    source_run = repo.add_source_run(
        collection_run_id=collection_run_id,
        data_mode=DataMode.REAL,
        source=result.source,
        mode=mode,
        status=source_run_status(result),
        started_at=result.started_at,
        finished_at=result.finished_at,
        http_calls=result.http_calls,
        error_code=result.error.code if result.error else None,
        error_detail=result.error.detail if result.error else None,
    )
    inserted = repo.add_observations(source_run.id, result.observations, data_mode=DataMode.REAL)
    repo.set_source_run_items(source_run.id, inserted.inserted, data_mode=DataMode.REAL)
    return source_run, inserted
