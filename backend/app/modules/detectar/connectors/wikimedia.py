"""Conector de Wikimedia Pageviews (visitas diarias por artículo).

Endpoint según la especificación OpenAPI oficial
(https://wikimedia.org/api/rest_v1/metrics/pageviews/api-spec.json, consultada el
17/10/2026)::

    GET https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
        {project}/{access}/{agent}/{article}/{granularity}/{start}/{end}

- ``project``: dominio, p. ej. ``es.wikipedia.org``.
- ``access``: all-access | desktop | mobile-app | mobile-web (aquí: all-access).
- ``agent``: all-agents | user | spider | automated (aquí: user, solo personas).
- ``article``: título codificado para URL.
- ``granularity``: daily | monthly (aquí: daily).
- ``start``/``end``: ``YYYYMMDDHH``.
- Respuesta 200: ``items[]`` con project, article, granularity, timestamp, access, agent,
  views. Códigos documentados: 200, 400, 404, 500.
- Verificado con una consulta real (17/10/2026, es.wikipedia.org, "México", 3 días): 3
  items con esas 7 claves; ``project`` llega como ``es.wikipedia`` (sin ``.org``) y
  ``article`` sin codificar ("México").

La política de acceso exige un User-Agent identificable con contacto y recomienda
esperar a que termine cada solicitud antes de enviar otra: las consultas son secuenciales.

Qué NO hace este conector:

- no infiere el país de los lectores a partir del idioma de la edición;
- no presenta visitas como búsquedas, publicaciones ni creadores;
- no rellena días ausentes: la especificación no dice que un día ausente sea cero;
- un 404 se registra como "sin datos" para ese artículo, nunca como cero visitas.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote

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
from app.modules.detectar.connectors.params import WIKIPEDIA_PROJECT_RE, WikimediaParams
from app.modules.detectar.storage.models import (
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import ObservationIn

PAGEVIEWS_BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
ACCESS = "all-access"
AGENT = "user"
GRANULARITY = "daily"
METRIC_PAGEVIEWS = "wiki_pageviews"
MAX_RESPONSE_BYTES = 2_000_000


class _ArticleNotFound(Exception):
    pass


def pageviews_url(project: str, article: str, start: date, end: date) -> str:
    # safe="" codifica también "/" (títulos como "AC/DC").
    encoded = quote(article, safe="")
    return (
        f"{PAGEVIEWS_BASE_URL}/{project}/{ACCESS}/{AGENT}/{encoded}/{GRANULARITY}/"
        f"{start:%Y%m%d}00/{end:%Y%m%d}00"
    )


def article_url(project: str, article: str) -> str:
    return f"https://{project}/wiki/{quote(article, safe='')}"


def _parse_day(timestamp: object) -> date:
    if not isinstance(timestamp, str) or len(timestamp) != 10 or not timestamp.isdigit():
        raise PermanentSourceError("invalid_response", f"timestamp inválido: {timestamp!r}")
    if not timestamp.endswith("00"):
        raise PermanentSourceError("invalid_response", f"timestamp diario inesperado: {timestamp}")
    try:
        return datetime.strptime(timestamp[:8], "%Y%m%d").date()
    except ValueError:
        raise PermanentSourceError("invalid_response", f"fecha inválida: {timestamp}") from None


def parse_pageviews(
    payload: object, *, project: str, start: date, end: date
) -> list[tuple[date, int, dict[str, object]]]:
    """Valida la respuesta y devuelve (día, visitas, item original) sin rellenar huecos."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise PermanentSourceError("invalid_response", "La respuesta no contiene items[]")
    rows: list[tuple[date, int, dict[str, object]]] = []
    seen: set[date] = set()
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise PermanentSourceError("invalid_response", "Elemento de items no es un objeto")
        views = item.get("views")
        if isinstance(views, bool) or not isinstance(views, int) or views < 0:
            raise PermanentSourceError("invalid_response", f"views inválido: {views!r}")
        if item.get("granularity") not in (None, GRANULARITY):
            raise PermanentSourceError("invalid_response", "granularidad inesperada")
        # Se solicita "es.wikipedia.org" (como indica la especificación), pero la API real
        # responde "es.wikipedia" (verificado el 17/10/2026). Se aceptan ambas formas.
        if item.get("project") not in (None, project, project.removesuffix(".org")):
            raise PermanentSourceError("invalid_response", "proyecto inesperado en la respuesta")
        day = _parse_day(item.get("timestamp"))
        if not start <= day <= end:
            raise PermanentSourceError("invalid_response", f"día fuera del intervalo: {day}")
        if day in seen:
            raise PermanentSourceError("invalid_response", f"día repetido: {day}")
        seen.add(day)
        rows.append((day, views, item))
    return rows


def _combine(errors: dict[str, SourceError]) -> SourceError:
    codes = {error.code for error in errors.values()}
    code = codes.pop() if len(codes) == 1 else "multiple_errors"
    detail = "; ".join(f"{key}: {error.code} ({error.detail})" for key, error in errors.items())
    if all(error.retryable for error in errors.values()):
        return TransientSourceError(code, detail)
    return PermanentSourceError(code, detail)


class WikimediaPageviewsConnector(BaseConnector):
    source = Source.WIKIMEDIA

    def __init__(
        self,
        client: HttpClient,
        *,
        enabled: bool,
        contact: str | None,
        default_projects: Sequence[str],
        max_days: int,
        max_articles: int,
        clock: Clock = utc_now,
        today: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(clock=clock)
        for project in default_projects:
            if not WIKIPEDIA_PROJECT_RE.match(project):
                raise ValueError(f"Proyecto de Wikipedia inválido: {project!r}")
        if max_days < 1 or max_articles < 1:
            raise ValueError("max_days y max_articles deben ser positivos")
        self._client = client
        self._enabled = enabled
        self._contact = contact
        self._projects = tuple(dict.fromkeys(default_projects))
        self._max_days = max_days
        self._max_articles = max_articles
        self._today = today or (lambda: self._clock().astimezone(UTC).date())
        self._calls_at_start = client.calls

    def availability(self) -> ConnectorAvailability:
        if not self._enabled:
            return ConnectorAvailability(Availability.DISABLED, "Desactivado por configuración")
        if not self._contact:
            return ConnectorAvailability(
                Availability.UNCONFIGURED,
                "Falta DETECTAR_HTTP_CONTACT: Wikimedia exige un User-Agent con contacto",
            )
        if not self._projects:
            return ConnectorAvailability(Availability.UNCONFIGURED, "No hay proyectos configurados")
        return ConnectorAvailability(Availability.READY, "Configurado")

    def _http_calls_so_far(self) -> int:
        return self._client.calls - self._calls_at_start

    def _validate(self, params: WikimediaParams | None) -> tuple[WikimediaParams, tuple[str, ...]]:
        if params is None:
            raise PermanentSourceError(
                "invalid_parameter", "Wikimedia requiere artículos y un intervalo de fechas"
            )
        if params.end >= self._today():
            raise PermanentSourceError(
                "invalid_parameter", "end debe ser anterior a hoy (UTC): el día en curso no está cerrado"
            )
        if params.days > self._max_days:
            raise PermanentSourceError(
                "invalid_parameter", f"El intervalo supera {self._max_days} días"
            )
        if len(params.articles) > self._max_articles:
            raise PermanentSourceError(
                "invalid_parameter", f"Se admiten como máximo {self._max_articles} artículos"
            )
        projects = params.projects or self._projects
        not_allowed = [p for p in projects if p not in self._projects]
        if not_allowed:
            raise PermanentSourceError(
                "invalid_parameter", f"Proyectos no configurados: {', '.join(not_allowed)}"
            )
        return params, projects

    async def _fetch(self, query: ConnectorQuery) -> FetchOutput:
        params, projects = self._validate(query.wikimedia)
        self._calls_at_start = self._client.calls
        requested = {"start": params.start.isoformat(), "end": params.end.isoformat()}
        observations: list[ObservationIn] = []
        errors: dict[str, SourceError] = {}
        not_found: list[str] = []

        for project in projects:
            language = project.split(".", 1)[0]
            for article in params.articles:
                key = f"{project}:{article}"
                try:
                    rows = await self._fetch_article(project, article, params)
                except _ArticleNotFound:
                    not_found.append(key)
                    continue
                except SourceError as error:
                    errors[key] = error
                    continue
                consulted_at = self._clock().replace(microsecond=0)
                for day, views, item in rows:
                    period_start = datetime.combine(day, time.min, tzinfo=UTC)
                    observations.append(
                        ObservationIn(
                            source=Source.WIKIMEDIA,
                            metric_key=METRIC_PAGEVIEWS,
                            unit=Unit.VIEWS,
                            value=float(views),
                            observed_at=consulted_at,
                            period_start=period_start,
                            period_end=period_start + timedelta(days=1),
                            granularity=Granularity.DAY,
                            # La edición de Wikipedia no identifica el país de los lectores.
                            language=language,
                            language_basis=LanguageBasis.QUERY_FILTER,
                            subject_type=SubjectType.WIKI_ARTICLE,
                            subject_ref=key,
                            source_url=article_url(project, article),
                            raw_excerpt={
                                "project": project,
                                "article": article,
                                "article_returned": item.get("article"),
                                "access": ACCESS,
                                "agent": AGENT,
                                "granularity": GRANULARITY,
                                "timestamp": item.get("timestamp"),
                                "views": views,
                                "requested_interval": requested,
                            },
                        )
                    )

        if not_found:
            errors["sin_datos"] = PermanentSourceError(
                "article_not_found",
                "La API respondió 404 (sin datos; no equivale a cero visitas) para: "
                + ", ".join(not_found),
            )
        partial_error = _combine(errors) if errors else None
        return FetchOutput(observations, http_calls=self._http_calls_so_far(), partial_error=partial_error)

    async def _fetch_article(
        self, project: str, article: str, params: WikimediaParams
    ) -> list[tuple[date, int, dict[str, object]]]:
        url = pageviews_url(project, article, params.start, params.end)
        try:
            response = await self._client.get(url, max_bytes=MAX_RESPONSE_BYTES)
        except PermanentSourceError as error:
            if error.status_code == 404:
                raise _ArticleNotFound from None
            raise
        try:
            payload = response.json()
        except ValueError:
            raise PermanentSourceError("invalid_response", "JSON inválido") from None
        return parse_pageviews(payload, project=project, start=params.start, end=params.end)
