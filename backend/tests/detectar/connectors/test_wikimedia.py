"""Conector de Wikimedia Pageviews con respuestas simuladas (respx). Sin red real.

Las respuestas siguen el esquema de la especificación OpenAPI oficial
(items[] con project, article, granularity, timestamp, access, agent, views); los
valores son sintéticos.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.modules.detectar.connectors.base import Availability, ConnectorQuery, Outcome
from app.modules.detectar.connectors.http import HttpClient, HttpSettings
from app.modules.detectar.connectors.params import (
    WikimediaParams,
    normalize_article_title,
)
from app.modules.detectar.connectors.wikimedia import (
    METRIC_PAGEVIEWS,
    WikimediaPageviewsConnector,
    article_url,
    pageviews_url,
)
from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)

TODAY = date(2026, 10, 17)
CONSULTED = datetime(2026, 10, 17, 4, 30, 15, 999, tzinfo=UTC)
START, END = date(2026, 10, 1), date(2026, 10, 3)
PROJECT = "es.wikipedia.org"


def item(day: date, views: int, article: str = "Tema_de_prueba", **overrides) -> dict:
    return {
        # La API real responde el proyecto sin ".org" (verificado el 17/10/2026).
        "project": PROJECT.removesuffix(".org"),
        "article": article,
        "granularity": "daily",
        "timestamp": f"{day:%Y%m%d}00",
        "access": "all-access",
        "agent": "user",
        "views": views,
    } | overrides


async def _no_sleep(_s: float) -> None:
    return None


def _client(max_retries: int = 0) -> HttpClient:
    return HttpClient(HttpSettings(max_retries=max_retries), sleep=_no_sleep, jitter=lambda: 0.0)


def _connector(client: HttpClient, **kwargs) -> WikimediaPageviewsConnector:
    options = {
        "enabled": True,
        "contact": "equipo@hack30x.example",
        "default_projects": (PROJECT,),
        "max_days": 90,
        "max_articles": 20,
        "clock": lambda: CONSULTED,
        "today": lambda: TODAY,
    } | kwargs
    return WikimediaPageviewsConnector(client, **options)


def _query(articles=("Tema de prueba",), start=START, end=END, projects=()) -> ConnectorQuery:
    return ConnectorQuery(
        wikimedia=WikimediaParams(articles=articles, start=start, end=end, projects=projects)
    )


@pytest.fixture
def mock_api():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


def _route(router, article="Tema_de_prueba", project=PROJECT, start=START, end=END):
    return router.get(pageviews_url(project, article, start, end))


# --- URL y parámetros ---------------------------------------------------------------


def test_url_follows_the_official_template() -> None:
    assert pageviews_url(PROJECT, "AC/DC", START, END) == (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "es.wikipedia.org/all-access/user/AC%2FDC/daily/2026100100/2026100300"
    )
    assert article_url(PROJECT, "Ñandú") == "https://es.wikipedia.org/wiki/%C3%91and%C3%BA"


def test_titles_are_normalized_without_changing_case() -> None:
    assert normalize_article_title("  Copa América 2026 ") == "Copa_América_2026"
    assert normalize_article_title("iPhone") == "iPhone"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"articles": ()},
        {"articles": ("",)},
        {"articles": ("Tema|otro",)},
        {"articles": ("a" * 256,)},
        {"articles": ("Tema", "Tema")},
        {"start": END, "end": START},
        {"start": date(2015, 6, 30), "end": date(2015, 7, 2)},
        {"projects": ("es.wikipedia",)},
        {"projects": ("evil.example.com",)},
        {"projects": ("es.wikipedia.org/../x",)},
    ],
)
def test_invalid_parameters_are_rejected(kwargs: dict) -> None:
    fields = {"articles": ("Tema",), "start": START, "end": END} | kwargs
    with pytest.raises(ValidationError):
        WikimediaParams(**fields)


# --- Respuestas válidas -----------------------------------------------------------


@pytest.mark.anyio
async def test_valid_response_keeps_dates_project_title_and_views(mock_api) -> None:
    route = _route(mock_api).respond(
        200, json={"items": [item(date(2026, 10, 1), 120), item(date(2026, 10, 2), 0)]}
    )

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert route.call_count == 1
    assert route.calls.last.request.headers["User-Agent"].startswith("HACK30X-DETECTAR/")
    assert result.outcome is Outcome.OK
    assert result.http_calls == 1
    first, second = result.observations
    assert first.source is Source.WIKIMEDIA
    assert (first.metric_key, first.unit, first.value) == (METRIC_PAGEVIEWS, Unit.VIEWS, 120.0)
    assert second.value == 0.0  # cero solo porque la API lo informó
    # Fecha de la métrica, hora de consulta y ausencia de fecha de publicación: separadas.
    assert first.period_start == datetime(2026, 10, 1, tzinfo=UTC)
    assert first.period_end == datetime(2026, 10, 2, tzinfo=UTC)
    assert first.observed_at == CONSULTED.replace(microsecond=0)
    assert first.source_published_at is None
    assert first.granularity is Granularity.DAY
    assert first.subject_type is SubjectType.WIKI_ARTICLE
    assert first.subject_ref == "es.wikipedia.org:Tema_de_prueba"
    # La edición indica el idioma consultado, nunca el país de los lectores.
    assert (first.language, first.language_basis) == ("es", LanguageBasis.QUERY_FILTER)
    assert (first.country, first.country_basis) == (None, CountryBasis.NONE)
    assert first.source_url == "https://es.wikipedia.org/wiki/Tema_de_prueba"
    assert first.raw_excerpt["timestamp"] == "2026100100"
    assert first.raw_excerpt["requested_interval"] == {"start": "2026-10-01", "end": "2026-10-03"}
    assert first.raw_excerpt["agent"] == "user"


@pytest.mark.anyio
async def test_missing_days_are_not_filled(mock_api) -> None:
    _route(mock_api).respond(200, json={"items": [item(date(2026, 10, 1), 5)]})

    async with _client() as client:
        result = await _connector(client).run(_query())

    # Se pidieron 3 días; la API entregó 1. No se crean días con cero.
    assert [o.period_start.date() for o in result.observations] == [date(2026, 10, 1)]


@pytest.mark.anyio
async def test_empty_items_is_empty_not_error(mock_api) -> None:
    _route(mock_api).respond(200, json={"items": []})

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.EMPTY
    assert result.error is None


@pytest.mark.anyio
async def test_404_means_no_data_and_is_never_zero(mock_api) -> None:
    _route(mock_api).respond(404, json={"type": "not_found"})
    _route(mock_api, article="Otro_tema").respond(200, json={"items": [item(START, 7, "Otro_tema")]})

    async with _client() as client:
        result = await _connector(client).run(_query(articles=("Tema de prueba", "Otro tema")))

    assert result.outcome is Outcome.PARTIAL
    assert [o.subject_ref for o in result.observations] == ["es.wikipedia.org:Otro_tema"]
    assert result.error.code == "article_not_found"
    assert "no equivale a cero" in result.error.detail


@pytest.mark.anyio
async def test_all_articles_without_data_is_a_controlled_error(mock_api) -> None:
    _route(mock_api).respond(404)

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "article_not_found"
    assert result.observations == ()


@pytest.mark.anyio
async def test_several_projects_and_articles(mock_api) -> None:
    for project in (PROJECT, "en.wikipedia.org"):
        for article in ("Tema_de_prueba", "Otro_tema"):
            _route(mock_api, article=article, project=project).respond(
                200,
                json={"items": [item(START, 1, article, project=project.removesuffix(".org"))]},
            )

    async with _client() as client:
        connector = _connector(client, default_projects=(PROJECT, "en.wikipedia.org"))
        result = await connector.run(_query(articles=("Tema de prueba", "Otro tema")))

    assert result.http_calls == 4
    assert {(o.subject_ref, o.language) for o in result.observations} == {
        ("es.wikipedia.org:Tema_de_prueba", "es"),
        ("es.wikipedia.org:Otro_tema", "es"),
        ("en.wikipedia.org:Tema_de_prueba", "en"),
        ("en.wikipedia.org:Otro_tema", "en"),
    }


# --- Respuestas inválidas -----------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"sin_items": []},
        {"items": "no es lista"},
        {"items": [item(START, -1)]},
        {"items": [item(START, 1.5)]},
        {"items": [item(START, True)]},
        {"items": [item(START, "10")]},
        {"items": [item(START, 1, timestamp="20261001")]},
        {"items": [item(START, 1, timestamp="2026100112")]},
        {"items": [item(START, 1, timestamp="2026023100")]},
        {"items": [item(date(2026, 9, 30), 1)]},  # fuera del intervalo
        {"items": [item(START, 1), item(START, 2)]},  # día repetido
        {"items": [item(START, 1, granularity="monthly")]},
        {"items": [item(START, 1, project="en.wikipedia")]},
        {"items": [item(START, 1, project="es.wikipedia.org.evil")]},
        ["lista en la raíz"],
    ],
)
async def test_invalid_payloads_are_permanent_errors(mock_api, payload) -> None:
    _route(mock_api).respond(200, json=payload)

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "invalid_response"
    assert result.observations == ()


@pytest.mark.anyio
async def test_non_json_body_is_invalid(mock_api) -> None:
    _route(mock_api).respond(200, text="<html>error</html>")

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.error.code == "invalid_response"


# --- Errores HTTP ------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.ReadTimeout("lento"), "upstream_timeout"),
        (httpx.ConnectError("sin conexión"), "upstream_unreachable"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(500), "upstream_unavailable"),
        (httpx.Response(503), "upstream_unavailable"),
    ],
)
async def test_temporary_failures_are_transient(mock_api, response, code) -> None:
    route = _route(mock_api).mock(side_effect=[response] * 2)

    async with _client(max_retries=1) as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.TRANSIENT_ERROR
    assert result.error.code == code
    assert route.call_count == 2


@pytest.mark.anyio
async def test_bad_request_is_permanent(mock_api) -> None:
    route = _route(mock_api).respond(400)

    async with _client(max_retries=2) as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "upstream_rejected"
    assert route.call_count == 1


# --- Configuración y validación en el conector ---------------------------------------


@pytest.mark.anyio
async def test_requires_contact_for_user_agent(mock_api) -> None:
    async with _client() as client:
        result = await _connector(client, contact=None).run(_query())

    assert result.outcome is Outcome.SKIPPED
    assert result.skipped_reason is Availability.UNCONFIGURED


@pytest.mark.anyio
async def test_disabled_connector_does_not_call_the_api(mock_api) -> None:
    route = mock_api.get(url__startswith="https://wikimedia.org/")

    async with _client() as client:
        result = await _connector(client, enabled=False).run(_query())

    assert result.skipped_reason is Availability.DISABLED
    assert route.call_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("query", "kwargs"),
    [
        (ConnectorQuery(), {}),  # sin parámetros de Wikimedia
        (_query(end=TODAY), {}),  # día no cerrado
        (_query(start=TODAY - timedelta(days=40), end=TODAY - timedelta(days=1)), {"max_days": 30}),
        (_query(articles=("A", "B", "C")), {"max_articles": 2}),
        (_query(projects=("en.wikipedia.org",)), {}),  # proyecto no configurado
    ],
)
async def test_connector_rejects_invalid_queries_without_calling_api(mock_api, query, kwargs) -> None:
    route = mock_api.get(url__startswith="https://wikimedia.org/")

    async with _client() as client:
        result = await _connector(client, **kwargs).run(query)

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error.code == "invalid_parameter"
    assert route.call_count == 0


def test_invalid_configured_project_is_rejected() -> None:
    with pytest.raises(ValueError):
        _connector(_client(), default_projects=("wikipedia.org",))


@pytest.mark.anyio
async def test_no_real_network_is_used(block_network: list[str]) -> None:
    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert block_network == ["wikimedia.org"]
    block_network.clear()


@pytest.mark.anyio
@pytest.mark.parametrize("returned_project", ["es.wikipedia", "es.wikipedia.org"])
async def test_both_project_spellings_are_accepted(mock_api, returned_project: str) -> None:
    """La especificación usa el dominio; la API real responde sin ".org"."""
    _route(mock_api).respond(200, json={"items": [item(START, 9, project=returned_project)]})

    async with _client() as client:
        result = await _connector(client).run(_query())

    assert result.outcome is Outcome.OK
    assert result.observations[0].subject_ref == "es.wikipedia.org:Tema_de_prueba"
