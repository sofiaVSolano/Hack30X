"""Errores controlados de las fuentes de datos.

- ``TransientSourceError``: puede resolverse reintentando más tarde (timeout, 429, 5xx).
- ``PermanentSourceError``: reintentar no lo resolverá (4xx, respuesta inválida).

Los mensajes se limpian de secretos al construirse.
"""

from app.modules.detectar.logsafety import redact

MAX_DETAIL_LENGTH = 500


class SourceError(Exception):
    retryable: bool = False

    def __init__(self, code: str, detail: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.detail = redact(detail)[:MAX_DETAIL_LENGTH]
        # Código HTTP de la respuesta, cuando el error proviene de una.
        self.status_code = status_code
        super().__init__(f"{code}: {self.detail}")


class TransientSourceError(SourceError):
    retryable = True


class PermanentSourceError(SourceError):
    retryable = False
