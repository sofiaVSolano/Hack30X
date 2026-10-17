"""Conector de GDELT DOC 2.0 con respuestas simuladas (respx). Sin red real.

Las respuestas siguen la forma supuesta en el conector (no verificada con la API real);
los valores son sintéticos.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.modules.detectar.connectors.base import Availability, ConnectorQuery, Outcome
from app.modules.detectar.connectors.gdelt import (
    ATTRIBUTION,
    GDELT_DOC_URL,
    MAX_RESPONSE_BYTES,
    METRIC_ARTICLES,
    GdeltDocConnector,
)
from app.modules.detectar.connectors.http import HttpClient, HttpSettings
from app.modules.detectar.connectors.params import GdeltParams
from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)

TODAY = date(2026, 10, 17)
CONSULTED = datetime(2026, 10, 17, 5, 0, 30, 1234, tzinfo=UTC)
START, END = date(2026, 10, 1), date(2026, 10, 8)  # 8 días: resolución diaria


def point(day: date, value, norm=1000) -> dict:
    data = {"date": f"{day:%Y%m%d}T000000Z", "value": value}
    if norm is not None:
        data["norm"] = norm
    return data


def timeline(*points: dict, series: str = "Article Count") -> dict:
    return {"timeline": [{"series": series, "data": list(points)}]}


async def _no_sleep(_s: float) -> None:
    return None


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _client(max_retries: int = 0) -> HttpClient:
    return HttpClient(HttpSettings(max_retries=max_retries), sleep=_no_sleep, jitter=lambda: 0.0)


def _connector(client: HttpClient, **kwargs) -> GdeltDocConnector:
    options = {
        "enabled": True,
        "max_requests": 5,
        "min_interval_seconds": 0,
        "clock": lambda: CONSULTED,
        "today": lambda: TODAY,
    } | kwargs
    return GdeltDocConnector(client, **options)


def _query(**kwargs) -> ConnectorQuery:
    fields = {"terms": ("inteligencia artificial",), "start": START, "end": END} | kwargs
    return ConnectorQuery(gdelt=GdeltParams(**fields))


@pytest.fixture
def mock_api():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


# --- Parámetros -----------------------------------------------------------------------


def test_queries_quote_phrases_and_add_filters() -> None:
    params = GdeltParams(
        terms=("inteligencia artificial", "Mundial"),
        start=START,
        end=END,
        source_language="spanish",
        source_countries=("MX", "CL"),
    )

    assert params.queries() == (
        ("inteligencia artificial", '"inteligencia artificial" sourcelang:spanish sourcecountry:mexico', "MX"),
        ("inteligencia artificial", '"inteligencia artificial" sourcelang:spanish sourcecountry:chile', "CL"),
        ("Mundial", "Mundial sourcelang:spanish sourcecountry:mexico", "MX"),
        ("Mundial", "Mundial sourcelang:spanish sourcecountry:chile", "CL"),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"terms": ()},
        {"terms": ("a",)},  # demasiado corto
        {"terms": ("x sourcecountry:mexico",)},  # inyección de operador
        {"terms": ('hola"',)},
        {"terms": ("(a OR b)",)},
        {"terms": ("OR",)},
        {"terms": ("tema_x",)},
        {"terms": ("Tema", "tema")},  # repetido sin distinguir mayúsculas
        {"start": END, "end": START},
        {"end": START + timedelta(days=6)},  # menos de 8 días: no sería diaria
        {"source_language": "klingon"},
        {"source_countries": ("BR",)},
        {"source_countries": ("MX", "MX")},
        {"extra": 1},
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict) -> None:
    fields = {"terms": ("Tema",), "start": START, "end": END} | kwargs
    with pytest.raises(ValidationError):
        GdeltParams(**fields)


# --- Respuestas válidas ---------------------------------------------------------------


@pytest.mark.anyio
async def test_valid_timeline_is_stored_as_news_coverage(mock_api) -> None:
    route = mock_api.get(GDELT_DOC_URL).respond(
        200, json=timeline(point(date(2026, 10, 1), 12), point(date(2026, 10, 2), 0, norm=None))
    )

    async with _client() as client:
        result = await _connector(client).run(
            _query(source_language="spanish", source_countries=("MX",))
        )

    assert result.outcome is Outcome.OK
    params = route.calls.last.request.url.params
    assert params["mode"] == "TimelineVolRaw"
    assert params["format"] == "json"
    assert params["startdatetime"] == "20261001000000"
    assert params["enddatetime"] == "20261008235959"
    assert params["query"] == '"inteligencia artificial" sourcelang:spanish sourcecountry:mexico'

    first, second = result.observations
    assert first.source is Source.GDELT
    assert (first.metric_key, first.unit, first.value) == (METRIC_ARTICLES, Unit.ARTICLES, 12.0)
    assert second.value == 0.0  # cero solo porque la fuente lo informó
    assert first.granularity is Granularity.DAY
    assert first.period_start == datetime(2026, 10, 1, tzinfo=UTC)
    assert first.period_end == datetime(2026, 10, 2, tzinfo=UTC)
    assert first.observed_at == CONSULTED.replace(microsecond=0)
    assert first.source_published_at is None
    assert first.subject_type is SubjectType.NEWS_QUERY
    # País del medio (filtro de la consulta), no de la audiencia; idioma del artículo.
    assert (first.country, first.country_basis) == ("MX", CountryBasis.PUBLISHER_COUNTRY)
    assert (first.language, first.language_basis) == ("es", LanguageBasis.QUERY_FILTER)
    assert first.raw_excerpt["norm"] == 1000
    assert second.raw_excerpt["norm"] is None
    assert first.raw_excerpt["requested_interval"] == {"start": "2026-10-01", "end": "2026-10-08"}
    assert first.raw_excerpt["attribution"] == ATTRIBUTION
    assert first.source_url.startswith(GDELT_DOC_URL + "?")


@pytest.mark.anyio
async def test_without_filters_no_country_or_language_is_attributed(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, json=timeline(point(START, 3)))

    async with _client() as client:
        result = await _connector(client).run(_query())

    (obs,) = result.observations
    assert (obs.country, obs.country_basis) == (None, CountryBasis.NONE)
    assert (obs.language, obs.language_basis) == (None, LanguageBasis.NONE)


@pytest.mark.anyio
async def test_missing_days_are_not_filled(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, json=timeline(point(date(2026, 10, 3), 4)))

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert [o.period_start.date() for o in result.observations] == [date(2026, 10, 3)]


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{}, {"timeline": []}, timeline()])
async def test_empty_responses_are_empty(mock_api, payload) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, json=payload)

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.EMPTY
    assert result.error is None


@pytest.mark.anyio
async def test_requests_are_sequential_and_spaced(mock_api) -> None:
    route = mock_api.get(GDELT_DOC_URL).respond(200, json=timeline(point(START, 1)))
    sleeps = SleepRecorder()

    async with _client() as client:
        connector = _connector(client, min_interval_seconds=5.0, sleep=sleeps)
        result = await connector.run(_query(terms=("Tema uno", "Tema dos", "Tema tres")))

    assert route.call_count == 3
    assert sleeps.delays == [5.0, 5.0]  # entre solicitudes, no antes de la primera
    assert result.http_calls == 3
    assert len({o.subject_ref for o in result.observations}) == 3


# --- Respuestas inválidas y errores --------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"otra_cosa": []},
        {"timeline": "x"},
        {"timeline": [{"series": "a", "data": []}, {"series": "b", "data": []}]},
        {"timeline": [{"series": "a"}]},
        timeline({"date": "2026-10-01", "value": 1}),
        timeline(point(START, -1)),
        timeline(point(START, 1.5)),
        timeline(point(START, True)),
        timeline(point(START, "3")),
        timeline(point(START, 1, norm=-5)),
        timeline({"date": "20261001T120000Z", "value": 1}),  # no diaria
        timeline(point(date(2026, 9, 30), 1)),  # fuera del intervalo
        timeline(point(START, 1), point(START, 2)),  # repetido
        ["lista"],
    ],
)
async def test_malformed_payloads_are_permanent_errors(mock_api, payload) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, json=payload)

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "invalid_response"
    assert result.observations == ()


@pytest.mark.anyio
async def test_plain_text_query_error_is_permanent(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, text="Your search contained a phrase that was too short.")

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert "too short" in result.error.detail


@pytest.mark.anyio
async def test_plain_text_rate_limit_is_transient(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, text="Please limit requests to one every 5 seconds.")

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.TRANSIENT_ERROR
    assert result.error.code == "rate_limited"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.ReadTimeout("lento"), "upstream_timeout"),
        (httpx.ConnectError("sin conexión"), "upstream_unreachable"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(502), "upstream_unavailable"),
    ],
)
async def test_temporary_failures_are_transient(mock_api, response, code) -> None:
    route = mock_api.get(GDELT_DOC_URL).mock(side_effect=[response] * 2)

    async with _client(max_retries=1) as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.TRANSIENT_ERROR
    assert result.error.code == code
    assert route.call_count == 2


@pytest.mark.anyio
async def test_definitive_http_error_is_permanent(mock_api) -> None:
    route = mock_api.get(GDELT_DOC_URL).respond(400)

    async with _client(max_retries=2) as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert route.call_count == 1


@pytest.mark.anyio
async def test_oversized_response_is_rejected(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL).respond(200, content=b"{" + b" " * MAX_RESPONSE_BYTES + b"}")

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.error.code == "response_too_large"


@pytest.mark.anyio
async def test_one_failing_query_keeps_the_others(mock_api) -> None:
    mock_api.get(GDELT_DOC_URL, params={"query": "Uno"}).respond(200, json=timeline(point(START, 1)))
    mock_api.get(GDELT_DOC_URL, params={"query": "Dos"}).respond(503)

    async with _client() as client:
        result = await _connector(client).run(_query(terms=("Uno", "Dos")))

    assert result.outcome is Outcome.PARTIAL
    assert {o.subject_ref for o in result.observations} == {"Uno"}
    assert result.error.retryable is True


# --- Validación en el conector y configuración -----------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "kwargs"),
    [
        (ConnectorQuery(), {}),
        (_query(start=TODAY - timedelta(days=8), end=TODAY), {}),  # día no cerrado
        (_query(start=TODAY - timedelta(days=100), end=TODAY - timedelta(days=90)), {}),  # fuera de 3 meses
        (_query(terms=("Uno", "Dos", "Tres")), {"max_requests": 2}),
    ],
)
async def test_invalid_queries_make_no_requests(mock_api, query, kwargs) -> None:
    route = mock_api.get(GDELT_DOC_URL)

    async with _client() as client:
        result = await _connector(client, **kwargs).run(query)

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "invalid_parameter"
    assert route.call_count == 0


@pytest.mark.anyio
async def test_disabled_connector_does_not_call_gdelt(mock_api) -> None:
    route = mock_api.get(GDELT_DOC_URL)

    async with _client() as client:
        result = await _connector(client, enabled=False).run(_query())

    assert result.skipped_reason is Availability.DISABLED
    assert route.call_count == 0


@pytest.mark.anyio
async def test_no_real_network_is_used(block_network: list[str]) -> None:
    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert block_network == ["api.gdeltproject.org"]
    block_network.clear()
