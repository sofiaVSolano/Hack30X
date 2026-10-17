"""Datos de prueba sintéticos para el almacenamiento.

Solo existen en bases temporales de pytest; no representan señales reales.
"""

from datetime import UTC, datetime
from typing import Any

from app.modules.detectar.storage.models import Granularity, Source, SubjectType, Unit
from app.modules.detectar.storage.repository import ObservationIn

T0 = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)

TEST_DATASET_ID = "pruebas_unitarias_v1"


def make_observation(**overrides: Any) -> ObservationIn:
    fields: dict[str, Any] = {
        "source": Source.WIKIMEDIA,
        "metric_key": "wiki_pageviews",
        "unit": Unit.VIEWS,
        "value": 100.0,
        "observed_at": T1,
        "period_start": T0,
        "period_end": T1,
        "granularity": Granularity.DAY,
        "language": "es",
        "language_basis": "reported_by_source",
        "subject_type": SubjectType.WIKI_ARTICLE,
        "subject_ref": "es:Tema_de_prueba",
    }
    fields.update(overrides)
    return ObservationIn(**fields)
