"""Contrato común de los conectores, con conectores falsos (sin red)."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.modules.detectar.connectors.base import (
    Availability,
    ConnectorError,
    ConnectorQuery,
    ConnectorResult,
    FetchOutput,
    Outcome,
)
from app.modules.detectar.connectors.errors import (
    PermanentSourceError,
    TransientSourceError,
)
from app.modules.detectar.storage.models import Source

from ..fakes import START, FakeConnector
from ..storage.factories import make_observation

pytestmark = pytest.mark.anyio

QUERY = ConnectorQuery(countries=("MX",))


def _returns(*observations, partial_error=None, http_calls=1):
    async def behaviour(_query: ConnectorQuery) -> FetchOutput:
        return FetchOutput(observations, http_calls=http_calls, partial_error=partial_error)

    return behaviour


def _raises(error: Exception):
    async def behaviour(_query: ConnectorQuery) -> FetchOutput:
        raise error

    return behaviour


async def test_ok_result_records_timing_and_observations() -> None:
    connector = FakeConnector(Source.WIKIMEDIA, _returns(make_observation(), http_calls=2))

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.OK
    assert result.source is Source.WIKIMEDIA
    assert len(result.observations) == 1
    assert result.http_calls == 2
    assert result.error is None
    assert result.started_at == START
    assert result.finished_at == START + timedelta(seconds=1)


async def test_empty_response_is_not_an_error() -> None:
    result = await FakeConnector(Source.WIKIMEDIA, _returns()).run(QUERY)

    assert result.outcome is Outcome.EMPTY
    assert result.observations == ()
    assert result.error is None


@pytest.mark.parametrize("availability", [Availability.DISABLED, Availability.UNCONFIGURED])
async def test_unavailable_connector_is_skipped_without_fetching(availability: Availability) -> None:
    connector = FakeConnector(Source.GDELT, _returns(), availability=availability)

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.SKIPPED
    assert result.skipped_reason is availability
    assert result.http_calls == 0
    assert connector.fetch_count == 0


async def test_transient_error_is_retryable() -> None:
    connector = FakeConnector(
        Source.GDELT, _raises(TransientSourceError("upstream_timeout", "lento")), http_calls=3
    )

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.TRANSIENT_ERROR
    assert result.error == ConnectorError(code="upstream_timeout", detail="lento", retryable=True)
    assert result.observations == ()
    assert result.http_calls == 3


async def test_permanent_error_is_not_retryable() -> None:
    connector = FakeConnector(
        Source.GDELT, _raises(PermanentSourceError("upstream_rejected", "HTTP 404"))
    )

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error is not None and result.error.retryable is False


async def test_unexpected_exception_is_contained_without_leaking_message() -> None:
    connector = FakeConnector(Source.GDELT, _raises(ValueError("token=valor-secreto-123")))

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error is not None
    assert result.error.code == "internal_error"
    assert "valor-secreto-123" not in result.model_dump_json()


async def test_partial_result_keeps_data_and_error() -> None:
    partial = TransientSourceError("rate_limited", "HTTP 429 en la página 2")
    connector = FakeConnector(Source.WIKIMEDIA, _returns(make_observation(), partial_error=partial))

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.PARTIAL
    assert len(result.observations) == 1
    assert result.error is not None and result.error.code == "rate_limited"


async def test_partial_error_without_data_is_an_error() -> None:
    partial = PermanentSourceError("invalid_response", "XML inválido")
    result = await FakeConnector(Source.WIKIMEDIA, _returns(partial_error=partial)).run(QUERY)

    assert result.outcome is Outcome.PERMANENT_ERROR


async def test_observations_from_another_source_are_rejected() -> None:
    connector = FakeConnector(Source.GDELT, _returns(make_observation()))  # obs. de Wikimedia

    result = await connector.run(QUERY)

    assert result.outcome is Outcome.PERMANENT_ERROR
    assert result.error is not None and result.error.code == "invalid_connector_output"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"outcome": Outcome.OK},  # OK sin observaciones
        {"outcome": Outcome.EMPTY, "observations": (make_observation(),)},
        {"outcome": Outcome.TRANSIENT_ERROR},  # error sin detalle
        {
            "outcome": Outcome.TRANSIENT_ERROR,
            "error": ConnectorError(code="x", detail="y", retryable=False),
        },
        {
            "outcome": Outcome.PERMANENT_ERROR,
            "observations": (make_observation(),),
            "error": ConnectorError(code="x", detail="y", retryable=False),
        },
        {"outcome": Outcome.SKIPPED},  # sin motivo
        {"outcome": Outcome.SKIPPED, "skipped_reason": Availability.READY},
        {"outcome": Outcome.EMPTY, "skipped_reason": Availability.DISABLED},
        {"outcome": Outcome.EMPTY, "finished_at": START - timedelta(seconds=1)},
    ],
)
def test_inconsistent_results_are_rejected(kwargs: dict) -> None:
    fields = {"source": Source.WIKIMEDIA, "started_at": START, "finished_at": START} | kwargs
    with pytest.raises(ValidationError):
        ConnectorResult(**fields)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"countries": ("mx",)},
        {"countries": ("MEX",)},
        {"since": START, "until": START},
        {"since": START.replace(tzinfo=None)},
        {"unexpected": 1},
    ],
)
def test_invalid_queries_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        ConnectorQuery(**kwargs)
