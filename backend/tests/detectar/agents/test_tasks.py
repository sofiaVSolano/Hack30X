"""Tareas reales de E10 (trend_hunter y supervisor) con servicios reales y HTTP simulado."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.detectar.agents.coordinator import LocalAgentCoordinator
from app.modules.detectar.agents.registry import default_registry
from app.modules.detectar.agents.tasks import TaskDependencies, build_tasks
from app.modules.detectar.config import DetectarSettings
from app.modules.detectar.connectors.google_trends_rss import GTR_RSS_URL
from app.modules.detectar.ingestion.collection import CollectionService
from app.modules.detectar.storage.agent_runs import AgentRunRepository
from app.modules.detectar.storage.models import (
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    CollectionRun,
    CollectionStatus,
    DataMode,
    MetricValue,
    TrendClassification,
)

from ..metrics.test_service import AS_OF, NOW, gdelt_series, wiki_series

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "google_trends_rss"
REAL_YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


def rss_transport(responses: dict[str, int | str]) -> httpx.MockTransport:
    """País -> nombre de fixture (200) o código HTTP de error."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(GTR_RSS_URL)
        answer = responses[request.url.params["geo"]]
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=(FIXTURES / answer).read_bytes())

    return httpx.MockTransport(handler)


class ForbiddenCollection:
    """Falla si alguien intenta recolectar (para flujos sin recolección)."""

    async def collect(self, *args: Any, **kwargs: Any):
        raise AssertionError("No debía recolectar")


def coordinator(
    session_factory: sessionmaker[Session],
    *,
    transport: httpx.MockTransport | None = None,
    clock=None,
    settings: DetectarSettings | None = None,
) -> LocalAgentCoordinator:
    registry = default_registry()
    settings = settings or DetectarSettings(env="test", http_max_retries=0)
    collection = (
        CollectionService(session_factory, settings, http_transport=transport)
        if transport is not None
        else ForbiddenCollection()
    )
    deps = TaskDependencies(
        session_factory=session_factory,
        collection_service=collection,  # type: ignore[arg-type]
        registry=registry,
        **({"clock": clock} if clock else {}),
    )
    return LocalAgentCoordinator(session_factory, registry, tasks=build_tasks(deps), **({"clock": clock} if clock else {}))


def trends_params(as_of: date, countries=("MX",)) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat(),
        "collection": {"sources": ["google_trends_rss"], "countries": list(countries)},
    }


# --- trend_hunter: modo real con recolección -------------------------------------------------


async def test_trend_hunter_runs_the_real_pipeline_and_reports_what_happened(session_factory) -> None:
    run = await coordinator(session_factory, transport=rss_transport({"MX": "two_trends.xml"})).start(
        "trend_hunter", data_mode="real", params=trends_params(REAL_YESTERDAY)
    )

    assert run.status is AgentRunStatus.COMPLETED and run.error_code is None
    result = run.result
    collection = result["pasos"]["recoleccion"]
    assert (collection["ejecutada"], collection["estado"]) == (True, "ok")
    assert collection["fuentes"]["google_trends_rss"]["observaciones_nuevas"] == 3
    assert result["pasos"]["normalizacion"]["procesadas"] == 3
    assert result["pasos"]["normalizacion"]["temas_creados"] == 2
    # Las capturas son de hoy: no entran en la ventana de ayer. No se inventan métricas.
    assert result["pasos"]["metricas"]["valores_escritos"] == 0
    assert result["estado_objetivo"] == "con_limitaciones"
    assert any("Ninguna métrica" in item for item in result["limitaciones"])
    assert any("no calibradas" in item for item in result["limitaciones"])
    with session_factory() as session:
        stored = session.scalar(select(CollectionRun).where(CollectionRun.id == collection["run_id"]))
        assert stored.status is CollectionStatus.OK


async def test_failed_collection_fails_the_run(session_factory) -> None:
    run = await coordinator(session_factory, transport=rss_transport({"MX": 503})).start(
        "trend_hunter", data_mode="real", params=trends_params(REAL_YESTERDAY)
    )

    assert run.status is AgentRunStatus.FAILED
    assert run.result is None
    assert "collection_failed" in run.error_detail
    with session_factory() as session:
        (collection,) = session.scalars(select(CollectionRun)).all()
        assert collection.status is CollectionStatus.FAILED  # queda registrada, no se oculta


async def test_partial_collection_is_completed_with_explicit_limitations(session_factory) -> None:
    run = await coordinator(
        session_factory, transport=rss_transport({"MX": "two_trends.xml", "AR": 500})
    ).start("trend_hunter", data_mode="real", params=trends_params(REAL_YESTERDAY, ("MX", "AR")))

    assert run.status is AgentRunStatus.COMPLETED
    assert run.result["pasos"]["recoleccion"]["estado"] == "partial"
    assert run.result["pasos"]["recoleccion"]["fuentes"]["google_trends_rss"]["estado"] == "partial"
    assert any("google_trends_rss" in item for item in run.result["limitaciones"])


async def test_disabled_source_fails_without_collecting(session_factory) -> None:
    settings = DetectarSettings(env="test", gdelt_mode="off")
    params = {"as_of": REAL_YESTERDAY.isoformat(), "collection": {"sources": ["gdelt"]}}

    run = await coordinator(session_factory, transport=rss_transport({}), settings=settings).start(
        "trend_hunter", data_mode="real", params=params
    )

    assert run.status is AgentRunStatus.FAILED
    assert "SourceNotEnabledError" in run.error_detail


# --- trend_hunter: modo simulado y datos existentes ----------------------------------------


async def test_simulated_run_processes_existing_data_and_matches_the_database(session_factory) -> None:
    with session_factory() as session, session.begin():
        wiki_series(session, "Tema", AS_OF - timedelta(days=20), [10] * 7 + [20] * 7 + [50] * 7, mode=DataMode.SIMULATED)

    run = await coordinator(session_factory, clock=lambda: NOW).start(
        "trend_hunter", data_mode="simulated", params={"as_of": AS_OF.isoformat()}
    )

    assert run.status is AgentRunStatus.COMPLETED and run.data_mode is DataMode.SIMULATED
    steps = run.result["pasos"]
    assert steps["recoleccion"]["ejecutada"] is False
    assert steps["clasificacion"]["por_etapa"] == {"acelerando": 1}
    assert steps["clasificacion"]["calibrada"] is False
    with session_factory() as session:
        metrics = session.scalar(select(func.count()).select_from(MetricValue).where(MetricValue.data_mode == DataMode.SIMULATED))
        stages = session.scalar(select(func.count()).select_from(TrendClassification))
        assert steps["metricas"]["valores_escritos"] == metrics  # el resumen es lo que hay en la base
        assert steps["clasificacion"]["creadas"] == stages == 1
        assert session.scalar(select(func.count()).select_from(MetricValue).where(MetricValue.data_mode == DataMode.REAL)) == 0


async def test_simulated_mode_cannot_collect(session_factory) -> None:
    run = await coordinator(session_factory, clock=lambda: NOW).start(
        "trend_hunter", data_mode="simulated", params=trends_params(AS_OF)
    )

    assert run.status is AgentRunStatus.FAILED
    assert "modo real" in run.error_detail


async def test_gdelt_only_data_is_reported_as_unvalidated_and_insufficient(session_factory) -> None:
    with session_factory() as session, session.begin():
        gdelt_series(session, "huracan", AS_OF - timedelta(days=20), [1] * 7 + [3] * 7 + [10] * 7)

    run = await coordinator(session_factory, clock=lambda: NOW).start(
        "trend_hunter", data_mode="real", params={"as_of": AS_OF.isoformat()}
    )

    assert run.status is AgentRunStatus.COMPLETED
    assert run.result["pasos"]["clasificacion"]["por_etapa"] == {"datos_insuficientes": 1}
    assert any("GDELT no está validada" in item for item in run.result["limitaciones"])
    with session_factory() as session:
        assert not session.scalar(select(func.count()).select_from(MetricValue).where(MetricValue.source_validated.is_(True)))


async def test_no_data_produces_an_explicit_result(session_factory) -> None:
    run = await coordinator(session_factory, clock=lambda: NOW).start(
        "trend_hunter", data_mode="real", params={"as_of": AS_OF.isoformat()}
    )

    assert run.status is AgentRunStatus.COMPLETED
    assert run.result["estado_objetivo"] == "con_limitaciones"
    assert run.result["pasos"]["normalizacion"]["procesadas"] == 0
    assert any("Ningún tema" in item for item in run.result["limitaciones"])


@pytest.mark.parametrize(
    "params",
    [{}, {"as_of": "no-es-fecha"}, {"as_of": AS_OF.isoformat(), "extra": 1}, {"as_of": NOW.date().isoformat()}],
)
async def test_invalid_parameters_fail_the_run(session_factory, params) -> None:
    run = await coordinator(session_factory, clock=lambda: NOW).start("trend_hunter", data_mode="real", params=params)

    assert run.status is AgentRunStatus.FAILED and run.result is None


# --- supervisor --------------------------------------------------------------------------


async def test_supervisor_without_previous_runs(session_factory) -> None:
    run = await coordinator(session_factory).start("supervisor", data_mode="real", params={})

    result = run.result
    assert run.status is AgentRunStatus.COMPLETED
    assert result["sin_actividad_registrada"] is True
    assert "supervisor" not in result["agentes"]
    assert sorted(result["agentes_sin_ejecuciones"]) == sorted(
        d.id for d in default_registry().all() if d.id != "supervisor"
    )
    assert set(result["totales_por_estado"].values()) == {0}


def _past_run(session_factory, agent_id: str, status: AgentRunStatus, mode=DataMode.REAL, minutes=0) -> str:
    t0 = datetime(2026, 10, 10, 12, tzinfo=UTC) + timedelta(minutes=minutes)
    with session_factory() as session, session.begin():
        repo = AgentRunRepository(session)
        run = repo.create(agent_id, data_mode=mode, trigger=AgentRunTrigger.MANUAL, requested_at=t0)
        if status is AgentRunStatus.BLOCKED:
            repo.mark_blocked(run.id, data_mode=mode, finished_at=t0, error_code="not_implemented", error_detail="x")
        else:
            repo.mark_running(run.id, data_mode=mode, started_at=t0)
            if status is AgentRunStatus.COMPLETED:
                repo.mark_completed(run.id, data_mode=mode, finished_at=t0 + timedelta(seconds=1), result={"ok": True})
            elif status is AgentRunStatus.FAILED:
                repo.mark_failed(run.id, data_mode=mode, finished_at=t0 + timedelta(seconds=1), error_code="task_error", error_detail="falló")
        return run.id


async def test_supervisor_consolidates_recorded_runs_without_touching_them(session_factory) -> None:
    _past_run(session_factory, "trend_hunter", AgentRunStatus.COMPLETED, minutes=0)
    last = _past_run(session_factory, "trend_hunter", AgentRunStatus.FAILED, minutes=5)
    _past_run(session_factory, "format_hunter", AgentRunStatus.BLOCKED, minutes=1)
    _past_run(session_factory, "analyst", AgentRunStatus.COMPLETED, mode=DataMode.SIMULATED)
    with session_factory() as session:
        before = session.execute(text("SELECT * FROM agent_runs ORDER BY id")).all()

    run = await coordinator(session_factory).start("supervisor", data_mode="real", params={"per_agent_limit": 10})

    result = run.result
    hunter = result["agentes"]["trend_hunter"]
    assert hunter["conteo_por_estado"]["completed"] == 1 and hunter["conteo_por_estado"]["failed"] == 1
    assert hunter["ultima_ejecucion"]["id"] == last
    assert hunter["ultima_ejecucion"]["estado"] == "failed"  # nunca se convierte en éxito
    assert result["agentes"]["format_hunter"]["conteo_por_estado"]["blocked"] == 1
    assert result["agentes"]["analyst"]["ejecuciones_consideradas"] == 0  # la simulada no cuenta
    assert result["sin_actividad_registrada"] is False
    with session_factory() as session:
        after = session.execute(text("SELECT * FROM agent_runs WHERE agent_id != 'supervisor' ORDER BY id")).all()
        others = session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.agent_id != "supervisor"))
    assert after == before  # no modificó ni inició otras ejecuciones
    assert others == 4


async def test_supervisor_is_deterministic(session_factory) -> None:
    _past_run(session_factory, "trend_hunter", AgentRunStatus.COMPLETED)
    coord = coordinator(session_factory)

    first = await coord.start("supervisor", data_mode="real", params={})
    second = await coord.start("supervisor", data_mode="real", params={})

    assert first.result == second.result


async def test_supervisor_rejects_invalid_limits(session_factory) -> None:
    run = await coordinator(session_factory).start("supervisor", data_mode="real", params={"per_agent_limit": 0})

    assert run.status is AgentRunStatus.FAILED


async def test_other_roles_stay_blocked(session_factory) -> None:
    run = await coordinator(session_factory).start("analyst", data_mode="real", params={})

    assert (run.status, run.error_code) == (AgentRunStatus.BLOCKED, "not_implemented")
