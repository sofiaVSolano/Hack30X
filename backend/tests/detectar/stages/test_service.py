"""Clasificación persistida: observaciones -> vínculos E7 -> métricas E8 -> etapas E9."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.detectar.metrics.service import MetricsService
from app.modules.detectar.stages.rules import RULES_VERSION
from app.modules.detectar.stages.service import (
    ClassificationService,
    StageRulesConflictError,
)
from app.modules.detectar.storage.models import (
    ClassificationEvidence,
    DataMode,
    EvidenceRole,
    RulesVersion,
    Source,
    TrendClassification,
    TrendStage,
)
from app.modules.detectar.storage.topics import topic_id_for

from ..metrics.test_service import (
    AS_OF,
    NOW,
    gdelt_series,
    link_and_compute,
    wiki_series,
)


def classify(session: Session, mode: DataMode = DataMode.REAL):
    report = ClassificationService(session, clock=lambda: NOW).classify(data_mode=mode, as_of=AS_OF)
    session.flush()
    return report


def current(session: Session, term: str, mode: DataMode = DataMode.REAL) -> TrendClassification:
    return session.scalar(
        select(TrendClassification).where(
            TrendClassification.topic_id == topic_id_for(mode, term),
            TrendClassification.superseded_at.is_(None),
        )
    )


START = AS_OF - timedelta(days=20)


def test_accelerating_topic_end_to_end(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)  # +100 %, luego +150 %
    link_and_compute(session)

    report = classify(session)

    row = current(session, "tema")
    assert row.stage is TrendStage.ACELERANDO and row.reason is None
    assert (row.rules_version, row.metrics_rules_version, row.calibrated) == (RULES_VERSION, "metrics-v1", False)
    assert row.explanation["provisional"] is True
    assert row.explanation["sources"]["wikimedia"]["rules"][0]["rule"] == "W1"
    used = [m for m in row.metrics_considered if m["used_for_stage"]]
    assert {m["metric"] for m in used} == {"wiki_views_growth", "wiki_views_acceleration"}
    assert all({"unit", "value", "status", "metrics_rules_version", "source"} <= m.keys() for m in row.metrics_considered)
    assert report.created == 1 and report.by_stage == {"acelerando": 1}


def test_missing_days_lead_to_insufficient_data(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50, 50, None, 50, 50, 50, 50])
    link_and_compute(session)

    classify(session)

    row = current(session, "tema")
    assert (row.stage, row.reason) == (TrendStage.DATOS_INSUFICIENTES, "sin_evidencia_temporal_suficiente")


def test_short_history_cannot_be_accelerating(session: Session) -> None:
    wiki_series(session, "Tema", AS_OF - timedelta(days=13), [10] * 7 + [30] * 7)  # solo 14 días
    link_and_compute(session)

    classify(session)

    row = current(session, "tema")
    assert row.stage is TrendStage.EMERGENTE  # crece; la aceleración no se puede evaluar
    assert row.explanation["sources"]["wikimedia"]["rules"][0]["rule"] == "W2"


def test_gdelt_only_topic_is_insufficient(session: Session) -> None:
    gdelt_series(session, "huracan", START, [1] * 7 + [3] * 7 + [10] * 7)
    link_and_compute(session)

    classify(session)

    row = current(session, "huracan")
    assert (row.stage, row.reason) == (TrendStage.DATOS_INSUFICIENTES, "solo_fuente_no_validada")
    gdelt = session.scalar(
        select(ClassificationEvidence).where(
            ClassificationEvidence.classification_id == row.id, ClassificationEvidence.source == Source.GDELT
        )
    )
    assert gdelt.role is EvidenceRole.COMPLEMENTARY and gdelt.source_validated is False


def test_reclassification_with_same_metrics_is_idempotent(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)
    link_and_compute(session)
    classify(session)

    again = classify(session)

    assert (again.created, again.unchanged, again.superseded) == (0, 1, 0)
    assert session.scalar(select(func.count()).select_from(TrendClassification)) == 1


def test_changed_metrics_create_a_new_result_and_keep_history(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)
    link_and_compute(session)
    classify(session)
    first = current(session, "tema")
    # Llega un día que faltaba en otro artículo vinculado al mismo tema -> métricas nuevas.
    wiki_series(session, "TEMA", START, [100] * 21)
    link_and_compute(session)

    report = classify(session)

    assert report.superseded == 1 and report.created == 1
    rows = list(session.scalars(select(TrendClassification).order_by(TrendClassification.id)))
    assert len(rows) == 2
    assert rows[0].id == first.id and rows[0].superseded_at is not None
    assert rows[1].superseded_at is None and rows[1].inputs_sha256 != rows[0].inputs_sha256


def test_rules_version_is_registered_and_immutable(session: Session) -> None:
    classify(session)
    assert session.get(RulesVersion, RULES_VERSION) is not None

    session.execute(text("UPDATE rules_versions SET params_sha256 = :x WHERE version = :v"), {"x": "0" * 64, "v": RULES_VERSION})
    with pytest.raises(StageRulesConflictError):
        classify(session)


def test_real_and_simulated_are_classified_separately(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7, mode=DataMode.REAL)
    wiki_series(session, "Tema", START, [50] * 7 + [20] * 7 + [10] * 7, mode=DataMode.SIMULATED)
    link_and_compute(session, DataMode.REAL)
    link_and_compute(session, DataMode.SIMULATED)

    classify(session, DataMode.REAL)

    assert current(session, "tema", DataMode.SIMULATED) is None
    classify(session, DataMode.SIMULATED)
    assert current(session, "tema").stage is TrendStage.ACELERANDO
    assert current(session, "tema", DataMode.SIMULATED).stage is TrendStage.DATOS_INSUFICIENTES  # descenso


def test_classification_does_not_modify_observations_links_or_metrics(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)
    link_and_compute(session)
    snapshot = lambda: tuple(
        session.execute(text(q)).all()
        for q in (
            "SELECT * FROM raw_observations ORDER BY id",
            "SELECT * FROM topic_links ORDER BY id",
            "SELECT id, value, status, reason FROM metric_values ORDER BY id",
        )
    )
    before = snapshot()

    classify(session)

    assert snapshot() == before


def test_reference_date_must_be_closed(session: Session) -> None:
    with pytest.raises(ValueError):
        ClassificationService(session, clock=lambda: NOW).classify(data_mode="real", as_of=NOW.date())


def test_topics_without_metrics_are_not_classified(session: Session) -> None:
    assert classify(session).created == 0


def test_classifications_and_evidence_are_immutable(session: Session) -> None:
    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)
    link_and_compute(session)
    classify(session)
    row = current(session, "tema")

    with pytest.raises(IntegrityError, match="reemplazada"):
        session.execute(text("UPDATE trend_classifications SET stage = 'saturada' WHERE id = :i"), {"i": row.id})
    with pytest.raises(IntegrityError, match="no se borran"):
        session.execute(text("DELETE FROM trend_classifications WHERE id = :i"), {"i": row.id})
    with pytest.raises(IntegrityError, match="inmutable"):
        session.execute(text("UPDATE classification_evidence SET role = 'primary'"))


def test_metrics_of_another_date_are_not_used(session: Session) -> None:
    from datetime import UTC, datetime

    from app.modules.detectar.storage.models import MetricValue

    wiki_series(session, "Tema", START, [10] * 7 + [20] * 7 + [50] * 7)
    link_and_compute(session)
    MetricsService(session, clock=lambda: NOW).compute(data_mode="real", as_of=AS_OF - timedelta(days=1))
    session.flush()
    as_of_dt = datetime(AS_OF.year, AS_OF.month, AS_OF.day, tzinfo=UTC)
    same_day = set(session.scalars(select(MetricValue.id).where(MetricValue.as_of == as_of_dt)))
    other_day = set(session.scalars(select(MetricValue.id).where(MetricValue.as_of != as_of_dt)))
    assert same_day and other_day

    classify(session)

    used = {m["metric_value_id"] for m in current(session, "tema").metrics_considered}
    assert used == same_day
    assert not used & other_day
