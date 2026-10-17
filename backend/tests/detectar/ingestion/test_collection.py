"""Servicio de recolección: SQLite real temporal, HTTP simulado con MockTransport."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.gdelt import GDELT_DOC_URL
from app.modules.detectar.connectors.google_trends_rss import (
    GTR_RSS_URL,
    METRIC_PRESENCE,
    GoogleTrendsRssConnector,
)
from app.modules.detectar.connectors.params import GdeltParams, WikimediaParams
from app.modules.detectar.ingestion.collection import (
    CollectionInProgressError,
    CollectionService,
    SourceNotEnabledError,
    aggregate_status,
)
from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    DataMode,
    Source,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import DetectarRepository

from ..fakes import StepClock

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "google_trends_rss"
FIXED = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)


def rss_transport(responses: dict[str, httpx.Response | bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GTR_RSS_URL)
        response = responses[request.url.params["geo"]]
        return response if isinstance(response, httpx.Response) else httpx.Response(200, content=response)

    return httpx.MockTransport(handler)


def fixed_clock_connectors(client, settings):
    """Conectores reales con reloj fijo, para comprobar la idempotencia."""
    return {
        Source.GOOGLE_TRENDS_RSS: GoogleTrendsRssConnector(
            client, enabled=True, default_countries=settings.countries, clock=lambda: FIXED
        )
    }


def _settings(**overrides) -> DetectarSettings:
    return DetectarSettings(env="test", http_max_retries=0, **overrides)


def _service(session_factory, transport, **kwargs) -> CollectionService:
    return CollectionService(
        session_factory,
        kwargs.pop("settings", _settings()),
        http_transport=transport,
        clock=StepClock(),
        **kwargs,
    )


async def test_collection_persists_run_source_and_observations(session_factory) -> None:
    transport = rss_transport({"MX": (FIXTURES / "two_trends.xml").read_bytes()})

    report = await _service(session_factory, transport).collect(
        [Source.GOOGLE_TRENDS_RSS], ["MX"]
    )

    assert report.status is CollectionStatus.OK
    (source,) = report.sources
    assert (source.status, source.inserted, source.ignored, source.http_calls) == (
        SourceRunStatus.OK,
        3,
        0,
        1,
    )
    with session_factory() as session:
        repo = DetectarRepository(session)
        run = repo.get_collection_run(report.run_id, data_mode=DataMode.REAL)
        assert run.status is CollectionStatus.OK
        assert run.started_at is not None and run.finished_at > run.started_at
        assert run.requested_countries == ["MX"]
        (source_run,) = repo.list_source_runs(report.run_id, data_mode=DataMode.REAL)
        assert source_run.items == 3
        observations = repo.list_observations(data_mode=DataMode.REAL)
        assert len(observations) == 3
        assert {o.source_run_id for o in observations} == {source_run.id}


async def test_repeated_collection_does_not_duplicate_observations(session_factory) -> None:
    transport = rss_transport({"MX": (FIXTURES / "two_trends.xml").read_bytes()})
    service = _service(session_factory, transport, connector_factory=fixed_clock_connectors)

    first = await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"])
    second = await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    assert first.sources[0].inserted == 3
    assert (second.sources[0].inserted, second.sources[0].ignored) == (0, 3)
    with session_factory() as session:
        assert len(DetectarRepository(session).list_observations(data_mode=DataMode.REAL)) == 3


async def test_failed_source_is_recorded_and_collection_is_failed(session_factory) -> None:
    transport = rss_transport({"MX": httpx.Response(503)})

    report = await _service(session_factory, transport).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    assert report.status is CollectionStatus.FAILED
    (source,) = report.sources
    assert source.status is SourceRunStatus.FAILED
    assert source.error_code == "upstream_unavailable"
    with session_factory() as session:
        repo = DetectarRepository(session)
        assert repo.get_collection_run(report.run_id, data_mode="real").status is CollectionStatus.FAILED
        assert repo.list_observations(data_mode=DataMode.REAL) == []


async def test_partial_country_failure_is_a_partial_collection(session_factory) -> None:
    transport = rss_transport(
        {"MX": (FIXTURES / "two_trends.xml").read_bytes(), "AR": httpx.Response(500)}
    )

    report = await _service(session_factory, transport).collect(
        [Source.GOOGLE_TRENDS_RSS], ["MX", "AR"]
    )

    assert report.status is CollectionStatus.PARTIAL
    assert report.sources[0].status is SourceRunStatus.PARTIAL


async def test_empty_feed_is_ok_with_zero_observations(session_factory) -> None:
    transport = rss_transport({"MX": (FIXTURES / "empty.xml").read_bytes()})

    report = await _service(session_factory, transport).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    assert report.status is CollectionStatus.OK
    assert report.sources[0].inserted == 0


async def test_unexpected_error_closes_the_run_as_failed(session_factory) -> None:
    def broken_factory(client, settings):
        raise RuntimeError("fallo inesperado")

    service = _service(session_factory, rss_transport({}), connector_factory=broken_factory)

    with pytest.raises(RuntimeError):
        await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    with session_factory() as session:
        (run,) = DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL)
        assert run.status is CollectionStatus.FAILED
        assert run.finished_at is not None


async def test_disabled_or_unknown_sources_are_rejected(session_factory) -> None:
    service = _service(session_factory, rss_transport({}), settings=_settings(gtr_mode="off"))

    with pytest.raises(SourceNotEnabledError):
        await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"])
    with pytest.raises(SourceNotEnabledError):
        await _service(session_factory, rss_transport({})).collect([Source.YOUTUBE], ["MX"])

    with session_factory() as session:
        assert DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL) == []


async def test_concurrent_collections_are_rejected(session_factory) -> None:
    release = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(200, content=(FIXTURES / "empty.xml").read_bytes())

    service = _service(session_factory, httpx.MockTransport(slow_handler))
    first = asyncio.create_task(service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"]))
    await asyncio.sleep(0.05)

    with pytest.raises(CollectionInProgressError):
        await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    release.set()
    report = await first
    assert report.status is CollectionStatus.OK
    with session_factory() as session:
        assert len(DetectarRepository(session).list_collection_runs(data_mode=DataMode.REAL)) == 1


def _running_run(session_factory: sessionmaker[Session], started_at: datetime) -> str:
    with session_factory() as session, session.begin():
        run = DetectarRepository(session).create_collection_run(
            data_mode=DataMode.REAL,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[Source.GOOGLE_TRENDS_RSS],
            requested_countries=["MX"],
            created_at=started_at,
            status=CollectionStatus.RUNNING,
            started_at=started_at,
        )
        return run.id


async def test_recent_running_collection_in_database_blocks_a_new_one(session_factory) -> None:
    _running_run(session_factory, StepClock()())

    with pytest.raises(CollectionInProgressError):
        await _service(session_factory, rss_transport({})).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])


async def test_abandoned_running_collection_is_closed_as_failed(session_factory) -> None:
    stale_id = _running_run(session_factory, StepClock()() - timedelta(hours=2))
    transport = rss_transport({"MX": (FIXTURES / "empty.xml").read_bytes()})

    report = await _service(session_factory, transport).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    assert report.status is CollectionStatus.OK
    with session_factory() as session:
        stale = DetectarRepository(session).get_collection_run(stale_id, data_mode="real")
        assert stale.status is CollectionStatus.FAILED


async def test_collections_are_always_real_and_isolated(session_factory) -> None:
    transport = rss_transport({"MX": (FIXTURES / "two_trends.xml").read_bytes()})

    await _service(session_factory, transport).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    with session_factory() as session:
        repo = DetectarRepository(session)
        assert repo.list_collection_runs(data_mode=DataMode.SIMULATED) == []
        assert repo.list_observations(data_mode=DataMode.SIMULATED) == []
        real = repo.list_observations(data_mode=DataMode.REAL, metric_key=METRIC_PRESENCE)
        assert real and all(o.dataset_id is None for o in real)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([SourceRunStatus.OK], CollectionStatus.OK),
        ([SourceRunStatus.FAILED], CollectionStatus.FAILED),
        ([SourceRunStatus.OK, SourceRunStatus.FAILED], CollectionStatus.PARTIAL),
        ([SourceRunStatus.PARTIAL], CollectionStatus.PARTIAL),
        ([], CollectionStatus.FAILED),
    ],
)
def test_aggregate_status_never_reports_failure_as_success(statuses, expected) -> None:
    assert aggregate_status(statuses) is expected


# --- E5: Wikimedia en el servicio de recolección --------------------------------------


def _both_sources_transport(wiki_status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(GTR_RSS_URL):
            return httpx.Response(200, content=(FIXTURES / "two_trends.xml").read_bytes())
        return httpx.Response(wiki_status)

    return httpx.MockTransport(handler)


def _wiki_settings() -> DetectarSettings:
    return _settings(wikimedia_mode="on", http_contact="equipo@hack30x.example")


def _wiki_params() -> WikimediaParams:
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    return WikimediaParams(articles=("Tema",), start=yesterday, end=yesterday)


async def test_wikimedia_failure_does_not_affect_trends(session_factory) -> None:
    service = _service(session_factory, _both_sources_transport(503), settings=_wiki_settings())

    report = await service.collect(
        [Source.GOOGLE_TRENDS_RSS, Source.WIKIMEDIA], ["MX"], wikimedia=_wiki_params()
    )

    assert report.status is CollectionStatus.PARTIAL
    statuses = {s.source: s.status for s in report.sources}
    assert statuses == {
        Source.GOOGLE_TRENDS_RSS: SourceRunStatus.OK,
        Source.WIKIMEDIA: SourceRunStatus.FAILED,
    }
    with session_factory() as session:
        stored = DetectarRepository(session).list_observations(data_mode=DataMode.REAL)
        assert len(stored) == 3 and {o.source for o in stored} == {Source.GOOGLE_TRENDS_RSS}


async def test_wikimedia_params_are_required_only_with_wikimedia(session_factory) -> None:
    service = _service(session_factory, _both_sources_transport(200), settings=_wiki_settings())

    with pytest.raises(ValueError):
        await service.collect([Source.WIKIMEDIA], [])
    with pytest.raises(ValueError):
        await service.collect([Source.GOOGLE_TRENDS_RSS], ["MX"], wikimedia=_wiki_params())


async def test_trend_observations_keep_original_publication_date(session_factory) -> None:
    transport = rss_transport({"MX": (FIXTURES / "two_trends.xml").read_bytes()})

    await _service(session_factory, transport).collect([Source.GOOGLE_TRENDS_RSS], ["MX"])

    with session_factory() as session:
        rows = DetectarRepository(session).list_observations(
            data_mode=DataMode.REAL, metric_key=METRIC_PRESENCE
        )
    by_term = {r.subject_ref: r for r in rows}
    published = by_term["tema de prueba uno"].source_published_at
    assert published == datetime(2026, 10, 17, 3, 10, tzinfo=UTC)  # 20:10 -07:00
    assert by_term["tema de prueba uno"].observed_at != published
    assert by_term["tema de prueba dos"].source_published_at is None  # pubDate inválido


# --- E6: GDELT en el servicio de recolección ---------------------------------------------


def _three_sources_transport(gdelt_status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(GTR_RSS_URL):
            return httpx.Response(200, content=(FIXTURES / "two_trends.xml").read_bytes())
        if url.startswith(GDELT_DOC_URL):
            if gdelt_status != 200:
                return httpx.Response(gdelt_status)
            day = datetime.now(UTC).date() - timedelta(days=2)
            return httpx.Response(
                200,
                json={"timeline": [{"series": "Article Count", "data": [
                    {"date": f"{day:%Y%m%d}T000000Z", "value": 7, "norm": 900}
                ]}]},
            )
        raise AssertionError(f"URL inesperada: {url}")

    return httpx.MockTransport(handler)


def _gdelt_params() -> GdeltParams:
    end = datetime.now(UTC).date() - timedelta(days=1)
    return GdeltParams(terms=("Tema",), start=end - timedelta(days=9), end=end)


def _gdelt_settings() -> DetectarSettings:
    return _settings(gdelt_mode="on", gdelt_min_interval_seconds=1)


async def test_gdelt_is_recorded_with_provenance(session_factory) -> None:
    service = _service(session_factory, _three_sources_transport(200), settings=_gdelt_settings())

    report = await service.collect([Source.GDELT], [], gdelt=_gdelt_params())

    assert report.status is CollectionStatus.OK
    with session_factory() as session:
        repo = DetectarRepository(session)
        (obs,) = repo.list_observations(data_mode=DataMode.REAL, source=Source.GDELT)
        assert obs.value == 7.0
        assert obs.raw_excerpt["norm"] == 900
        assert obs.raw_excerpt["attribution"].startswith("Datos: The GDELT Project")
        run = repo.get_collection_run(report.run_id, data_mode=DataMode.REAL)
        assert run.request_params["gdelt"]["terms"] == ["Tema"]
        assert run.requested_countries == []


async def test_gdelt_recording_is_idempotent(session_factory) -> None:
    service = _service(session_factory, _three_sources_transport(200), settings=_gdelt_settings())

    first = await service.collect([Source.GDELT], [], gdelt=_gdelt_params())
    second = await service.collect([Source.GDELT], [], gdelt=_gdelt_params())

    assert first.sources[0].inserted == 1
    assert (second.sources[0].inserted, second.sources[0].ignored) == (0, 1)


async def test_gdelt_failure_does_not_affect_other_sources(session_factory) -> None:
    service = _service(session_factory, _three_sources_transport(503), settings=_gdelt_settings())

    report = await service.collect(
        [Source.GOOGLE_TRENDS_RSS, Source.GDELT], ["MX"], gdelt=_gdelt_params()
    )

    assert report.status is CollectionStatus.PARTIAL
    statuses = {s.source: s.status for s in report.sources}
    assert statuses[Source.GOOGLE_TRENDS_RSS] is SourceRunStatus.OK
    assert statuses[Source.GDELT] is SourceRunStatus.FAILED
    with session_factory() as session:
        stored = DetectarRepository(session).list_observations(data_mode=DataMode.REAL)
        assert {o.source for o in stored} == {Source.GOOGLE_TRENDS_RSS}
        assert DetectarRepository(session).list_observations(data_mode=DataMode.SIMULATED) == []


async def test_gdelt_is_off_by_default(session_factory) -> None:
    service = _service(session_factory, _three_sources_transport(200))

    with pytest.raises(SourceNotEnabledError):
        await service.collect([Source.GDELT], [], gdelt=_gdelt_params())
