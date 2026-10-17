"""Motor puro de clasificación ``stages-v1`` (sin base de datos).

Recibe instantáneas de métricas E8 de UN tema, UN ``data_mode`` y UNA fecha, y devuelve la
etapa, la contribución de cada fuente y la explicación de las reglas aplicadas.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modules.detectar.metrics.definitions import SOURCE_VALIDATED
from app.modules.detectar.stages.rules import (
    METRICS_RULES_VERSION,
    PARAMS,
    STAGE_METRICS,
)
from app.modules.detectar.storage.models import (
    DataMode,
    EvidenceRole,
    MetricStatus,
    Source,
    TrendStage,
)

STAGE_SOURCES = (Source.WIKIMEDIA, Source.GDELT, Source.GOOGLE_TRENDS_RSS)


@dataclass(frozen=True)
class MetricSnapshot:
    id: int
    data_mode: DataMode
    metric_key: str
    source: Source
    scope: str
    unit: str
    value: float | None
    status: MetricStatus
    reason: str | None
    window_days: int
    rules_version: str
    source_validated: bool
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "metric_value_id": self.id,
            "metric": self.metric_key,
            "source": self.source.value,
            "scope": self.scope,
            "unit": self.unit,
            "value": self.value,
            "status": self.status.value,
            "reason": self.reason,
            "metrics_rules_version": self.rules_version,
            "source_validated": self.source_validated,
        }


@dataclass(frozen=True)
class ScopeSignal:
    scope: str
    stage: TrendStage | None
    rule: str
    explanation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "proposed_stage": self.stage.value if self.stage else None,
            "rule": self.rule,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class SourceEvidence:
    source: Source
    role: EvidenceRole
    source_validated: bool
    proposed_stage: TrendStage | None
    reason: str
    scopes: tuple[ScopeSignal, ...]


@dataclass(frozen=True)
class Classification:
    stage: TrendStage
    reason: str | None
    evidence: tuple[SourceEvidence, ...]
    metrics_considered: tuple[MetricSnapshot, ...]
    notes: tuple[str, ...]


class MixedInputError(ValueError):
    """Métricas de otro data_mode, versión o ventana: no se pueden combinar."""


def _f(name: str) -> float:
    value = PARAMS[name]
    assert isinstance(value, int | float)
    return float(value)


# --- reglas por ámbito -----------------------------------------------------------------


def _growth_scope(scope: str, growth: MetricSnapshot | None, accel: MetricSnapshot | None) -> ScopeSignal:
    g_min, a_min, flat = _f("growth_min"), _f("acceleration_min"), _f("flat_band")
    if growth is None or growth.status is not MetricStatus.OK or growth.value is None:
        why = growth.reason if growth else "métrica de crecimiento ausente"
        return ScopeSignal(scope, None, "W0", f"Crecimiento no disponible: {why}")
    g = growth.value
    accel_ok = accel is not None and accel.status is MetricStatus.OK and accel.value is not None
    a = accel.value if accel_ok else None
    earlier = accel.details.get("earlier_growth") if accel_ok else None

    if g >= g_min:
        if a is None:
            why = accel.reason if accel else "métrica de aceleración ausente"
            return ScopeSignal(scope, TrendStage.EMERGENTE, "W2", f"g={g:.3f} >= {g_min}; aceleración no evaluable ({why})")
        if a >= a_min:
            return ScopeSignal(scope, TrendStage.ACELERANDO, "W1", f"g={g:.3f} >= {g_min} y a={a:.3f} >= {a_min}")
        if a > -a_min:
            return ScopeSignal(scope, TrendStage.EMERGENTE, "W3", f"g={g:.3f} >= {g_min}; |a|={abs(a):.3f} < {a_min}")
        return ScopeSignal(scope, None, "W4", f"g={g:.3f} crece pero a={a:.3f} <= -{a_min}: desacelera; no distingue de un máximo")
    if abs(g) < flat:
        if isinstance(earlier, int | float) and earlier >= g_min:
            return ScopeSignal(
                scope, TrendStage.PUNTO_MAXIMO, "W5",
                f"|g|={abs(g):.3f} < {flat} tras g_prev={earlier:.3f} >= {g_min}: meseta tras subida",
            )
        why = "sin historia para inferir un máximo" if earlier is None else f"g_prev={earlier:.3f} < {g_min}"
        return ScopeSignal(scope, None, "W6", f"Estable (|g|={abs(g):.3f}); {why}")
    if g <= -flat:
        return ScopeSignal(scope, None, "W7", f"g={g:.3f} <= -{flat}: descenso (no es una etapa definida en v1)")
    return ScopeSignal(scope, None, "W8", f"g={g:.3f} entre {flat} y {g_min}: crecimiento moderado bajo el umbral")


def _gtr_scope(scope: str, change: MetricSnapshot | None) -> ScopeSignal:
    rise = _f("gtr_share_rise_min")
    if change is None or change.status is not MetricStatus.OK or change.value is None:
        why = change.reason if change else "métrica ausente"
        return ScopeSignal(scope, None, "G0", f"Cambio de presencia no disponible: {why}")
    previous, current = change.details.get("previous"), change.details.get("current")
    if previous == 0 and isinstance(current, int | float) and current > 0:
        return ScopeSignal(scope, TrendStage.EMERGENTE, "G1", f"Apareció en capturas recientes (0 -> {current:.3f})")
    if change.value >= rise:
        return ScopeSignal(scope, TrendStage.EMERGENTE, "G2", f"Presencia en aumento: +{change.value:.3f} >= {rise}")
    return ScopeSignal(scope, None, "G3", f"Cambio de presencia {change.value:+.3f}: sin señal de aparición")


# --- combinación -----------------------------------------------------------------------


def _source_evidence(source: Source, snapshots: list[MetricSnapshot]) -> SourceEvidence:
    keys = STAGE_METRICS[source]
    by_scope: dict[str, dict[str, MetricSnapshot]] = defaultdict(dict)
    for snap in snapshots:
        if snap.metric_key in keys:
            by_scope[snap.scope][snap.metric_key] = snap
    # Sin métricas de la fuente, se informa el estado real de validación de su conector (el mismo
    # que llevan sus métricas), no "no validada": así una fuente validada nunca aparece degradada.
    validated = all(s.source_validated for s in snapshots) if snapshots else SOURCE_VALIDATED.get(source, False)
    role_if_used = EvidenceRole.PRIMARY if validated else EvidenceRole.COMPLEMENTARY
    if not by_scope:
        return SourceEvidence(source, EvidenceRole.EXCLUDED, validated, None, "sin métricas de etapa para esta fuente", ())

    signals = []
    for scope, metrics in sorted(by_scope.items()):
        if source is Source.GOOGLE_TRENDS_RSS:
            signals.append(_gtr_scope(scope, metrics.get(keys[0])))
        else:
            signals.append(_growth_scope(scope, metrics.get(keys[0]), metrics.get(keys[1])))  # type: ignore[misc]
    stages = {s.stage for s in signals if s.stage is not None}
    if not stages:
        return SourceEvidence(source, EvidenceRole.EXCLUDED, validated, None, "ningún ámbito aporta señal", tuple(signals))
    if len(stages) > 1:
        names = ", ".join(sorted(s.value for s in stages))
        return SourceEvidence(source, EvidenceRole.EXCLUDED, validated, None, f"ámbitos contradictorios: {names}", tuple(signals))
    (stage,) = stages
    return SourceEvidence(source, role_if_used, validated, stage, "señal consistente entre ámbitos", tuple(signals))


def classify(snapshots: Sequence[MetricSnapshot], *, data_mode: DataMode) -> Classification:
    for snap in snapshots:
        if snap.data_mode is not data_mode:
            raise MixedInputError("Métrica de otro data_mode")
        if snap.rules_version != METRICS_RULES_VERSION:
            raise MixedInputError(f"Métrica de otra versión ({snap.rules_version})")
        if snap.window_days != PARAMS["window_days"]:
            raise MixedInputError("Métrica con otra ventana")

    by_source: dict[Source, list[MetricSnapshot]] = defaultdict(list)
    for snap in snapshots:
        by_source[snap.source].append(snap)
    evidence = tuple(_source_evidence(source, by_source.get(source, [])) for source in STAGE_SOURCES)

    primary = [e for e in evidence if e.role is EvidenceRole.PRIMARY]
    complementary = [e for e in evidence if e.role is EvidenceRole.COMPLEMENTARY]
    stages = {e.proposed_stage for e in primary}
    notes: list[str] = []

    if not stages:
        reason = "solo_fuente_no_validada" if complementary else "sin_evidencia_temporal_suficiente"
        stage, final_reason = TrendStage.DATOS_INSUFICIENTES, reason
    elif len(stages) == 1:
        (stage,) = stages
        final_reason = None
    elif stages == {TrendStage.EMERGENTE, TrendStage.ACELERANDO}:
        stage, final_reason = TrendStage.ACELERANDO, None
        notes.append("Compatibles: Google Trends informa aparición; la evidencia temporal más específica indica aceleración")
    else:
        stage, final_reason = TrendStage.DATOS_INSUFICIENTES, "senales_contradictorias"

    for item in complementary:
        relation = "coincide" if item.proposed_stage == stage else "no coincide"
        notes.append(
            f"{item.source.value} (no validada) propone {item.proposed_stage.value} y {relation}; no determina la etapa"
        )
    assert stage is not None
    return Classification(stage, final_reason, evidence, tuple(snapshots), tuple(notes))
