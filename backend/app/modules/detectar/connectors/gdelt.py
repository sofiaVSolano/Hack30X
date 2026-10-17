"""Conector de GDELT DOC 2.0: cobertura de noticias en línea por término.

Qué devuelve (documentación oficial, https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/,
consultada el 17/10/2026):

- ``mode=TimelineVolRaw``: "the actual number of distinct articles that matched your
  query" por intervalo de tiempo, más un campo ``norm`` con "the total number of all
  articles GDELT monitored during that time interval" (solo en CSV y JSON).
- Ventana móvil de los últimos 3 meses; ``STARTDATETIME``/``ENDDATETIME`` en
  ``YYYYMMDDHHMMSS``. Con intervalos de más de una semana la resolución es diaria.
- ``sourcelang:`` = idioma original del artículo; ``sourcecountry:`` = país del MEDIO.
- Términos de uso: uso libre (también comercial) con cita a GDELT y enlace a
  https://www.gdeltproject.org/.

Qué representa cada observación (``gdelt_article_count``, unidad ``articles``): cuántos
artículos de noticias monitoreados por GDELT coincidieron con la consulta ese día. Mide
cobertura periodística; NO mide búsquedas, consumo de contenido ni cantidad de creadores.
``norm`` se conserva en ``raw_excerpt`` sin convertirlo en métrica (no consta si respeta
los filtros de la consulta).

Supuestos no verificados con la API real (las consultas de prueba devolvieron ``{}`` y
luego HTTP 429): la forma ``{"timeline": [{"series": str, "data": [{"date":
"YYYYMMDDTHHMMSSZ", "value": int, "norm": int}]}]}``. El parser exige exactamente esa forma
y trata cualquier otra como respuesta inválida, para que un supuesto erróneo falle de forma
visible. Las respuestas de error de GDELT en texto plano se detectan aparte.

Límites: no hay cifras oficiales; se observó HTTP 429 y fuentes de terceros mencionan
una solicitud cada 5 segundos, así que las consultas son secuenciales y espaciadas.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode

from app.modules.detectar.connectors.base import (
    Availability,
    BaseConnector,
    Clock,
    ConnectorAvailability,
    ConnectorQuery,
    FetchOutput,
    utc_now,
)
from app.modules.detectar.connectors.errors import (
    PermanentSourceError,
    SourceError,
    TransientSourceError,
)
from app.modules.detectar.connectors.http import HttpClient
from app.modules.detectar.connectors.params import (
    GDELT_MAX_LOOKBACK_DAYS,
    GDELT_SOURCE_LANGUAGES,
    GdeltParams,
)
from app.modules.detectar.logsafety import redact
from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import ObservationIn

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MODE = "TimelineVolRaw"
METRIC_ARTICLES = "gdelt_article_count"
MAX_RESPONSE_BYTES = 2_000_000
ATTRIBUTION = "Datos: The GDELT Project (https://www.gdeltproject.org/)"

_DATE_RE = re.compile(r"^\d{8}T\d{6}Z$")
_RATE_LIMIT_TEXT = re.compile(r"limit requests|too many requests|rate limit", re.IGNORECASE)

Sleep = Callable[[float], Awaitable[None]]


def request_params(query: str, params: GdeltParams) -> dict[str, str]:
    return {
        "query": query,
        "mode": MODE,
        "format": "json",
        "startdatetime": f"{params.start:%Y%m%d}000000",
        "enddatetime": f"{params.end:%Y%m%d}235959",
    }


def _parse_day(value: object) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise PermanentSourceError("invalid_response", f"fecha inválida: {value!r:.40}")
    if value[9:15] != "000000":
        raise PermanentSourceError("invalid_response", f"se esperaba resolución diaria: {value}")
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        raise PermanentSourceError("invalid_response", f"fecha inválida: {value}") from None


def _count(value: object, name: str) -> int | None:
    if value is None and name == "norm":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise PermanentSourceError("invalid_response", f"{name} inválido: {value!r:.40}")
    if isinstance(value, float) and not value.is_integer():
        raise PermanentSourceError("invalid_response", f"{name} no es un conteo: {value}")
    return int(value)


def parse_timeline(
    content: bytes, *, start: date, end: date
) -> tuple[str | None, list[tuple[date, int, int | None]]]:
    """Devuelve (nombre de la serie, [(día, artículos, norm)]) sin rellenar días ausentes."""
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = content[:300].decode("utf-8", errors="replace").strip()
        if _RATE_LIMIT_TEXT.search(text):
            raise TransientSourceError("rate_limited", "GDELT pidió reducir la frecuencia") from None
        # GDELT responde errores de consulta en texto plano con HTTP 200.
        raise PermanentSourceError(
            "invalid_response", f"Respuesta no JSON: {redact(text)[:120]!r}"
        ) from None

    if payload == {}:
        return None, []  # observado con consultas sin coincidencias
    if not isinstance(payload, dict) or not isinstance(payload.get("timeline"), list):
        raise PermanentSourceError("invalid_response", "La respuesta no contiene timeline[]")
    timeline = payload["timeline"]
    if not timeline:
        return None, []
    if len(timeline) != 1 or not isinstance(timeline[0], dict):
        raise PermanentSourceError("invalid_response", "Se esperaba exactamente una serie")
    series = timeline[0]
    data = series.get("data")
    if not isinstance(data, list):
        raise PermanentSourceError("invalid_response", "La serie no contiene data[]")

    rows: list[tuple[date, int, int | None]] = []
    seen: set[date] = set()
    for point in data:
        if not isinstance(point, dict):
            raise PermanentSourceError("invalid_response", "Punto de la serie no es un objeto")
        day = _parse_day(point.get("date"))
        if not start <= day <= end:
            raise PermanentSourceError("invalid_response", f"día fuera del intervalo: {day}")
        if day in seen:
            raise PermanentSourceError("invalid_response", f"día repetido: {day}")
        seen.add(day)
        value = _count(point.get("value"), "value")
        assert value is not None
        rows.append((day, value, _count(point.get("norm"), "norm")))
    name = series.get("series")
    return (name if isinstance(name, str) else None), rows


def _combine(errors: dict[str, SourceError]) -> SourceError:
    codes = {error.code for error in errors.values()}
    code = codes.pop() if len(codes) == 1 else "multiple_errors"
    detail = "; ".join(f"{key}: {error.code} ({error.detail})" for key, error in errors.items())
    if all(error.retryable for error in errors.values()):
        return TransientSourceError(code, detail)
    return PermanentSourceError(code, detail)


class GdeltDocConnector(BaseConnector):
    source = Source.GDELT

    def __init__(
        self,
        client: HttpClient,
        *,
        enabled: bool,
        max_requests: int,
        min_interval_seconds: float,
        clock: Clock = utc_now,
        today: Callable[[], date] | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(clock=clock)
        if max_requests < 1 or min_interval_seconds < 0:
            raise ValueError("max_requests debe ser positivo y min_interval_seconds no negativo")
        self._client = client
        self._enabled = enabled
        self._max_requests = max_requests
        self._min_interval = min_interval_seconds
        self._today = today or (lambda: self._clock().astimezone(UTC).date())
        self._sleep = sleep
        self._calls_at_start = client.calls

    def availability(self) -> ConnectorAvailability:
        if not self._enabled:
            return ConnectorAvailability(Availability.DISABLED, "Desactivado por configuración")
        return ConnectorAvailability(Availability.READY, "Sin credenciales requeridas")

    def _http_calls_so_far(self) -> int:
        return self._client.calls - self._calls_at_start

    def _validate(self, params: GdeltParams | None) -> GdeltParams:
        if params is None:
            raise PermanentSourceError("invalid_parameter", "GDELT requiere términos y un intervalo")
        today = self._today()
        if params.end >= today:
            raise PermanentSourceError("invalid_parameter", "end debe ser anterior a hoy (UTC)")
        if params.start < today - timedelta(days=GDELT_MAX_LOOKBACK_DAYS):
            raise PermanentSourceError(
                "invalid_parameter",
                f"start debe estar dentro de los últimos {GDELT_MAX_LOOKBACK_DAYS} días",
            )
        if len(params.queries()) > self._max_requests:
            raise PermanentSourceError(
                "invalid_parameter",
                f"La consulta requiere {len(params.queries())} solicitudes; máximo {self._max_requests}",
            )
        return params

    async def _fetch(self, query: ConnectorQuery) -> FetchOutput:
        params = self._validate(query.gdelt)
        self._calls_at_start = self._client.calls
        language = GDELT_SOURCE_LANGUAGES.get(params.source_language) if params.source_language else None
        requested = {"start": params.start.isoformat(), "end": params.end.isoformat()}
        observations: list[ObservationIn] = []
        errors: dict[str, SourceError] = {}

        for index, (term, gdelt_query, country) in enumerate(params.queries()):
            if index and self._min_interval:
                await self._sleep(self._min_interval)  # consultas espaciadas por cortesía
            api_params = request_params(gdelt_query, params)
            try:
                response = await self._client.get(
                    GDELT_DOC_URL, params=api_params, max_bytes=MAX_RESPONSE_BYTES
                )
                series, rows = parse_timeline(response.content, start=params.start, end=params.end)
            except SourceError as error:
                errors[gdelt_query] = error
                continue
            consulted_at = self._clock().replace(microsecond=0)
            source_url = f"{GDELT_DOC_URL}?{urlencode(api_params)}"
            for day, articles, norm in rows:
                period_start = datetime.combine(day, time.min, tzinfo=UTC)
                observations.append(
                    ObservationIn(
                        source=Source.GDELT,
                        metric_key=METRIC_ARTICLES,
                        unit=Unit.ARTICLES,
                        value=float(articles),
                        observed_at=consulted_at,
                        period_start=period_start,
                        period_end=period_start + timedelta(days=1),
                        granularity=Granularity.DAY,
                        # País del MEDIO que publica, solo si se filtró por él.
                        country=country,
                        country_basis=(
                            CountryBasis.PUBLISHER_COUNTRY if country else CountryBasis.NONE
                        ),
                        language=language,
                        language_basis=(
                            LanguageBasis.QUERY_FILTER if language else LanguageBasis.NONE
                        ),
                        subject_type=SubjectType.NEWS_QUERY,
                        subject_ref=gdelt_query,
                        source_url=source_url,
                        raw_excerpt={
                            "term": term,
                            "query": gdelt_query,
                            "mode": MODE,
                            "series": series,
                            "date": f"{day:%Y%m%d}T000000Z",
                            "value": articles,
                            "norm": norm,
                            "requested_interval": requested,
                            "attribution": ATTRIBUTION,
                        },
                    )
                )

        partial_error = _combine(errors) if errors else None
        return FetchOutput(observations, http_calls=self._http_calls_so_far(), partial_error=partial_error)
