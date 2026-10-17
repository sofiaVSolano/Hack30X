"""Conector de Google Trends RSS con respuestas simuladas (respx). Sin red real."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from app.modules.detectar.connectors.base import Availability, ConnectorQuery, Outcome
from app.modules.detectar.connectors.errors import PermanentSourceError
from app.modules.detectar.connectors.google_trends_rss import (
    GTR_RSS_URL,
    MAX_RSS_BYTES,
    METRIC_PRESENCE,
    METRIC_TRAFFIC,
    GoogleTrendsRssConnector,
    parse_traffic_lower_bound,
    parse_trends_rss,
)
from app.modules.detectar.connectors.http import HttpClient, HttpSettings
from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "google_trends_rss"
CAPTURED = datetime(2026, 10, 17, 3, 15, 42, 123456, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def _no_sleep(_seconds: float) -> None:
    return None


def _client(max_retries: int = 0) -> HttpClient:
    return HttpClient(HttpSettings(max_retries=max_retries), sleep=_no_sleep, jitter=lambda: 0.0)


def _connector(client: HttpClient, countries=("MX",), enabled=True) -> GoogleTrendsRssConnector:
    return GoogleTrendsRssConnector(
        client, enabled=enabled, default_countries=countries, clock=lambda: CAPTURED
    )


@pytest.fixture
def mock_rss():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


def _route(router: respx.MockRouter, country: str):
    return router.get(GTR_RSS_URL, params={"geo": country})


# --- Parser ------------------------------------------------------------------


def test_parser_extracts_available_fields() -> None:
    feed = parse_trends_rss(fixture("two_trends.xml"))

    assert feed.skipped_items == 0
    first, second = feed.trends
    assert first.title == "tema de prueba uno"
    assert first.feed_position == 1
    assert first.approx_traffic == "2K+"
    assert first.pub_date == datetime(2026, 10, 16, 20, 10, tzinfo=timezone(timedelta(hours=-7)))
    assert first.pub_date_raw == "Fri, 16 Oct 2026 20:10:00 -0700"
    assert first.picture_source == "Medio de Prueba"
    assert first.news[0].title == "Titular sintético uno"
    assert first.news[0].url == "https://example.test/noticia-1"
    assert first.news[0].source == "Medio de Prueba"
    # Un enlace que no es http(s) no se conserva.
    assert first.news[1].url is None

    assert second.title == "tema de prueba dos"
    assert second.approx_traffic is None
    assert second.pub_date is None  # fecha inválida: no se inventa
    assert second.pub_date_raw == "fecha no válida"
    assert second.news == ()


def test_parser_accepts_feed_without_items() -> None:
    feed = parse_trends_rss(fixture("empty.xml"))

    assert feed.trends == () and feed.skipped_items == 0


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("malformed.xml", "invalid_response"),
        ("entity_expansion.xml", "invalid_response"),
        ("unexpected_root.xml", "unexpected_format"),
        ("no_channel.xml", "unexpected_format"),
    ],
)
def test_parser_rejects_invalid_or_unexpected_xml(name: str, code: str) -> None:
    with pytest.raises(PermanentSourceError) as excinfo:
        parse_trends_rss(fixture(name))

    assert excinfo.value.code == code


def test_parser_counts_items_without_title() -> None:
    feed = parse_trends_rss(fixture("item_without_title.xml"))

    assert [t.title for t in feed.trends] == ["tema valido"]
    assert feed.skipped_items == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("200+", 200.0),
        ("1,000+", 1000.0),
        ("2K+", 2000.0),
        ("1.5M+", 1_500_000.0),
        ("20000+", 20000.0),
        ("200", None),  # sin "+" no es una cota inferior
        ("1.000+", None),  # ambiguo
        ("muchas", None),
        ("", None),
        (None, None),
    ],
)
def test_traffic_lower_bound_is_only_parsed_when_explicit(text, expected) -> None:
    assert parse_traffic_lower_bound(text) == expected


# --- Conector ------------------------------------------------------------------


@pytest.mark.anyio
async def test_valid_feed_produces_presence_and_traffic_observations(mock_rss) -> None:
    route = _route(mock_rss, "MX").respond(200, content=fixture("two_trends.xml"))

    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery(countries=("MX",)))

    assert route.call_count == 1
    assert result.outcome is Outcome.OK
    assert result.http_calls == 1
    by_key = {(o.subject_ref, o.metric_key): o for o in result.observations}
    # tema uno: presencia + tráfico; tema dos: solo presencia (no trae tráfico).
    assert set(by_key) == {
        ("tema de prueba uno", METRIC_PRESENCE),
        ("tema de prueba uno", METRIC_TRAFFIC),
        ("tema de prueba dos", METRIC_PRESENCE),
    }

    presence = by_key[("tema de prueba uno", METRIC_PRESENCE)]
    assert presence.source is Source.GOOGLE_TRENDS_RSS
    assert (presence.unit, presence.value) == (Unit.PRESENCE, 1.0)
    assert presence.granularity is Granularity.SNAPSHOT
    assert presence.subject_type is SubjectType.SEARCH_TERM
    assert (presence.country, presence.country_basis) == ("MX", CountryBasis.REPORTED_BY_SOURCE)
    # El RSS no informa idioma: no se asume español.
    assert (presence.language, presence.language_basis) == (None, LanguageBasis.NONE)
    # Hora de la consulta (sin microsegundos) y fecha original de publicación, por separado.
    assert presence.observed_at == presence.period_start == CAPTURED.replace(microsecond=0)
    assert presence.raw_excerpt["pub_date"] == "2026-10-16T20:10:00-07:00"
    assert presence.raw_excerpt["pub_date_raw"] == "Fri, 16 Oct 2026 20:10:00 -0700"
    assert presence.raw_excerpt["feed_position"] == 1
    assert presence.raw_excerpt["news"][0]["url"] == "https://example.test/noticia-1"
    assert presence.source_url == f"{GTR_RSS_URL}?geo=MX"

    traffic = by_key[("tema de prueba uno", METRIC_TRAFFIC)]
    assert (traffic.unit, traffic.value, traffic.value_text) == (
        Unit.SEARCHES_LOWER_BOUND,
        2000.0,
        "2K+",
    )

    second = by_key[("tema de prueba dos", METRIC_PRESENCE)]
    assert second.raw_excerpt["pub_date"] is None
    assert second.raw_excerpt["approx_traffic"] is None


@pytest.mark.anyio
async def test_unparseable_traffic_keeps_text_without_inventing_a_number(mock_rss) -> None:
    xml = fixture("two_trends.xml").replace(b"2K+", b"Muy alto")
    _route(mock_rss, "MX").respond(200, content=xml)

    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery())

    traffic = [o for o in result.observations if o.metric_key == METRIC_TRAFFIC]
    assert len(traffic) == 1
    assert traffic[0].value is None
    assert traffic[0].value_text == "Muy alto"


@pytest.mark.anyio
async def test_several_countries_are_queried_with_their_code(mock_rss) -> None:
    mx = _route(mock_rss, "MX").respond(200, content=fixture("two_trends.xml"))
    co = _route(mock_rss, "CO").respond(200, content=fixture("item_without_title.xml"))

    async with _client() as client:
        result = await _connector(client, countries=("MX", "CO")).run(ConnectorQuery())

    assert mx.call_count == co.call_count == 1
    assert {o.country for o in result.observations} == {"MX", "CO"}
    # CO tenía un elemento sin título: se informa como resultado parcial, no se oculta.
    assert result.outcome is Outcome.PARTIAL
    assert result.error.code == "items_skipped"
    assert result.http_calls == 2


@pytest.mark.anyio
async def test_empty_feed_is_empty_not_an_error(mock_rss) -> None:
    _route(mock_rss, "MX").respond(200, content=fixture("empty.xml"))

    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.EMPTY
    assert result.observations == ()
    assert result.error is None


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["malformed.xml", "unexpected_root.xml", "entity_expansion.xml"])
async def test_invalid_feed_is_a_permanent_error(mock_rss, name: str) -> None:
    _route(mock_rss, "MX").respond(200, content=fixture(name))

    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.observations == ()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.ReadTimeout("lento"), "upstream_timeout"),
        (httpx.ConnectError("sin conexión"), "upstream_unreachable"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(503), "upstream_unavailable"),
    ],
)
async def test_temporary_failures_are_transient(mock_rss, response, code: str) -> None:
    route = _route(mock_rss, "MX").mock(side_effect=[response] * 2)

    async with _client(max_retries=1) as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.TRANSIENT_ERROR
    assert result.error.code == code
    assert result.error.retryable is True
    assert route.call_count == 2  # 1 intento + 1 reintento del cliente compartido
    assert result.http_calls == 2


@pytest.mark.anyio
async def test_definitive_http_error_is_permanent(mock_rss) -> None:
    route = _route(mock_rss, "MX").respond(404)

    async with _client(max_retries=2) as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "upstream_rejected"
    assert route.call_count == 1


@pytest.mark.anyio
async def test_oversized_feed_is_rejected(mock_rss) -> None:
    _route(mock_rss, "MX").respond(200, content=b"x" * (MAX_RSS_BYTES + 1))

    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "response_too_large"


@pytest.mark.anyio
async def test_failure_in_one_country_keeps_the_others(mock_rss) -> None:
    _route(mock_rss, "MX").respond(200, content=fixture("two_trends.xml"))
    _route(mock_rss, "AR").respond(503)

    async with _client() as client:
        result = await _connector(client, countries=("MX", "AR")).run(ConnectorQuery())

    assert result.outcome is Outcome.PARTIAL
    assert {o.country for o in result.observations} == {"MX"}
    assert result.error.code == "upstream_unavailable"
    assert result.error.retryable is True
    assert "AR:" in result.error.detail


@pytest.mark.anyio
async def test_all_countries_failing_with_mixed_errors(mock_rss) -> None:
    _route(mock_rss, "MX").respond(503)
    _route(mock_rss, "AR").respond(200, content=fixture("malformed.xml"))

    async with _client() as client:
        result = await _connector(client, countries=("MX", "AR")).run(ConnectorQuery())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "multiple_errors"


@pytest.mark.anyio
async def test_query_countries_override_defaults(mock_rss) -> None:
    pe = _route(mock_rss, "PE").respond(200, content=fixture("empty.xml"))

    async with _client() as client:
        await _connector(client, countries=("MX", "CO")).run(ConnectorQuery(countries=("PE",)))

    assert pe.call_count == 1


@pytest.mark.anyio
async def test_disabled_connector_makes_no_requests(mock_rss) -> None:
    route = mock_rss.get(GTR_RSS_URL)

    async with _client() as client:
        result = await _connector(client, enabled=False).run(ConnectorQuery())

    assert result.outcome is Outcome.SKIPPED
    assert result.skipped_reason is Availability.DISABLED
    assert route.call_count == 0


@pytest.mark.parametrize("bad", ["mx", "MEX", "M1", "", "MX&x=1"])
def test_invalid_default_countries_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        GoogleTrendsRssConnector(_client(), enabled=True, default_countries=(bad,))


@pytest.mark.anyio
async def test_no_real_network_is_used(block_network: list[str]) -> None:
    """Sin respx, el conector intenta la URL oficial y el bloqueo de pruebas lo impide."""
    async with _client() as client:
        result = await _connector(client).run(ConnectorQuery())

    assert result.outcome is Outcome.PERMANENT_ERROR  # el bloqueo no es un error HTTP
    assert block_network == ["trends.google.com"]
    block_network.clear()
