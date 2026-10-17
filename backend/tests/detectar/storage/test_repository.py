import inspect as pyinspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.detectar.storage.db import create_session_factory
from app.modules.detectar.storage.models import (
    CollectionStatus,
    CollectionTrigger,
    CountryBasis,
    DataMode,
    Source,
    SourceRun,
    SourceRunStatus,
)
from app.modules.detectar.storage.repository import (
    DetectarRepository,
    InvalidDataModeError,
)

from .factories import T0, T1, TEST_DATASET_ID, make_observation

MakeSourceRun = Callable[..., SourceRun]


# --- 2. Recolecciones y ejecuciones por fuente --------------------------------


def test_collection_run_and_source_runs_round_trip(engine: Engine) -> None:
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        repo = DetectarRepository(session)
        run = repo.create_collection_run(
            data_mode=DataMode.REAL,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[Source.GOOGLE_TRENDS_RSS, Source.WIKIMEDIA],
            requested_countries=["MX", "CO"],
            created_at=T1,
        )
        repo.add_source_run(
            collection_run_id=run.id,
            data_mode=DataMode.REAL,
            source=Source.WIKIMEDIA,
            mode="on",
            status=SourceRunStatus.OK,
            started_at=T1,
            finished_at=T1 + timedelta(seconds=4),
            http_calls=3,
            items=12,
        )
        repo.add_source_run(
            collection_run_id=run.id,
            data_mode=DataMode.REAL,
            source=Source.GOOGLE_TRENDS_RSS,
            mode="on",
            status=SourceRunStatus.FAILED,
            started_at=T1,
            error_code="upstream_timeout",
            error_detail="x" * 900,
        )
        run_id = run.id

    with factory() as session:
        repo = DetectarRepository(session)
        stored = repo.get_collection_run(run_id, data_mode=DataMode.REAL)
        assert stored is not None
        assert stored.id.startswith("run_") and len(stored.id) == 36
        assert stored.status is CollectionStatus.QUEUED
        assert stored.requested_sources == ["google_trends_rss", "wikimedia"]
        assert stored.requested_countries == ["MX", "CO"]
        assert stored.created_at == T1
        assert stored.created_at.tzinfo is not None

        source_runs = repo.list_source_runs(run_id, data_mode=DataMode.REAL)
        assert [sr.source for sr in source_runs] == [Source.GOOGLE_TRENDS_RSS, Source.WIKIMEDIA]
        failed, ok = source_runs
        assert failed.status is SourceRunStatus.FAILED
        assert failed.error_code == "upstream_timeout"
        assert len(failed.error_detail or "") == 500
        assert ok.items == 12 and ok.http_calls == 3
        assert ok.finished_at == T1 + timedelta(seconds=4)
        assert [sr.id for sr in stored.source_runs] == [sr.id for sr in source_runs]


def test_datetimes_are_stored_and_returned_in_utc(repo: DetectarRepository) -> None:
    bogota = timezone(timedelta(hours=-5))
    run = repo.create_collection_run(
        data_mode=DataMode.REAL,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[],
        requested_countries=[],
        created_at=datetime(2026, 10, 16, 17, 0, tzinfo=bogota),
    )
    repo._session.expire_all()

    stored = repo.get_collection_run(run.id, data_mode=DataMode.REAL)
    assert stored is not None
    assert stored.created_at == datetime(2026, 10, 16, 22, 0, tzinfo=UTC)
    assert stored.created_at.utcoffset() == timedelta(0)


def test_naive_datetimes_are_rejected(repo: DetectarRepository) -> None:
    with pytest.raises(Exception, match="zona horaria"):
        repo.create_collection_run(
            data_mode=DataMode.REAL,
            trigger=CollectionTrigger.MANUAL,
            requested_sources=[],
            requested_countries=[],
            created_at=datetime(2026, 10, 16, 22, 0),
        )


def test_source_run_requires_collection_with_same_mode(repo: DetectarRepository) -> None:
    run = repo.create_collection_run(
        data_mode=DataMode.REAL,
        trigger=CollectionTrigger.MANUAL,
        requested_sources=[],
        requested_countries=[],
        created_at=T1,
    )

    with pytest.raises(LookupError):
        repo.add_source_run(
            collection_run_id=run.id,
            data_mode=DataMode.SIMULATED,
            source=Source.GDELT,
            mode="on",
            status=SourceRunStatus.OK,
        )


# --- 3. Aislamiento real / simulado ------------------------------------------


@pytest.fixture
def mixed_observations(repo: DetectarRepository, make_source_run: MakeSourceRun) -> None:
    real_run = make_source_run(DataMode.REAL)
    simulated_run = make_source_run(DataMode.SIMULATED)
    repo.add_observations(
        real_run.id,
        [make_observation(subject_ref="es:Tema_real", value=10.0)],
        data_mode=DataMode.REAL,
    )
    repo.add_observations(
        simulated_run.id,
        [make_observation(subject_ref="es:Tema_simulado", value=99.0)],
        data_mode=DataMode.SIMULATED,
        dataset_id=TEST_DATASET_ID,
    )


@pytest.mark.usefixtures("mixed_observations")
def test_real_query_never_returns_simulated(repo: DetectarRepository) -> None:
    rows = repo.list_observations(data_mode=DataMode.REAL)

    assert [row.subject_ref for row in rows] == ["es:Tema_real"]
    assert all(row.data_mode is DataMode.REAL and row.dataset_id is None for row in rows)
    assert repo.list_observations(data_mode="real", subject_ref="es:Tema_simulado") == []


@pytest.mark.usefixtures("mixed_observations")
def test_simulated_query_never_returns_real(repo: DetectarRepository) -> None:
    rows = repo.list_observations(data_mode=DataMode.SIMULATED)

    assert [row.subject_ref for row in rows] == ["es:Tema_simulado"]
    assert all(row.data_mode is DataMode.SIMULATED for row in rows)
    assert rows[0].dataset_id == TEST_DATASET_ID
    assert repo.list_observations(data_mode="simulated", subject_ref="es:Tema_real") == []


@pytest.mark.usefixtures("mixed_observations")
def test_collection_queries_are_isolated_by_mode(repo: DetectarRepository) -> None:
    real_runs = repo.list_collection_runs(data_mode=DataMode.REAL)
    simulated_runs = repo.list_collection_runs(data_mode=DataMode.SIMULATED)

    assert len(real_runs) == 1 and len(simulated_runs) == 1
    assert repo.get_collection_run(real_runs[0].id, data_mode=DataMode.SIMULATED) is None
    assert repo.list_source_runs(real_runs[0].id, data_mode=DataMode.SIMULATED) == []


def test_observation_cannot_be_written_to_run_of_other_mode(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    real_run = make_source_run(DataMode.REAL)

    with pytest.raises(LookupError):
        repo.add_observations(
            real_run.id,
            [make_observation()],
            data_mode=DataMode.SIMULATED,
            dataset_id=TEST_DATASET_ID,
        )


def test_simulated_requires_dataset_id_and_real_forbids_it(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    real_run = make_source_run(DataMode.REAL)
    simulated_run = make_source_run(DataMode.SIMULATED)

    with pytest.raises(ValueError, match="dataset_id"):
        repo.add_observations(simulated_run.id, [make_observation()], data_mode=DataMode.SIMULATED)
    with pytest.raises(ValueError, match="dataset_id"):
        repo.add_observations(
            real_run.id, [make_observation()], data_mode=DataMode.REAL, dataset_id="demo"
        )


# --- 4. Modos inválidos y consultas sin data_mode -----------------------------


@pytest.mark.parametrize("bad_mode", [None, "", "REAL", "mixed", "all", 1])
def test_invalid_data_mode_is_rejected(repo: DetectarRepository, bad_mode: object) -> None:
    with pytest.raises(InvalidDataModeError):
        repo.list_observations(data_mode=bad_mode)  # type: ignore[arg-type]
    with pytest.raises(InvalidDataModeError):
        repo.list_collection_runs(data_mode=bad_mode)  # type: ignore[arg-type]


def test_queries_without_data_mode_fail(repo: DetectarRepository) -> None:
    with pytest.raises(TypeError):
        repo.list_observations()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        repo.list_collection_runs()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        repo.get_collection_run("run_x")  # type: ignore[call-arg]


def test_every_public_repository_method_requires_data_mode() -> None:
    methods = {
        name: member
        for name, member in pyinspect.getmembers(DetectarRepository, pyinspect.isfunction)
        if not name.startswith("_")
    }
    assert methods, "El repositorio debe exponer métodos públicos"
    for name, method in methods.items():
        parameter = pyinspect.signature(method).parameters.get("data_mode")
        assert parameter is not None, f"{name} no recibe data_mode"
        assert parameter.kind is pyinspect.Parameter.KEYWORD_ONLY, f"{name}: data_mode no es keyword-only"
        assert parameter.default is pyinspect.Parameter.empty, f"{name}: data_mode tiene valor por defecto"


def test_database_rejects_invalid_mode_written_directly(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO collection_runs (id, data_mode, trigger, status, requested_sources, "
                "requested_countries, created_at) VALUES ('run_directo', 'mixed', 'manual', "
                "'queued', '[]', '[]', '2026-10-16 00:00:00')"
            )
        )


# --- 5. Idempotencia ----------------------------------------------------------


def test_repeated_insert_is_ignored(repo: DetectarRepository, make_source_run: MakeSourceRun) -> None:
    source_run = make_source_run(DataMode.REAL)
    observation = make_observation(country="MX", country_basis=CountryBasis.REPORTED_BY_SOURCE)

    first = repo.add_observations(source_run.id, [observation], data_mode=DataMode.REAL)
    second = repo.add_observations(source_run.id, [observation, observation], data_mode=DataMode.REAL)

    assert (first.inserted, first.ignored) == (1, 0)
    assert (second.inserted, second.ignored) == (0, 2)
    assert len(repo.list_observations(data_mode=DataMode.REAL)) == 1


def test_same_observation_in_other_mode_is_not_a_duplicate(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    real_run = make_source_run(DataMode.REAL)
    simulated_run = make_source_run(DataMode.SIMULATED)
    observation = make_observation()

    repo.add_observations(real_run.id, [observation], data_mode=DataMode.REAL)
    result = repo.add_observations(
        simulated_run.id, [observation], data_mode=DataMode.SIMULATED, dataset_id=TEST_DATASET_ID
    )

    assert result.inserted == 1


def test_different_periods_are_distinct_observations(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL)
    result = repo.add_observations(
        source_run.id,
        [
            make_observation(period_start=T0, period_end=T1),
            make_observation(period_start=T1, period_end=T1 + timedelta(days=1)),
        ],
        data_mode=DataMode.REAL,
    )

    assert result.inserted == 2


# --- 6. Integridad referencial -----------------------------------------------


def test_source_run_with_missing_collection_is_rejected_by_database(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO source_runs (id, collection_run_id, data_mode, source, mode, status, "
                "http_calls, items, estimated_cost_usd) VALUES ('srn_x', 'run_inexistente', 'real', "
                "'gdelt', 'on', 'ok', 0, 0, 0)"
            )
        )


def test_database_rejects_mode_mismatch_between_tables(
    session: Session, make_source_run: MakeSourceRun
) -> None:
    real_run = make_source_run(DataMode.REAL)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO raw_observations (source_run_id, data_mode, source, metric_key, unit, "
                "value, observed_at, period_start, granularity, country_basis, language_basis, "
                "subject_type, subject_ref, dataset_id) VALUES (:run_id, 'simulated', 'wikimedia', "
                "'wiki_pageviews', 'views', 1, '2026-10-16 00:00:00', '2026-10-15 00:00:00', 'day', "
                "'none', 'none', 'wiki_article', 'es:X', 'demo')"
            ),
            {"run_id": real_run.id},
        )


def test_collection_with_source_runs_cannot_be_deleted(
    session: Session, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL)

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM collection_runs WHERE id = :id"), {"id": source_run.collection_run_id}
        )


def test_observation_for_unknown_source_run_is_rejected(repo: DetectarRepository) -> None:
    with pytest.raises(LookupError):
        repo.add_observations("srn_inexistente", [make_observation()], data_mode=DataMode.REAL)


# --- 7. País NULL -------------------------------------------------------------


def test_null_country_does_not_allow_duplicates(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL)
    observation = make_observation()  # sin país: Wikipedia en español no identifica país
    assert observation.country is None

    first = repo.add_observations(source_run.id, [observation], data_mode=DataMode.REAL)
    second = repo.add_observations(source_run.id, [observation], data_mode=DataMode.REAL)

    assert first.inserted == 1
    assert (second.inserted, second.ignored) == (0, 1)


def test_null_and_explicit_country_are_different_observations(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL)
    result = repo.add_observations(
        source_run.id,
        [
            make_observation(),
            make_observation(country="MX", country_basis=CountryBasis.REPORTED_BY_SOURCE),
        ],
        data_mode=DataMode.REAL,
    )

    assert result.inserted == 2


def test_country_filter_distinguishes_null_from_any(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL)
    repo.add_observations(
        source_run.id,
        [
            make_observation(subject_ref="es:Sin_pais"),
            make_observation(
                subject_ref="es:Con_pais", country="CO", country_basis=CountryBasis.REPORTED_BY_SOURCE
            ),
        ],
        data_mode=DataMode.REAL,
    )

    assert {r.subject_ref for r in repo.list_observations(data_mode=DataMode.REAL)} == {
        "es:Sin_pais",
        "es:Con_pais",
    }
    assert [r.subject_ref for r in repo.list_observations(data_mode=DataMode.REAL, country=None)] == [
        "es:Sin_pais"
    ]
    assert [r.subject_ref for r in repo.list_observations(data_mode=DataMode.REAL, country="CO")] == [
        "es:Con_pais"
    ]


def test_database_unique_index_handles_null_country_without_repository(
    session: Session, make_source_run: MakeSourceRun
) -> None:
    """La garantía no depende del repositorio: la base rechaza el duplicado con país NULL."""
    source_run = make_source_run(DataMode.REAL)
    insert = text(
        "INSERT INTO raw_observations (source_run_id, data_mode, source, metric_key, unit, value, "
        "observed_at, period_start, granularity, country_basis, language_basis, subject_type, "
        "subject_ref) VALUES (:run_id, 'real', 'wikimedia', 'wiki_pageviews', 'views', 1, "
        "'2026-10-16 00:00:00', '2026-10-15 00:00:00', 'day', 'none', 'none', 'wiki_article', 'es:X')"
    )
    session.execute(insert, {"run_id": source_run.id})

    with pytest.raises(IntegrityError):
        session.execute(insert, {"run_id": source_run.id})


# --- Validación de observaciones ---------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": Source.YOUTUBE},
        {"value": None, "value_text": None},
        {"value": float("nan")},
        {"country": "mx", "country_basis": CountryBasis.REPORTED_BY_SOURCE},
        {"country": "MX"},  # país sin indicar su origen
        {"country_basis": CountryBasis.PUBLISHER_COUNTRY},  # origen sin país
        {"language": None},  # idioma ausente con language_basis declarado
        {"period_start": T1, "period_end": T0},
        {"observed_at": datetime(2026, 10, 16)},  # sin zona horaria
        {"metric_key": "Wiki Pageviews"},
        {"campo_extra": 1},
    ],
)
def test_invalid_observations_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_observation(**overrides)


def test_youtube_observations_are_rejected_by_database(
    session: Session, make_source_run: MakeSourceRun
) -> None:
    source_run = make_source_run(DataMode.REAL, source=Source.YOUTUBE)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO raw_observations (source_run_id, data_mode, source, metric_key, unit, "
                "value, observed_at, period_start, granularity, country_basis, language_basis, "
                "subject_type, subject_ref) VALUES (:run_id, 'real', 'youtube', 'yt_views', 'views', "
                "1, '2026-10-16 00:00:00', '2026-10-15 00:00:00', 'day', 'none', 'none', "
                "'search_term', 'x')"
            ),
            {"run_id": source_run.id},
        )


def test_observation_source_must_match_source_run(
    repo: DetectarRepository, make_source_run: MakeSourceRun
) -> None:
    gdelt_run = make_source_run(DataMode.REAL, source=Source.GDELT)

    with pytest.raises(ValueError, match="no corresponde"):
        repo.add_observations(gdelt_run.id, [make_observation()], data_mode=DataMode.REAL)
