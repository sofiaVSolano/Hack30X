"""Cliente HTTP compartido. Todas las respuestas se simulan con respx; no hay red real."""

import logging

import httpx
import pytest
import respx

from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.errors import (
    PermanentSourceError,
    TransientSourceError,
)
from app.modules.detectar.connectors.http import HttpClient, HttpSettings

pytestmark = pytest.mark.anyio

URL = "https://api.ejemplo.test/datos"


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def sleeps() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def mock_api():
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


def _client(sleeps: SleepRecorder, **settings) -> HttpClient:
    return HttpClient(HttpSettings(**settings), sleep=sleeps, jitter=lambda: 0.0)


async def test_returns_json_and_sends_user_agent(mock_api, sleeps) -> None:
    route = mock_api.get(URL).respond(200, json={"items": [1, 2]})

    async with _client(sleeps) as client:
        data = await client.get_json(URL, params={"q": "tema"})
        calls = client.calls

    assert data == {"items": [1, 2]}
    assert calls == 1
    request = route.calls.last.request
    assert request.headers["User-Agent"].startswith("HACK30X-DETECTAR/")
    assert request.url.params["q"] == "tema"
    assert sleeps.delays == []


async def test_retries_server_error_then_succeeds(mock_api, sleeps) -> None:
    mock_api.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )

    async with _client(sleeps, max_retries=2) as client:
        data = await client.get_json(URL)
        calls = client.calls

    assert data == {"ok": True}
    assert calls == 2
    assert sleeps.delays == [0.25]  # backoff 0.5 s con variación 0 => 0.5 * 0.5


async def test_respects_retry_after_on_429(mock_api, sleeps) -> None:
    mock_api.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, text="ok")]
    )

    async with _client(sleeps) as client:
        assert await client.get_text(URL) == "ok"

    assert sleeps.delays == [2.0]


async def test_excessive_retry_after_is_not_waited(mock_api, sleeps) -> None:
    mock_api.get(URL).respond(429, headers={"Retry-After": "3600"})

    async with _client(sleeps) as client:
        with pytest.raises(TransientSourceError) as excinfo:
            await client.get(URL)
        calls = client.calls

    assert excinfo.value.code == "rate_limited"
    assert calls == 1
    assert sleeps.delays == []


async def test_retries_are_limited(mock_api, sleeps) -> None:
    route = mock_api.get(URL).respond(503)

    async with _client(sleeps, max_retries=2) as client:
        with pytest.raises(TransientSourceError) as excinfo:
            await client.get(URL)

    assert excinfo.value.code == "upstream_unavailable"
    assert excinfo.value.retryable is True
    assert route.call_count == 3  # 1 intento + 2 reintentos
    assert sleeps.delays == [0.25, 0.5]


async def test_client_error_is_permanent_and_not_retried(mock_api, sleeps) -> None:
    route = mock_api.get(URL).respond(404)

    async with _client(sleeps) as client:
        with pytest.raises(PermanentSourceError) as excinfo:
            await client.get(URL)

    assert excinfo.value.code == "upstream_rejected"
    assert route.call_count == 1
    assert sleeps.delays == []


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (httpx.ReadTimeout("lento"), "upstream_timeout"),
        (httpx.ConnectTimeout("lento"), "upstream_timeout"),
        (httpx.ConnectError("sin conexión"), "upstream_unreachable"),
    ],
)
async def test_timeouts_and_transport_errors_are_transient(mock_api, sleeps, exception, code) -> None:
    route = mock_api.get(URL).mock(side_effect=exception)

    async with _client(sleeps, max_retries=1) as client:
        with pytest.raises(TransientSourceError) as excinfo:
            await client.get(URL)

    assert excinfo.value.code == code
    assert route.call_count == 2


async def test_zero_retries_means_single_attempt(mock_api, sleeps) -> None:
    route = mock_api.get(URL).respond(500)

    async with _client(sleeps, max_retries=0) as client:
        with pytest.raises(TransientSourceError):
            await client.get(URL)

    assert route.call_count == 1


async def test_invalid_json_is_permanent(mock_api, sleeps) -> None:
    mock_api.get(URL).respond(200, text="<html>no es json</html>")

    async with _client(sleeps) as client:
        with pytest.raises(PermanentSourceError) as excinfo:
            await client.get_json(URL)

    assert excinfo.value.code == "invalid_response"


async def test_oversized_response_is_rejected(mock_api, sleeps) -> None:
    mock_api.get(URL).respond(200, content=b"x" * 101)

    async with _client(sleeps, max_response_bytes=100) as client:
        with pytest.raises(PermanentSourceError) as excinfo:
            await client.get(URL)

    assert excinfo.value.code == "response_too_large"


async def test_errors_do_not_expose_secrets(mock_api, sleeps) -> None:
    secret_url = f"{URL}?key=CLAVE-SUPER-SECRETA&q=tema"
    mock_api.get(URL).respond(403)

    async with _client(sleeps) as client:
        with pytest.raises(PermanentSourceError) as excinfo:
            await client.get(secret_url)

    assert "CLAVE-SUPER-SECRETA" not in str(excinfo.value)
    assert "key=***" in excinfo.value.detail


async def test_httpx_request_logs_are_redacted(mock_api, sleeps, caplog) -> None:
    mock_api.get(URL).respond(200, text="ok")
    caplog.set_level(logging.INFO, logger="httpx")

    async with _client(sleeps) as client:
        await client.get(URL, params={"access_token": "TOKEN-SECRETO-999"})

    assert caplog.records, "httpx debería registrar la solicitud"
    assert "TOKEN-SECRETO-999" not in caplog.text
    assert "access_token=***" in caplog.text


async def test_unmocked_request_never_reaches_the_network(block_network: list[str]) -> None:
    async with HttpClient(HttpSettings(max_retries=0)) as client:
        with pytest.raises(RuntimeError, match="Conexión de red bloqueada"):
            await client.get("https://example.org/")

    assert block_network == ["example.org"]
    block_network.clear()  # el intento era esperado


@pytest.mark.parametrize(
    "kwargs",
    [{"max_retries": 4}, {"max_retries": -1}, {"read_timeout": 0}, {"max_response_bytes": 0}],
)
def test_invalid_http_settings_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        HttpSettings(**kwargs)


def test_http_settings_from_detectar_settings() -> None:
    settings = DetectarSettings(
        http_connect_timeout_seconds=3,
        http_read_timeout_seconds=9,
        http_max_retries=1,
        http_contact="equipo@hack30x.example",
    )

    http = HttpSettings.from_settings(settings)

    assert (http.connect_timeout, http.read_timeout, http.max_retries) == (3, 9, 1)
    assert "(equipo@hack30x.example)" in http.user_agent
