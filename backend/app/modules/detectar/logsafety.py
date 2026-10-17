"""Eliminación de secretos en textos de registro y mensajes de error.

``redact`` se aplica a todo texto que pueda contener URLs, cabeceras o mensajes de
fuentes externas antes de registrarlo o guardarlo. ``RedactingFilter`` hace lo mismo con
los registros de ``logging``, incluidos los de httpx, que escribe URLs completas.
"""

import logging
import re
import threading

REDACTED = "***"

_SENSITIVE_PARAMS = (
    r"api[_-]?key|key|access[_-]?token|refresh[_-]?token|token|auth|password|passwd|"
    r"secret|client[_-]?secret|signature|sig|session|cookie"
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Usuario y contraseña dentro de una URL.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1***:***@"),
    # Parámetros sensibles en query strings, formularios o texto libre ("token=...").
    # El lookbehind evita falsos positivos como "monkey=1".
    (
        re.compile(rf"(?i)((?<![a-z0-9_-])(?:{_SENSITIVE_PARAMS})=)[^&#\s'\",;)]+"),
        r"\1" + REDACTED,
    ),
    # Cabeceras de autorización y cookies.
    (
        re.compile(r"(?i)\b((?:proxy-)?authorization|x-api-key)(\s*[:=]\s*)[^\r\n,'\"}]+"),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"(?i)\b(set-cookie|cookie)(\s*[:=]\s*)[^\r\n'\"}]+"), r"\1\2" + REDACTED),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*"), "Bearer " + REDACTED),
    # Pares clave/valor estilo JSON o diccionario.
    (
        re.compile(
            rf"(?i)(['\"](?:{_SENSITIVE_PARAMS}|password)['\"]\s*:\s*)(['\"])[^'\"]*\2"
        ),
        r"\1\2" + REDACTED + r"\2",
    ),
)

_MIN_SECRET_LENGTH = 6
_known_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Registra un valor concreto (por ejemplo una clave de API) para ocultarlo siempre."""
    if value and len(value) >= _MIN_SECRET_LENGTH:
        with _lock:
            _known_secrets.add(value)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    with _lock:
        secrets = sorted(_known_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


class RedactingFilter(logging.Filter):
    """Reescribe el mensaje final del registro sin secretos."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message or record.args:
            record.msg = cleaned
            record.args = None
        return True


# Bibliotecas que registran URLs completas por su cuenta.
_THIRD_PARTY_LOGGERS = ("httpx", "httpcore")


def install_third_party_redaction() -> None:
    """Agrega el filtro a los loggers de httpx y httpcore. Es idempotente."""
    for name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
