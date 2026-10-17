"""Aislamiento de fallos entre conectores y registro de sus resultados."""

import asyncio

import pytest

from app.modules.detectar.connectors.base import (
    Availability,
    ConnectorQuery,
    ConnectorResult,
    FetchOutput,
    Outcome,
)
from app.modules.detectar.connectors.errors import TransientSourceError
from app.modules.detectar.ingestion.recording import record_connector_result
from app.modules.detectar.ingestion.runner import run_connectors
from app.modules.detectar.storage.models import (
    CollectionTrigger,
    DataMode,
    Source,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository

from ..fakes import START, FakeConnector
from ..storage.factories import make_observation

QUERY = ConnectorQuery(countries=("MX",))


async def _ok(_query: ConnectorQuery) -> FetchOutput:
    return FetchOutput([make_observation()], http_calls=1)


async def _hangs(_query: ConnectorQuery) -> FetchOutput:
    await asyncio.sleep(30)
    raise AssertionError("no debería llegar aquí")


async def _transient(_query: ConnectorQuery) -> FetchOutput:
    raise TransientSourceError("upstream_unavailable", "HTTP 503 en https://x.test/?key=SECRETO-42")


class ExplodingConnector(FakeConnector):
    async def run(self, query: ConnectorQuery) -> ConnectorResult:  # type: ignore[override]
        raise RuntimeError("fallo fuera del contrato")


@pytest.mark.anyio
async def test_one_failing_source_does_not_stop_the_others() -> None:
    connectors = [
        FakeConnector(Source.WIKIMEDIA, _ok),
        FakeConnector(Source.GDELT, _hangs),
        ExplodingConnector(Source.GOOGLE_TRENDS_RSS, _ok),
        FakeConnector(Source.X, _ok, availability=Availability.DISABLED),
        FakeConnector(Source.INSTAGRAM, _transient),
    ]

    results = await run_connectors(connectors, QUERY, timeout_seconds=0.2)

    by_source = {result.source: result for result in results}
    assert [r.source for r in results] == [c.source for c in connectors]
    assert by_source[Source.WIKIMEDIA].outcome is Outcome.OK
    assert by_source[Source.GDELT].outcome is Outcome.TRANSIENT_ERROR
    assert by_source[Source.GDELT].error.code == "connector_timeout"
    assert by_source[Source.GOOGLE_TRENDS_RSS].outcome is Outcome.PERMANENT_ERROR
    assert by_source[Source.GOOGLE_TRENDS_RSS].error.code == "internal_error"
    assert by_source[Source.X].outcome is Outcome.SKIPPED
    assert by_source[Source.INSTAGRAM].outcome is Outcome.TRANSIENT_ERROR


@pytest.mark.anyio
async def test_duplicate_sources_are_rejected() -> None:
    connectors = [FakeConnector(Source.WIKIMEDIA, _ok), FakeConnector(Source.WIKIMEDIA, _ok)]

    with pytest.raises(ValueError, match="misma fuente"):
        await run_connectors(connectors, QUERY, timeout_seconds=1)


@pytest.mark.anyio
async def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        await run_connectors([], QUERY, timeout_seconds=0)


# --- Registro en SQLite ---------------------------------------------------------


def _real_run(repo: DetectarRepository) -> str:
    run = repo.create_collection_run(
        data_mode=DataMode.REAL,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[Source.WIKIMEDIA, Source.GDELT, Source.X],
        requested_countries=["MX"],
        created_at=START,
    )
    return run.id


@pytest.mark.anyio
async def test_records_results_with_mapped_statuses(repo: DetectarRepository) -> None:
    run_id = _real_run(repo)
    results = await run_connectors(
        [
            FakeConnector(Source.WIKIMEDIA, _ok),
            FakeConnector(Source.GDELT, _transient),
            FakeConnector(Source.X, _ok, availability=Availability.DISABLED),
        ],
        QUERY,
        timeout_seconds=1,
    )

    for result in results:
        record_connector_result(
            repo, collection_run_id=run_id, result=result, mode="on", data_mode=DataMode.REAL
        )

    runs = {sr.source: sr for sr in repo.list_source_runs(run_id, data_mode=DataMode.REAL)}
    assert runs[Source.WIKIMEDIA].status is SourceRunStatus.OK
    assert runs[Source.WIKIMEDIA].items == 1
    assert runs[Source.GDELT].status is SourceRunStatus.FAILED
    assert runs[Source.GDELT].error_code == "upstream_unavailable"
    assert "SECRETO-42" not in (runs[Source.GDELT].error_detail or "")
    assert runs[Source.X].status is SourceRunStatus.SKIPPED_DISABLED
    assert runs[Source.X].http_calls == 0
    stored = repo.list_observations(data_mode=DataMode.REAL)
    assert len(stored) == 1 and stored[0].source is Source.WIKIMEDIA


@pytest.mark.anyio
async def test_repeated_recording_counts_only_new_observations(repo: DetectarRepository) -> None:
    result = await FakeConnector(Source.WIKIMEDIA, _ok).run(QUERY)

    first, _ = record_connector_result(
        repo, collection_run_id=_real_run(repo), result=result, mode="on", data_mode="real"
    )
    second, inserted = record_connector_result(
        repo, collection_run_id=_real_run(repo), result=result, mode="on", data_mode="real"
    )

    assert first.items == 1
    assert (second.items, inserted.ignored) == (0, 1)


@pytest.mark.anyio
async def test_connector_results_cannot_be_recorded_as_simulated(repo: DetectarRepository) -> None:
    simulated_run = repo.create_collection_run(
        data_mode=DataMode.SIMULATED,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[Source.WIKIMEDIA],
        requested_countries=[],
        created_at=START,
    )
    result = await FakeConnector(Source.WIKIMEDIA, _ok).run(QUERY)

    with pytest.raises(ValueError, match="reales"):
        record_connector_result(
            repo,
            collection_run_id=simulated_run.id,
            result=result,
            mode="on",
            data_mode=DataMode.SIMULATED,
        )

    assert repo.list_observations(data_mode=DataMode.SIMULATED) == []
    assert repo.list_observations(data_mode=DataMode.REAL) == []


@pytest.mark.anyio
async def test_real_results_are_not_visible_as_simulated(repo: DetectarRepository) -> None:
    result = await FakeConnector(Source.WIKIMEDIA, _ok).run(QUERY)
    record_connector_result(
        repo, collection_run_id=_real_run(repo), result=result, mode="on", data_mode="real"
    )

    assert repo.list_observations(data_mode=DataMode.SIMULATED) == []
    assert repo.list_collection_runs(data_mode=DataMode.SIMULATED) == []
