import logging

import pytest

from app.modules.detectar.logsafety import RedactingFilter, redact, register_secret


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("GET https://api.test/v3/search?part=id&key=AIzaFAKEKEY123&q=x", "AIzaFAKEKEY123"),
        ("https://api.test/?access_token=abc.def.ghi", "abc.def.ghi"),
        ("https://api.test/?API_KEY=MiClave999", "MiClave999"),
        ("Authorization: Bearer eyJhbGciOi.fake.token", "eyJhbGciOi.fake.token"),
        ("headers={'Authorization': 'Bearer abc123xyz'}", "abc123xyz"),
        ("Cookie: sessionid=abcd1234; csrftoken=zzz", "abcd1234"),
        ("https://usuario:contrasena123@host.test/ruta", "contrasena123"),
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ("x-api-key: llave-privada-77", "llave-privada-77"),
    ],
)
def test_redact_removes_secrets(text: str, secret: str) -> None:
    cleaned = redact(text)

    assert secret not in cleaned
    assert "***" in cleaned


def test_redact_keeps_harmless_text() -> None:
    text = "GET https://es.wikipedia.org/wiki/Temblor?action=view&monkey=1"

    assert redact(text) == text


def test_registered_secret_is_always_hidden() -> None:
    register_secret("valor-registrado-456")

    assert redact("error con valor-registrado-456 en la respuesta") == "error con *** en la respuesta"


def test_short_values_are_not_registered_as_secrets() -> None:
    register_secret("abc")

    assert redact("abc") == "abc"


def test_filter_redacts_formatted_log_records(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("tests.detectar.logsafety")
    logger.addFilter(RedactingFilter())
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("Consultando %s", "https://api.test/?token=TOKEN-ABC-123")
    finally:
        logger.filters.clear()

    assert "TOKEN-ABC-123" not in caplog.text
    assert "token=***" in caplog.text
