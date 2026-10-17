"""Observaciones sintéticas de las tres fuentes, guardadas en una SQLite temporal.

Reproducen la forma en que cada conector guarda sus datos (E4 a E6); los valores son
inventados y solo existen en la base de la prueba.
"""

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    CountryBasis,
    DataMode,
    Granularity,
    LanguageBasis,
    RawObservation,
    Source,
    SourceRunStatus,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import DetectarRepository, ObservationIn

T0 = datetime(2026, 10, 10, tzinfo=UTC)
_days = count()


def _run(repo: DetectarRepository, source: Source, mode: DataMode) -> str:
    started = T0
    run = repo.create_collection_run(
        data_mode=mode,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[source],
        requested_countries=[],
        created_at=started,
        status=CollectionStatus.RUNNING,
        started_at=started,
    )
    return repo.add_source_run(
        collection_run_id=run.id,
        data_mode=mode,
        source=source,
        mode="on",
        status=SourceRunStatus.OK,
        started_at=started,
        finished_at=started,
    ).id


def _store(session: Session, mode: DataMode, observation: ObservationIn) -> RawObservation:
    repo = DetectarRepository(session)
    run_id = _run(repo, observation.source, mode)
    dataset = "pruebas_temas_v1" if mode is DataMode.SIMULATED else None
    repo.add_observations(run_id, [observation], data_mode=mode, dataset_id=dataset)
    rows = repo.list_observations(
        data_mode=mode, source=observation.source, subject_ref=observation.subject_ref, limit=10_000
    )
    return rows[-1]


def _day() -> datetime:
    return T0 + timedelta(days=next(_days))


def trends(session: Session, title: str, *, mode: DataMode = DataMode.REAL, country: str = "MX") -> RawObservation:
    captured = _day()
    return _store(
        session,
        mode,
        ObservationIn(
            source=Source.GOOGLE_TRENDS_RSS,
            metric_key="gtr_trending_presence",
            unit=Unit.PRESENCE,
            value=1.0,
            observed_at=captured,
            period_start=captured,
            granularity=Granularity.SNAPSHOT,
            country=country,
            country_basis=CountryBasis.REPORTED_BY_SOURCE,
            subject_type=SubjectType.SEARCH_TERM,
            subject_ref=title,
            raw_excerpt={"approx_traffic": "200+"},
        ),
    )


def wiki(session: Session, article: str, *, mode: DataMode = DataMode.REAL, views: int = 100) -> RawObservation:
    day = _day()
    return _store(
        session,
        mode,
        ObservationIn(
            source=Source.WIKIMEDIA,
            metric_key="wiki_pageviews",
            unit=Unit.VIEWS,
            value=float(views),
            observed_at=day + timedelta(days=2),
            period_start=day,
            period_end=day + timedelta(days=1),
            granularity=Granularity.DAY,
            language="es",
            language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.WIKI_ARTICLE,
            subject_ref=f"es.wikipedia.org:{article}",
            raw_excerpt={"project": "es.wikipedia.org", "article": article, "views": views},
        ),
    )


def gdelt(
    session: Session,
    term: str | None,
    *,
    mode: DataMode = DataMode.REAL,
    query: str | None = None,
    excerpt: dict[str, Any] | None = None,
) -> RawObservation:
    day = _day()
    query = query or (f'"{term}" sourcelang:spanish' if term else "consulta sin termino")
    return _store(
        session,
        mode,
        ObservationIn(
            source=Source.GDELT,
            metric_key="gdelt_article_count",
            unit=Unit.ARTICLES,
            value=7.0,
            observed_at=day + timedelta(days=1),
            period_start=day,
            period_end=day + timedelta(days=1),
            granularity=Granularity.DAY,
            language="es",
            language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.NEWS_QUERY,
            subject_ref=query,
            raw_excerpt=excerpt if excerpt is not None else {"term": term, "query": query},
        ),
    )
