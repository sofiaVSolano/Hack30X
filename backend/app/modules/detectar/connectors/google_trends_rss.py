"""Conector de Google Trends "Trending now" mediante su RSS público por país.

Qué representa cada observación:

- ``gtr_trending_presence`` (unidad ``presence``, valor 1): el término aparecía en el RSS
  del país en el momento de la captura. Es una captura puntual, no una serie histórica de
  volumen de búsqueda; el historial se construye acumulando capturas reales.
- ``gtr_approx_traffic_min`` (unidad ``searches_lower_bound``): solo cuando el RSS trae
  un tráfico aproximado con forma de cota inferior ("200+", "2K+"). Si el texto existe
  pero no tiene esa forma, se guarda en ``value_text`` sin valor numérico. Si no existe,
  no se crea la observación.

La fecha de publicación original (``pubDate``), la posición en el feed y las noticias
relacionadas se conservan en ``raw_excerpt``. ``observed_at`` es la hora de la consulta.

Estructura observada el 16/10/2026 (resumen de una consulta al RSS de MX): espacio de
nombres ``ht`` = ``https://trends.google.com/trending/rss``; 10 ``<item>`` con ``title``,
``pubDate``, ``ht:approx_traffic``, ``ht:picture``, ``ht:picture_source`` y
``ht:news_item`` (``_title``, ``_snippet``, ``_url``, ``_picture``, ``_source``).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

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
from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    Source,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import ObservationIn

GTR_RSS_URL = "https://trends.google.com/trending/rss"
HT_NAMESPACE = "https://trends.google.com/trending/rss"
MAX_RSS_BYTES = 1_000_000
MAX_NEWS_ITEMS = 5
MAX_TEXT_LENGTH = 300

METRIC_PRESENCE = "gtr_trending_presence"
METRIC_TRAFFIC = "gtr_approx_traffic_min"

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
# "200+", "1,000+", "2K+", "1.5M+". Los puntos solo se aceptan como decimales con sufijo.
_TRAFFIC_RE = re.compile(r"^\s*(?P<num>\d{1,3}(?:,\d{3})*|\d+)(?:\.(?P<dec>\d+))?\s*(?P<suf>[KkMm])?\s*\+\s*$")


@dataclass(frozen=True)
class NewsItem:
    title: str | None
    url: str | None
    source: str | None


@dataclass(frozen=True)
class ParsedTrend:
    title: str
    feed_position: int
    approx_traffic: str | None
    pub_date: datetime | None
    pub_date_raw: str | None
    picture_source: str | None
    news: tuple[NewsItem, ...]


@dataclass(frozen=True)
class ParsedFeed:
    trends: tuple[ParsedTrend, ...]
    skipped_items: int


def _ht(tag: str) -> str:
    return f"{{{HT_NAMESPACE}}}{tag}"


def _text(element: Element, tag: str) -> str | None:
    value = element.findtext(tag)
    if value is None:
        return None
    value = value.strip()
    return value[:MAX_TEXT_LENGTH] if value else None


def _safe_url(value: str | None) -> str | None:
    if value and value.lower().startswith(("https://", "http://")):
        return value[:2000]
    return None


def parse_traffic_lower_bound(text: str | None) -> float | None:
    """Convierte "200+" o "2K+" en su cota inferior. Cualquier otra forma devuelve None."""
    if not text:
        return None
    match = _TRAFFIC_RE.match(text)
    if not match:
        return None
    if match["dec"] and not match["suf"]:
        return None  # "1.000+" es ambiguo: no se interpreta
    number = float(match["num"].replace(",", "") + (f".{match['dec']}" if match["dec"] else ""))
    multiplier = {"k": 1_000, "m": 1_000_000}.get((match["suf"] or "").lower(), 1)
    return number * multiplier


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed if parsed.tzinfo is not None else None


def parse_trends_rss(content: bytes) -> ParsedFeed:
    """Analiza el RSS con defusedxml (sin DTD ni entidades externas)."""
    try:
        root = fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as exc:
        raise PermanentSourceError("invalid_response", f"XML inválido: {type(exc).__name__}") from None
    if root.tag != "rss":
        raise PermanentSourceError("unexpected_format", f"Raíz inesperada: {root.tag[:50]!r}")
    channel = root.find("channel")
    if channel is None:
        raise PermanentSourceError("unexpected_format", "El RSS no contiene <channel>")

    trends: list[ParsedTrend] = []
    skipped = 0
    for position, item in enumerate(channel.findall("item"), start=1):
        title = _text(item, "title")
        if title is None:
            skipped += 1
            continue
        pub_date_raw = _text(item, "pubDate")
        news = tuple(
            NewsItem(
                title=_text(news_item, _ht("news_item_title")),
                url=_safe_url(_text(news_item, _ht("news_item_url"))),
                source=_text(news_item, _ht("news_item_source")),
            )
            for news_item in item.findall(_ht("news_item"))[:MAX_NEWS_ITEMS]
        )
        trends.append(
            ParsedTrend(
                title=title,
                feed_position=position,
                approx_traffic=_text(item, _ht("approx_traffic")),
                pub_date=_parse_pub_date(pub_date_raw),
                pub_date_raw=pub_date_raw,
                picture_source=_text(item, _ht("picture_source")),
                news=news,
            )
        )
    return ParsedFeed(trends=tuple(trends), skipped_items=skipped)


def trend_observations(trend: ParsedTrend, *, country: str, captured_at: datetime) -> list[ObservationIn]:
    feed_url = f"{GTR_RSS_URL}?geo={country}"
    common = {
        "source": Source.GOOGLE_TRENDS_RSS,
        "observed_at": captured_at,
        "period_start": captured_at,
        "granularity": Granularity.SNAPSHOT,
        "country": country,
        "country_basis": CountryBasis.REPORTED_BY_SOURCE,
        "subject_type": SubjectType.SEARCH_TERM,
        "subject_ref": trend.title,
        "source_url": feed_url,
        # pubDate original; None si falta o no se pudo interpretar (se conserva el texto).
        "source_published_at": trend.pub_date,
    }
    excerpt = {
        "pub_date": trend.pub_date.isoformat() if trend.pub_date else None,
        "pub_date_raw": trend.pub_date_raw,
        "feed_position": trend.feed_position,
        "approx_traffic": trend.approx_traffic,
        "picture_source": trend.picture_source,
        "news": [{"title": n.title, "url": n.url, "source": n.source} for n in trend.news],
    }
    observations = [
        ObservationIn(
            metric_key=METRIC_PRESENCE, unit=Unit.PRESENCE, value=1.0, raw_excerpt=excerpt, **common
        )
    ]
    if trend.approx_traffic is not None:
        observations.append(
            ObservationIn(
                metric_key=METRIC_TRAFFIC,
                unit=Unit.SEARCHES_LOWER_BOUND,
                value=parse_traffic_lower_bound(trend.approx_traffic),
                value_text=trend.approx_traffic[:64],
                raw_excerpt={"approx_traffic": trend.approx_traffic},
                **common,
            )
        )
    return observations


def _combine(errors: dict[str, SourceError]) -> SourceError:
    codes = {error.code for error in errors.values()}
    code = codes.pop() if len(codes) == 1 else "multiple_errors"
    detail = "; ".join(f"{country}: {error.code} ({error.detail})" for country, error in errors.items())
    if all(error.retryable for error in errors.values()):
        return TransientSourceError(code, detail)
    return PermanentSourceError(code, detail)


class GoogleTrendsRssConnector(BaseConnector):
    source = Source.GOOGLE_TRENDS_RSS

    def __init__(
        self,
        client: HttpClient,
        *,
        enabled: bool,
        default_countries: Sequence[str],
        clock: Clock = utc_now,
    ) -> None:
        super().__init__(clock=clock)
        for country in default_countries:
            if not _COUNTRY_RE.match(country):
                raise ValueError(f"Código de país inválido: {country!r}")
        self._client = client
        self._enabled = enabled
        self._default_countries = tuple(dict.fromkeys(default_countries))
        self._calls_at_start = client.calls

    def availability(self) -> ConnectorAvailability:
        if not self._enabled:
            return ConnectorAvailability(Availability.DISABLED, "Desactivado por configuración")
        if not self._default_countries:
            return ConnectorAvailability(Availability.UNCONFIGURED, "No hay países configurados")
        return ConnectorAvailability(Availability.READY, "Sin credenciales requeridas")

    def _http_calls_so_far(self) -> int:
        return self._client.calls - self._calls_at_start

    async def _fetch(self, query: ConnectorQuery) -> FetchOutput:
        countries = tuple(dict.fromkeys(query.countries)) or self._default_countries
        for country in countries:
            # ConnectorQuery ya valida el formato; se repite porque el valor va en la URL.
            if not _COUNTRY_RE.match(country):
                raise PermanentSourceError("invalid_parameter", f"País inválido: {country!r}")

        self._calls_at_start = self._client.calls
        observations: list[ObservationIn] = []
        errors: dict[str, SourceError] = {}
        skipped_items = 0
        for country in countries:
            try:
                response = await self._client.get(
                    GTR_RSS_URL, params={"geo": country}, max_bytes=MAX_RSS_BYTES
                )
                captured_at = self._clock().replace(microsecond=0)
                feed = parse_trends_rss(response.content)
            except SourceError as error:
                errors[country] = error
                continue
            skipped_items += feed.skipped_items
            for trend in feed.trends:
                observations.extend(trend_observations(trend, country=country, captured_at=captured_at))

        partial_error: SourceError | None = None
        if errors:
            partial_error = _combine(errors)
        elif skipped_items:
            partial_error = PermanentSourceError(
                "items_skipped", f"Se omitieron {skipped_items} elementos sin título"
            )
        return FetchOutput(observations, http_calls=self._http_calls_so_far(), partial_error=partial_error)
