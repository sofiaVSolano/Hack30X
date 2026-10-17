"""Cliente HTTP compartido por los conectores.

- Tiempos de espera explícitos (conexión, lectura, escritura y pool).
- Reintentos limitados (máximo 3), solo en GET, solo ante timeouts, errores de
  transporte, 429 y 5xx temporales; espera exponencial con variación aleatoria y respeto
  de ``Retry-After`` hasta un máximo.
- 4xx (excepto 429) y respuestas inválidas son errores definitivos y no se reintentan.
- Las URLs se registran sin secretos.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Self

import httpx

from app.modules.detectar import __version__
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.errors import (
    PermanentSourceError,
    TransientSourceError,
)
from app.modules.detectar.logsafety import install_third_party_redaction, redact

logger = logging.getLogger(__name__)

MAX_RETRIES_LIMIT = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpSettings:
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    write_timeout: float = 10.0
    pool_timeout: float = 5.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 8.0
    retry_after_max_seconds: float = 30.0
    max_response_bytes: int = 5_000_000
    max_redirects: int = 3
    user_agent: str = f"HACK30X-DETECTAR/{__version__}"

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= MAX_RETRIES_LIMIT:
            raise ValueError(f"max_retries debe estar entre 0 y {MAX_RETRIES_LIMIT}")
        for name in ("connect_timeout", "read_timeout", "write_timeout", "pool_timeout"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser positivo")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes debe ser positivo")

    @classmethod
    def from_settings(cls, settings: DetectarSettings) -> "HttpSettings":
        user_agent = f"HACK30X-DETECTAR/{__version__}"
        if settings.http_contact:
            user_agent += f" ({settings.http_contact})"
        return cls(
            connect_timeout=settings.http_connect_timeout_seconds,
            read_timeout=settings.http_read_timeout_seconds,
            max_retries=settings.http_max_retries,
            user_agent=f"{user_agent} httpx/{httpx.__version__}",
        )


Sleep = Callable[[float], Awaitable[None]]


class HttpClient:
    """Cliente asíncrono para usar con ``async with``. Cuenta los intentos realizados."""

    def __init__(
        self,
        settings: HttpSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings or HttpSettings()
        self._sleep = sleep
        self._jitter = jitter
        self._calls = 0
        install_third_party_redaction()
        s = self._settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=s.connect_timeout, read=s.read_timeout, write=s.write_timeout, pool=s.pool_timeout
            ),
            headers={"User-Agent": s.user_agent},
            follow_redirects=True,
            max_redirects=s.max_redirects,
            transport=transport,
        )

    @property
    def calls(self) -> int:
        return self._calls

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> httpx.Response:
        """GET con reintentos. ``max_bytes`` solo puede reducir el límite general."""
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes debe ser positivo")
        limit = min(self._settings.max_response_bytes, max_bytes or self._settings.max_response_bytes)
        safe_url = redact(url)
        attempt = 0
        while True:
            attempt += 1
            self._calls += 1
            retry_after: float | None = None
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.TimeoutException:
                error: TransientSourceError = TransientSourceError(
                    "upstream_timeout", f"Tiempo de espera agotado: {safe_url}"
                )
            except httpx.TransportError as exc:
                error = TransientSourceError(
                    "upstream_unreachable", f"{type(exc).__name__} al consultar {safe_url}"
                )
            else:
                status = response.status_code
                if status in RETRYABLE_STATUS:
                    code = "rate_limited" if status == 429 else "upstream_unavailable"
                    error = TransientSourceError(
                        code, f"HTTP {status} en {safe_url}", status_code=status
                    )
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                elif status >= 400:
                    raise PermanentSourceError(
                        "upstream_rejected", f"HTTP {status} en {safe_url}", status_code=status
                    )
                else:
                    if len(response.content) > limit:
                        raise PermanentSourceError(
                            "response_too_large", f"La respuesta supera {limit} bytes"
                        )
                    return response

            if attempt > self._settings.max_retries:
                raise error
            if retry_after is not None and retry_after > self._settings.retry_after_max_seconds:
                # La fuente pide esperar más de lo razonable: se informa como error temporal.
                raise error
            delay = retry_after if retry_after is not None else self._backoff(attempt)
            logger.warning(
                "Reintento %d/%d tras %s (espera %.2fs)",
                attempt,
                self._settings.max_retries,
                error.code,
                delay,
            )
            await self._sleep(delay)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.get(url, **kwargs)
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PermanentSourceError(
                "invalid_response", f"JSON inválido en {redact(url)}: {type(exc).__name__}"
            ) from None

    async def get_text(self, url: str, **kwargs: Any) -> str:
        return (await self.get(url, **kwargs)).text

    def _backoff(self, attempt: int) -> float:
        s = self._settings
        base = min(s.backoff_max_seconds, s.backoff_base_seconds * 2 ** (attempt - 1))
        return base * (0.5 + 0.5 * self._jitter())


def _parse_retry_after(value: str | None) -> float | None:
    """Solo se acepta la forma en segundos; las fechas HTTP se ignoran."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
