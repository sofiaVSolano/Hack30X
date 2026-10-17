"""Servicio de métricas sobre SQLite temporal: persistencia, trazabilidad e idempotencia.

Las observaciones son sintéticas y se vinculan con el vinculador real de E7.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.detectar.metrics.definitions import DEFINITIONS, RULES_VERSION
from app.modules.detectar.metrics.service import (
    MetricsService,
    RulesVersionConflictError,
)
from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    CountryBasis,
    DataMode,
    Granularity,
    LanguageBasis,
    MetricStatus,
    MetricUnit,
    MetricValue,
    RawObservation,
    RulesVersion,
    Source,
    SourceRunStatus,
    SubjectType,
    TopicLink,
    Unit,
)
from app.modules.detectar.storage.repository import DetectarRepository, ObservationIn
from app.modules.detectar.storage.topics import TopicRepository, topic_id_for
from app.modules.detectar.topics.linker import TopicLinker, correct_link

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
CUR_START = AS_OF - timedelta(days=6)


def _day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _store(session: Session, source: Source, observations: list[ObservationIn], mode=DataMode.REAL) -> None:
    repo = DetectarRepository(session)
    run = repo.create_collection_run(
        data_mode=mode, trigger=CollectionTrigger.MANUAL, requested_sources=[source],
        requested_countries=[], created_at=NOW, status=CollectionStatus.RUNNING, started_at=NOW,
    )
    source_run = repo.add_source_run(
        collection_run_id=run.id, data_mode=mode, source=source, mode="on",
        status=SourceRunStatus.OK, started_at=NOW, finished_at=NOW,
    )
    dataset = "pruebas_metricas_v1" if mode is DataMode.SIMULATED else None
    repo.add_observations(source_run.id, observations, data_mode=mode, dataset_id=dataset)


def wiki_series(session, article: str, start: date, values: list[float | None], mode=DataMode.REAL) -> None:
    """None = día ausente (no se guarda observación)."""
    obs = [
        ObservationIn(
            source=Source.WIKIMEDIA, metric_key="wiki_pageviews", unit=Unit.VIEWS, value=v,
            observed_at=NOW, period_start=_day(start + timedelta(days=i)),
            period_end=_day(start + timedelta(days=i + 1)), granularity=Granularity.DAY,
            language="es", language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.WIKI_ARTICLE, subject_ref=f"es.wikipedia.org:{article}",
            raw_excerpt={"article": article},
        )
        for i, v in enumerate(values)
        if v is not None
    ]
    _store(session, Source.WIKIMEDIA, obs, mode)


def gdelt_series(session, term: str, start: date, values: list[float | None], country: str | None = None) -> None:
    query = f"{term} sourcelang:spanish" + (f" sourcecountry:{country.lower()}" if country else "")
    obs = [
        ObservationIn(
            source=Source.GDELT, metric_key="gdelt_article_count", unit=Unit.ARTICLES, value=v,
            observed_at=NOW, period_start=_day(start + timedelta(days=i)),
            period_end=_day(start + timedelta(days=i + 1)), granularity=Granularity.DAY,
            country=country, country_basis=CountryBasis.PUBLISHER_COUNTRY if country else CountryBasis.NONE,
            language="es", language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.NEWS_QUERY, subject_ref=query,
            raw_excerpt={"term": term, "query": query},
        )
        for i, v in enumerate(values)
        if v is not None
    ]
    _store(session, Source.GDELT, obs)


def gtr_capture(session, country: str, moment: datetime, titles: dict[str, str | None]) -> None:
    """Una captura del RSS: título -> tráfico ('200+', texto o None)."""
    obs: list[ObservationIn] = []
    for title, traffic in titles.items():
        common = {
            "source": Source.GOOGLE_TRENDS_RSS,
            "observed_at": moment,
            "period_start": moment,
            "granularity": Granularity.SNAPSHOT,
            "country": country,
            "country_basis": CountryBasis.REPORTED_BY_SOURCE,
            "subject_type": SubjectType.SEARCH_TERM,
            "subject_ref": title,
        }
        obs.append(ObservationIn(metric_key="gtr_trending_presence", unit=Unit.PRESENCE, value=1.0, **common))
        if traffic is not None:
            lower = float(traffic.rstrip("+").replace("K", "000")) if traffic.endswith("+") else None
            obs.append(ObservationIn(
                metric_key="gtr_approx_traffic_min", unit=Unit.SEARCHES_LOWER_BOUND,
                value=lower, value_text=traffic, **common,
            ))
    _store(session, Source.GOOGLE_TRENDS_RSS, obs)


def link_and_compute(session, mode=DataMode.REAL, **kwargs):
    TopicLinker(session, clock=lambda: NOW).process(data_mode=mode, limit=5000)
    report = MetricsService(session, clock=lambda: NOW).compute(data_mode=mode, as_of=AS_OF, **kwargs)
    session.flush()
    return report


def values(session, mode=DataMode.REAL, **filters) -> dict[tuple[str, str, str], MetricValue]:
    stmt = select(MetricValue).where(MetricValue.data_mode == mode)
    for key, value in filters.items():
        stmt = stmt.where(getattr(MetricValue, key) == value)
    return {(m.source.value, m.scope, m.metric_key): m for m in session.scalars(stmt)}


# --- Wikimedia ----------------------------------------------------------------------------


def test_wikimedia_metrics_with_three_complete_windows(session: Session) -> None:
    start = AS_OF - timedelta(days=20)
    wiki_series(session, "México", start, [10] * 7 + [20] * 7 + [30] * 7)

    link_and_compute(session)

    v = values(session, source=Source.WIKIMEDIA)
    scope = "es.wikipedia.org:México"
    assert v[("wikimedia", scope, "wiki_views_total")].value == 210.0
    assert v[("wikimedia", scope, "wiki_views_daily_mean")].value == 30.0
    assert v[("wikimedia", scope, "wiki_views_abs_change")].value == 70.0
    assert v[("wikimedia", scope, "wiki_views_growth")].value == pytest.approx(0.5)
    assert v[("wikimedia", scope, "wiki_views_acceleration")].value == pytest.approx(-0.5)
    growth = v[("wikimedia", scope, "wiki_views_growth")]
    assert growth.unit is MetricUnit.GROWTH_RATE
    assert growth.status is MetricStatus.OK and growth.reason is None
    assert (growth.period_start, growth.period_end) == (_day(CUR_START), _day(AS_OF + timedelta(days=1)))
    assert growth.window_days == 7
    assert growth.rules_version == RULES_VERSION
    assert growth.source_validated is True
    assert growth.inputs["observation_count"] == 21
    assert growth.topic_id == topic_id_for(DataMode.REAL, "mexico")


def test_missing_day_makes_window_metrics_insufficient(session: Session) -> None:
    start = AS_OF - timedelta(days=13)
    wiki_series(session, "Tema", start, [100] * 7 + [100, 100, None, 100, 100, 100, 100])

    link_and_compute(session)

    v = values(session)
    total = v[("wikimedia", "es.wikipedia.org:Tema", "wiki_views_total")]
    assert (total.status, total.value, total.reason) == (MetricStatus.INSUFFICIENT, None, "missing_days:1")
    assert total.details["missing"] == [(CUR_START + timedelta(days=2)).isoformat()]


def test_small_base_does_not_produce_a_growth_rate(session: Session) -> None:
    start = AS_OF - timedelta(days=13)
    wiki_series(session, "Pequeño", start, [1] * 7 + [50] * 7)

    link_and_compute(session)

    v = values(session)
    scope = "es.wikipedia.org:Pequeño"
    assert v[("wikimedia", scope, "wiki_views_growth")].reason == "base_below_minimum:70"
    assert v[("wikimedia", scope, "wiki_views_abs_change")].value == 343.0  # sí se informa


def test_wikimedia_metrics_never_get_a_country(session: Session) -> None:
    wiki_series(session, "México", AS_OF - timedelta(days=6), [10] * 7)

    link_and_compute(session)

    keys = {k for (_, _, k) in values(session, source=Source.WIKIMEDIA)}
    assert not any("countr" in k for k in keys)


# --- GDELT --------------------------------------------------------------------------------


def test_gdelt_metrics_are_marked_as_unvalidated_source(session: Session) -> None:
    gdelt_series(session, "huracan", AS_OF - timedelta(days=13), [1] * 7 + [3] * 7)

    link_and_compute(session)

    v = values(session, source=Source.GDELT)
    scope = "huracan sourcelang:spanish"
    growth = v[("gdelt", scope, "gdelt_articles_growth")]
    assert growth.value == pytest.approx(2.0)  # (21 - 7) / 7
    assert growth.source_validated is False
    assert v[("gdelt", scope, "gdelt_articles_total")].unit is MetricUnit.ARTICLES


def test_gdelt_publisher_countries_only_with_country_filter(session: Session) -> None:
    gdelt_series(session, "huracan", AS_OF - timedelta(days=6), [2] * 7, country="MX")
    gdelt_series(session, "huracan", AS_OF - timedelta(days=6), [0] * 7, country="CO")
    gdelt_series(session, "sismo", AS_OF - timedelta(days=6), [5] * 7)  # sin filtro de país

    link_and_compute(session)

    by_topic = {
        m.topic_id: m
        for m in session.scalars(
            select(MetricValue).where(MetricValue.metric_key == "gdelt_publisher_countries")
        )
    }
    hur = by_topic[topic_id_for(DataMode.REAL, "huracan")]
    sismo = by_topic[topic_id_for(DataMode.REAL, "sismo")]
    assert (hur.status, hur.value, hur.details["countries"]) == (MetricStatus.OK, 1.0, ["MX"])  # CO: 0
    assert hur.unit is MetricUnit.COUNTRIES and hur.scope == "*"
    assert (sismo.status, sismo.reason) == (MetricStatus.INSUFFICIENT, "no_publisher_country_filter")


# --- Google Trends -------------------------------------------------------------------------


def test_gtr_presence_share_and_traffic(session: Session) -> None:
    for i in range(4):
        titles = {"Otro tema": None} | ({"Copa América": "200+" if i else "Muchas"} if i % 2 == 0 else {})
        gtr_capture(session, "MX", _day(CUR_START + timedelta(days=i)) + timedelta(hours=3), titles)

    link_and_compute(session)

    v = values(session, source=Source.GOOGLE_TRENDS_RSS, topic_id=topic_id_for(DataMode.REAL, "copa america"))
    assert v[("google_trends_rss", "MX", "gtr_presence_captures")].value == 2.0
    share = v[("google_trends_rss", "MX", "gtr_presence_share")]
    assert share.value == pytest.approx(0.5) and share.unit is MetricUnit.RATIO
    traffic = v[("google_trends_rss", "MX", "gtr_max_traffic_lower_bound")]
    assert (traffic.value, traffic.unit) == (200.0, MetricUnit.SEARCHES_LOWER_BOUND)
    assert v[("google_trends_rss", "MX", "gtr_presence_share_change")].reason.startswith(
        "previous_known_captures_below_minimum"
    )
    countries = v[("google_trends_rss", "*", "gtr_interest_countries")]
    assert (countries.value, countries.details["countries"]) == (1.0, ["MX"])


def test_single_capture_does_not_produce_share_or_change(session: Session) -> None:
    gtr_capture(session, "MX", _day(AS_OF) + timedelta(hours=1), {"Tema único": "100+"})

    link_and_compute(session)

    v = values(session, source=Source.GOOGLE_TRENDS_RSS)
    assert v[("google_trends_rss", "MX", "gtr_presence_captures")].value == 1.0
    assert v[("google_trends_rss", "MX", "gtr_presence_share")].reason == "known_captures_below_minimum:3"
    assert v[("google_trends_rss", "MX", "gtr_presence_share_change")].status is MetricStatus.INSUFFICIENT


# --- Separación de fuentes y unidades ------------------------------------------------------


def test_same_topic_keeps_sources_and_units_separate(session: Session) -> None:
    wiki_series(session, "Huracán", AS_OF - timedelta(days=6), [100] * 7)
    gdelt_series(session, "huracan", AS_OF - timedelta(days=6), [4] * 7)

    link_and_compute(session)

    rows = list(session.scalars(select(MetricValue).where(MetricValue.topic_id == topic_id_for(DataMode.REAL, "huracan"))))
    assert {r.source for r in rows} == {Source.WIKIMEDIA, Source.GDELT}
    for row in rows:
        definition = next(d for d in DEFINITIONS if d.key == row.metric_key)
        assert definition.source is row.source and definition.unit is row.unit
    assert not any(r.metric_key.startswith(("score", "combined")) for r in rows)


# --- Idempotencia, versión y trazabilidad -----------------------------------------------------


def test_recalculation_is_idempotent(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=13), [100] * 14)
    link_and_compute(session)
    first = session.scalar(select(func.count()).select_from(MetricValue))

    MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=AS_OF)
    session.flush()

    assert session.scalar(select(func.count()).select_from(MetricValue)) == first
    assert session.scalar(select(func.count()).select_from(RulesVersion)) == 1


def test_rules_version_is_immutable(session: Session) -> None:
    session.add(RulesVersion(version=RULES_VERSION, params={"window_days": 30}, params_sha256="x" * 64, created_at=NOW))
    session.flush()

    with pytest.raises(RulesVersionConflictError):
        MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=AS_OF)


def test_only_current_linked_observations_are_used(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=6), [100] * 7)
    TopicLinker(session, clock=lambda: NOW).process(data_mode="real")
    link_id = TopicRepository(session).list_links(data_mode="real", limit=1)[0].id
    correct_link(session, link_id, data_mode="real", action="reject", actor="ana", reason="no es", now=NOW)

    MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=AS_OF)
    session.flush()

    total = values(session)[("wikimedia", "es.wikipedia.org:Tema", "wiki_views_total")]
    assert (total.reason, total.inputs["observation_count"]) == ("missing_days:1", 6)


def test_computation_does_not_modify_observations_or_links(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=13), [100] * 14)
    TopicLinker(session, clock=lambda: NOW).process(data_mode="real")
    snapshot = lambda: (
        session.execute(text("SELECT id, value, subject_ref FROM raw_observations ORDER BY id")).all(),
        session.execute(text("SELECT id, topic_id, status, superseded_at FROM topic_links ORDER BY id")).all(),
    )
    before = snapshot()

    MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=AS_OF)
    session.flush()

    assert snapshot() == before


def test_reference_date_must_be_closed(session: Session) -> None:
    with pytest.raises(ValueError):
        MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=NOW.date())


# --- Aislamiento real / simulado -------------------------------------------------------------


def test_real_and_simulated_metrics_are_isolated(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=6), [100] * 7, mode=DataMode.REAL)
    wiki_series(session, "Tema", AS_OF - timedelta(days=6), [5] * 7, mode=DataMode.SIMULATED)

    link_and_compute(session, DataMode.REAL)

    assert values(session, DataMode.SIMULATED) == {}
    real_total = values(session)[("wikimedia", "es.wikipedia.org:Tema", "wiki_views_total")]
    assert real_total.value == 700.0

    link_and_compute(session, DataMode.SIMULATED)
    sim_total = values(session, DataMode.SIMULATED)[("wikimedia", "es.wikipedia.org:Tema", "wiki_views_total")]
    assert sim_total.value == 35.0
    assert sim_total.topic_id != real_total.topic_id


@pytest.mark.parametrize("bad", [None, "", "todos"])
def test_invalid_mode_is_rejected(session: Session, bad) -> None:
    from app.modules.detectar.storage.repository import InvalidDataModeError

    with pytest.raises(InvalidDataModeError):
        MetricsService(session, clock=lambda: NOW).compute(data_mode=bad, as_of=AS_OF)


# --- Restricciones en SQLite ---------------------------------------------------------------


def _insert(session, **overrides) -> None:
    session.execute(text("INSERT OR IGNORE INTO rules_versions VALUES ('vtest', '{}', :s, '2026-10-17 00:00:00')"), {"s": "0" * 64})
    tema = TopicRepository(session).create_topic("Tema", data_mode="real", created_by="x", now=NOW)[0]
    row = {
        "data_mode": "real", "topic_id": tema.id, "source": "wikimedia", "scope": "s",
        "metric_key": "wiki_views_total", "unit": "views", "value": 1.0, "status": "ok",
        "reason": None, "window_days": 7, "period_start": "2026-10-09 00:00:00",
        "period_end": "2026-10-16 00:00:00", "as_of": "2026-10-15 00:00:00",
        "computed_at": "2026-10-17 00:00:00", "rules_version": "vtest",
        "source_validated": 1, "inputs": "{}", "details": "{}",
    } | overrides
    cols = ", ".join(row)
    session.execute(text(f"INSERT INTO metric_values ({cols}) VALUES ({', '.join(':' + c for c in row)})"), row)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "ok", "value": None},
        {"status": "insufficient", "value": 1.0, "reason": "x"},
        {"status": "insufficient", "value": None, "reason": None},
        {"value": float("inf")},
        {"unit": "points"},
        {"period_end": "2026-10-09 00:00:00"},
        {"data_mode": "simulated"},  # el tema es real: la clave foránea compuesta lo impide
    ],
)
def test_database_rejects_inconsistent_metric_rows(session: Session, overrides) -> None:
    with pytest.raises(IntegrityError):
        _insert(session, **overrides)


def test_original_records_are_not_counted_twice(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=6), [100] * 7)

    link_and_compute(session)

    assert session.scalar(select(func.count()).select_from(RawObservation)) == 7
    assert session.scalar(select(func.count()).select_from(TopicLink)) == 7
