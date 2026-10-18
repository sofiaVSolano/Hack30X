"""Datos de prueba que pasan por el flujo REAL de DETECTAR.

Se guardan observaciones sintéticas con el repositorio de DETECTAR y se ejecutan su
normalización (E7), sus métricas (E8) y su clasificación (E9). Así CREAR se prueba contra lo
que DETECTAR realmente persiste, no contra una imitación de su esquema.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.stages.service import ClassificationService
from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    CountryBasis,
    DataMode,
    Granularity,
    LanguageBasis,
    Source,
    SourceRunStatus,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import DetectarRepository, ObservationIn
from app.modules.detectar.storage.topics import topic_id_for
from app.modules.detectar.topics.linker import TopicLinker

AS_OF = date(2026, 10, 15)
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
START = AS_OF - timedelta(days=20)  # tres ventanas completas de 7 días


def _day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _store(session: Session, source: Source, observations: list[ObservationIn], mode: DataMode) -> None:
    repo = DetectarRepository(session)
    run = repo.create_collection_run(
        data_mode=mode, trigger=CollectionTrigger.MANUAL, requested_sources=[source],
        requested_countries=[], created_at=NOW, status=CollectionStatus.RUNNING, started_at=NOW,
    )
    source_run = repo.add_source_run(
        collection_run_id=run.id, data_mode=mode, source=source, mode="on",
        status=SourceRunStatus.OK, started_at=NOW, finished_at=NOW,
    )
    dataset = "pruebas_crear_v1" if mode is DataMode.SIMULATED else None
    repo.add_observations(source_run.id, observations, data_mode=mode, dataset_id=dataset)


def wiki(
    session: Session,
    project: str,
    article: str,
    weekly: list[float],
    *,
    mode: DataMode = DataMode.REAL,
    start: date = START,
) -> None:
    """Visitas diarias constantes por semana: ``weekly`` = media diaria de cada semana."""
    language = project.split(".")[0]
    values = [v for v in weekly for _ in range(7)]
    observations = [
        ObservationIn(
            source=Source.WIKIMEDIA, metric_key="wiki_pageviews", unit=Unit.VIEWS, value=value,
            observed_at=NOW, period_start=_day(start + timedelta(days=i)),
            period_end=_day(start + timedelta(days=i + 1)), granularity=Granularity.DAY,
            language=language, language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.WIKI_ARTICLE, subject_ref=f"{project}:{article}",
            raw_excerpt={"article": article},
        )
        for i, value in enumerate(values)
    ]
    _store(session, Source.WIKIMEDIA, observations, mode)


def gdelt(session: Session, term: str, language: str, weekly: list[float], *, mode: DataMode = DataMode.REAL) -> None:
    query = f"{term} sourcelang:{language}"
    values = [v for v in weekly for _ in range(7)]
    observations = [
        ObservationIn(
            source=Source.GDELT, metric_key="gdelt_article_count", unit=Unit.ARTICLES, value=value,
            observed_at=NOW, period_start=_day(START + timedelta(days=i)),
            period_end=_day(START + timedelta(days=i + 1)), granularity=Granularity.DAY,
            country=None, country_basis=CountryBasis.NONE,
            language={"spanish": "es", "english": "en"}[language], language_basis=LanguageBasis.QUERY_FILTER,
            subject_type=SubjectType.NEWS_QUERY, subject_ref=query, raw_excerpt={"term": term, "query": query},
        )
        for i, value in enumerate(values)
    ]
    _store(session, Source.GDELT, observations, mode)


def trends(session: Session, country: str, days: dict[date, list[str]], *, mode: DataMode = DataMode.REAL) -> None:
    """Una captura del RSS por día, a las 12:00 UTC, con los títulos indicados."""
    observations = [
        ObservationIn(
            source=Source.GOOGLE_TRENDS_RSS, metric_key="gtr_trending_presence", unit=Unit.PRESENCE,
            value=1.0, observed_at=_day(day) + timedelta(hours=12), period_start=_day(day) + timedelta(hours=12),
            granularity=Granularity.SNAPSHOT, country=country, country_basis=CountryBasis.REPORTED_BY_SOURCE,
            subject_type=SubjectType.SEARCH_TERM, subject_ref=title,
        )
        for day, titles in days.items()
        for title in titles
    ]
    _store(session, Source.GOOGLE_TRENDS_RSS, observations, mode)


def last_days(count: int, as_of: date = AS_OF) -> list[date]:
    return [as_of - timedelta(days=i) for i in range(count)]


def run_detectar(sessions: sessionmaker[Session], *, mode: DataMode = DataMode.REAL, as_of: date = AS_OF) -> None:
    """Normalización, métricas y clasificación de DETECTAR, cada paso en su transacción."""
    with sessions() as session, session.begin():
        TopicLinker(session, clock=lambda: NOW).process(data_mode=mode, limit=5000)
    with sessions() as session, session.begin():
        MetricsService(session, clock=lambda: NOW).compute(data_mode=mode, as_of=as_of)
    with sessions() as session, session.begin():
        ClassificationService(session, clock=lambda: NOW).classify(data_mode=mode, as_of=as_of)


def topic_id(name: str, mode: DataMode = DataMode.REAL) -> str:
    return topic_id_for(mode, name.casefold())


def seed_gaps(sessions: sessionmaker[Session], *, mode: DataMode = DataMode.REAL) -> None:
    """Un escenario por veredicto (ver test_gaps_service.py)."""
    with sessions() as session, session.begin():
        # Brecha confirmada: 25× más visitas en inglés y tendencia solo en EE. UU.
        wiki(session, "en.wikipedia.org", "Brecha", [1000, 1000, 1000], mode=mode)
        wiki(session, "es.wikipedia.org", "Brecha", [40, 40, 40], mode=mode)
        # Por confirmar: solo se midió el artículo en inglés.
        wiki(session, "en.wikipedia.org", "Solo ingles", [500, 600, 900], mode=mode)
        # Señales mixtas: Wikipedia favorece al inglés; Google Trends, a México.
        wiki(session, "en.wikipedia.org", "Mixta", [500, 500, 500], mode=mode)
        wiki(session, "es.wikipedia.org", "Mixta", [100, 100, 100], mode=mode)
        # Sin brecha: atención parecida en ambos idiomas.
        wiki(session, "en.wikipedia.org", "Pareja", [200, 200, 200], mode=mode)
        wiki(session, "es.wikipedia.org", "Pareja", [180, 180, 180], mode=mode)
        # Datos insuficientes: solo español.
        wiki(session, "es.wikipedia.org", "Solo espanol", [300, 300, 300], mode=mode)
        # Una captura diaria en cada país: 7 capturas conocidas, así la ausencia es medida.
        recent = last_days(7)
        trends(session, "US", {d: ["Brecha"] for d in recent}, mode=mode)
        trends(session, "MX", {d: ["Mixta"] for d in recent}, mode=mode)
    run_detectar(sessions, mode=mode)
