"""Cálculo y persistencia de métricas ``metrics-v1``.

Usa solo vínculos de E7 vigentes con estado ``linked`` y las observaciones originales
correspondientes, del mismo ``data_mode``. No modifica ``raw_observations`` ni
``topic_links``. Es idempotente: recalcular la misma fecha de referencia actualiza la misma
fila (clave única por tema, fuente, ámbito, métrica, periodo y versión).
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.modules.detectar.connectors.base import Clock, utc_now
from app.modules.detectar.metrics import calculators as calc
from app.modules.detectar.metrics.definitions import (
    BY_KEY,
    PARAMS,
    RULES_VERSION,
    SOURCE_VALIDATED,
)
from app.modules.detectar.storage.models import (
    CountryBasis,
    DataMode,
    Granularity,
    LinkStatus,
    MetricStatus,
    MetricValue,
    RawObservation,
    RulesVersion,
    Source,
    TopicLink,
)
from app.modules.detectar.storage.repository import require_data_mode

GTR_PRESENCE = "gtr_trending_presence"
GTR_TRAFFIC = "gtr_approx_traffic_min"
WIKI_VIEWS = "wiki_pageviews"
GDELT_ARTICLES = "gdelt_article_count"
TOPIC_SCOPE = "*"


class RulesVersionConflictError(RuntimeError):
    """La versión ya existe con otros parámetros: las versiones son inmutables."""


@dataclass
class MetricsReport:
    data_mode: DataMode
    as_of: date
    rules_version: str
    written: int = 0
    by_status: Counter[str] = field(default_factory=Counter)
    by_metric: Counter[str] = field(default_factory=Counter)
    skipped_observations: Counter[str] = field(default_factory=Counter)


@dataclass
class _Series:
    """Serie diaria de un sujeto (Wikimedia o GDELT)."""

    values: dict[date, float] = field(default_factory=dict)
    ids: list[int] = field(default_factory=list)
    country: str | None = None
    country_basis: CountryBasis = CountryBasis.NONE


@dataclass
class _Captures:
    """Capturas de Google Trends de un tema en un país."""

    present: set[datetime] = field(default_factory=set)
    traffic: list[tuple[datetime, float | None]] = field(default_factory=list)
    ids: list[int] = field(default_factory=list)


def params_sha256() -> str:
    return hashlib.sha256(json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


class MetricsService:
    def __init__(self, session: Session, *, clock: Clock = utc_now) -> None:
        self._session = session
        self._clock = clock

    def compute(
        self,
        *,
        data_mode: DataMode | str,
        as_of: date,
        topic_ids: Sequence[str] | None = None,
    ) -> MetricsReport:
        mode = require_data_mode(data_mode)
        if as_of >= self._clock().astimezone(UTC).date():
            raise ValueError("as_of debe ser un día cerrado (anterior a hoy en UTC)")
        self._ensure_rules_version()

        w = int(PARAMS["window_days"])
        current, previous, before = calc.windows(as_of, w, 3)
        range_start, range_end = _day_start(before.start), _day_start(as_of + timedelta(days=1))
        report = MetricsReport(data_mode=mode, as_of=as_of, rules_version=RULES_VERSION)

        gtr: dict[tuple[str, str], _Captures] = defaultdict(_Captures)
        wiki: dict[tuple[str, str], _Series] = defaultdict(_Series)
        news: dict[tuple[str, str], _Series] = defaultdict(_Series)

        for topic_id, obs in self._linked(mode, range_start, range_end, topic_ids):
            if obs.source is Source.GOOGLE_TRENDS_RSS and obs.country:
                group = gtr[(topic_id, obs.country)]
                group.ids.append(obs.id)
                if obs.metric_key == GTR_PRESENCE:
                    group.present.add(obs.observed_at)
                elif obs.metric_key == GTR_TRAFFIC:
                    group.traffic.append((obs.observed_at, obs.value))
            elif obs.source in (Source.WIKIMEDIA, Source.GDELT):
                expected = WIKI_VIEWS if obs.source is Source.WIKIMEDIA else GDELT_ARTICLES
                if obs.metric_key != expected or not _is_one_day(obs) or obs.value is None:
                    report.skipped_observations[f"{obs.source.value}:not_daily_or_no_value"] += 1
                    continue
                target = wiki if obs.source is Source.WIKIMEDIA else news
                series = target[(topic_id, obs.subject_ref)]
                series.values[obs.period_start.date()] = obs.value
                series.ids.append(obs.id)
                series.country, series.country_basis = obs.country, obs.country_basis
            else:
                report.skipped_observations[f"{obs.source.value}:unsupported"] += 1

        known = self._known_captures(mode, range_start, range_end)
        windows = {"current": current, "previous": previous, "before": before}
        for (topic_id, country), group in gtr.items():
            self._gtr_metrics(report, topic_id, country, group, known.get(country, []), windows)
        self._gtr_regional(report, gtr, known, windows)
        for (topic_id, subject), series in wiki.items():
            self._series_metrics(report, Source.WIKIMEDIA, "wiki", topic_id, subject, series, windows)
        for (topic_id, subject), series in news.items():
            self._series_metrics(report, Source.GDELT, "gdelt", topic_id, subject, series, windows)
        self._gdelt_regional(report, news, windows)
        self._session.flush()
        return report

    # --- lectura de datos ------------------------------------------------------------

    def _linked(self, mode, start, end, topic_ids):
        stmt = (
            select(TopicLink.topic_id, RawObservation)
            .join(
                RawObservation,
                and_(
                    RawObservation.id == TopicLink.observation_id,
                    RawObservation.data_mode == TopicLink.data_mode,
                ),
            )
            .where(
                TopicLink.data_mode == mode,
                TopicLink.status == LinkStatus.LINKED,
                TopicLink.superseded_at.is_(None),
                RawObservation.period_start >= start,
                RawObservation.period_start < end,
            )
            .order_by(RawObservation.id)
        )
        if topic_ids is not None:
            stmt = stmt.where(TopicLink.topic_id.in_(list(topic_ids)))
        return self._session.execute(stmt).all()

    def _known_captures(self, mode, start, end) -> dict[str, list[datetime]]:
        """Instantes de captura con al menos una tendencia guardada, por país (todas las tendencias)."""
        stmt = (
            select(RawObservation.country, RawObservation.observed_at)
            .where(
                RawObservation.data_mode == mode,
                RawObservation.source == Source.GOOGLE_TRENDS_RSS,
                RawObservation.metric_key == GTR_PRESENCE,
                RawObservation.period_start >= start,
                RawObservation.period_start < end,
                RawObservation.country.is_not(None),
            )
            .distinct()
        )
        known: dict[str, list[datetime]] = defaultdict(list)
        for country, observed_at in self._session.execute(stmt):
            known[country].append(observed_at)
        return known

    # --- cálculos por fuente ---------------------------------------------------------------

    def _gtr_metrics(self, report, topic_id, country, group, known, windows) -> None:
        cur, prev = windows["current"], windows["previous"]
        min_known = int(PARAMS["gtr_min_known_captures"])
        known_now = [c for c in known if cur.contains(c)]
        if known_now:
            present = calc.Result(
                value=float(len({c for c in group.present if cur.contains(c)})),
                details={"known": len(known_now)},
            )
        else:
            present = calc.insufficient("no_known_captures_in_window")
        results = {
            "gtr_presence_captures": present,
            "gtr_presence_share": calc.presence_share(group.present, known, cur, min_known=min_known),
            "gtr_presence_share_change": calc.presence_share_change(
                list(group.present), known, cur, prev, min_known=min_known
            ),
            "gtr_max_traffic_lower_bound": calc.max_lower_bound(group.traffic, cur),
        }
        for key, result in results.items():
            self._store(report, key, topic_id, Source.GOOGLE_TRENDS_RSS, country, result, group.ids, cur)

    def _gtr_regional(self, report, gtr, known, windows) -> None:
        cur = windows["current"]
        by_topic: dict[str, list[tuple[str, _Captures]]] = defaultdict(list)
        for (topic_id, country), group in gtr.items():
            by_topic[topic_id].append((country, group))
        for topic_id, groups in by_topic.items():
            observed = [c for c, _ in groups if any(cur.contains(k) for k in known.get(c, []))]
            if not observed:
                result = calc.insufficient("no_known_captures_in_window")
            else:
                present = sorted(c for c, g in groups if any(cur.contains(p) for p in g.present))
                result = calc.Result(
                    value=float(len(present)),
                    details={"countries": present, "countries_with_captures": sorted(observed)},
                )
            ids = [i for _, g in groups for i in g.ids]
            self._store(report, "gtr_interest_countries", topic_id, Source.GOOGLE_TRENDS_RSS, TOPIC_SCOPE, result, ids, cur)

    def _series_metrics(self, report, source, prefix, topic_id, subject, series, windows) -> None:
        cur, prev, before = windows["current"], windows["previous"], windows["before"]
        unit_name = "views" if prefix == "wiki" else "articles"
        min_base = float(PARAMS["wiki_min_base_views" if prefix == "wiki" else "gdelt_min_base_articles"])
        values = series.values
        results = {
            f"{prefix}_{unit_name}_total": calc.window_total(values, cur),
            f"{prefix}_{unit_name}_daily_mean": calc.daily_mean(values, cur),
            f"{prefix}_{unit_name}_abs_change": calc.abs_change(values, cur, prev),
            f"{prefix}_{unit_name}_growth": calc.growth(values, cur, prev, min_base=min_base),
            f"{prefix}_{unit_name}_acceleration": calc.acceleration(
                values, cur, prev, before, min_base=min_base
            ),
        }
        for key, result in results.items():
            self._store(report, key, topic_id, source, subject, result, series.ids, cur)

    def _gdelt_regional(self, report, news, windows) -> None:
        cur = windows["current"]
        by_topic: dict[str, list[_Series]] = defaultdict(list)
        for (topic_id, _subject), series in news.items():
            by_topic[topic_id].append(series)
        for topic_id, all_series in by_topic.items():
            filtered = [s for s in all_series if s.country_basis is CountryBasis.PUBLISHER_COUNTRY and s.country]
            in_window = [s for s in filtered if any(d in s.values for d in cur.days)]
            if not filtered:
                result = calc.insufficient("no_publisher_country_filter")
            elif not in_window:
                result = calc.insufficient("no_observations_in_window")
            else:
                with_coverage = sorted(
                    {s.country for s in in_window if sum(s.values.get(d, 0.0) for d in cur.days if d in s.values) > 0}
                )
                incomplete = sorted({s.country for s in in_window if any(d not in s.values for d in cur.days)})
                result = calc.Result(
                    value=float(len(with_coverage)),
                    details={"countries": with_coverage, "countries_with_missing_days": incomplete},
                )
            ids = [i for s in all_series for i in s.ids]
            self._store(report, "gdelt_publisher_countries", topic_id, Source.GDELT, TOPIC_SCOPE, result, ids, cur)

    # --- persistencia ------------------------------------------------------------------

    def _ensure_rules_version(self) -> None:
        sha = params_sha256()
        existing = self._session.get(RulesVersion, RULES_VERSION)
        if existing is None:
            self._session.add(
                RulesVersion(
                    version=RULES_VERSION, params=dict(PARAMS), params_sha256=sha, created_at=self._clock()
                )
            )
            self._session.flush()
        elif existing.params_sha256 != sha:
            raise RulesVersionConflictError(
                f"{RULES_VERSION} ya existe con otros parámetros; cree una versión nueva"
            )

    def _store(self, report, key, topic_id, source, scope, result: calc.Result, ids, window) -> None:
        definition = BY_KEY[key]
        assert definition.source is source
        limit = int(PARAMS["max_input_ids"])
        unique_ids = sorted(set(ids))
        values = {
            "data_mode": report.data_mode,
            "topic_id": topic_id,
            "source": source,
            "scope": scope[:500],
            "metric_key": key,
            "unit": definition.unit,
            "value": result.value,
            "status": MetricStatus.OK if result.ok else MetricStatus.INSUFFICIENT,
            "reason": None if result.ok else (result.reason or "")[:300],
            "window_days": len(window.days),
            "period_start": _day_start(window.start),
            "period_end": _day_start(window.end + timedelta(days=1)),
            "as_of": _day_start(report.as_of),
            "computed_at": self._clock(),
            "rules_version": RULES_VERSION,
            "source_validated": SOURCE_VALIDATED[source],
            "inputs": {
                "observation_ids": unique_ids[:limit],
                "observation_count": len(unique_ids),
                "truncated": len(unique_ids) > limit,
            },
            "details": result.details,
        }
        identity = [
            "data_mode", "topic_id", "source", "scope", "metric_key",
            "period_start", "period_end", "rules_version",
        ]
        stmt = sqlite_insert(MetricValue).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=identity,
            set_={k: stmt.excluded[k] for k in values if k not in identity},
        )
        self._session.execute(stmt)
        report.written += 1
        report.by_status[values["status"].value] += 1
        report.by_metric[key] += 1


def _is_one_day(obs: RawObservation) -> bool:
    return (
        obs.granularity is Granularity.DAY
        and obs.period_end is not None
        and obs.period_end - obs.period_start == timedelta(days=1)
        and obs.period_start.time() == time.min
    )
