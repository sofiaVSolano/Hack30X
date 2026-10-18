"""Brechas inglés–español sobre los datos persistidos de DETECTAR (RF-06).

Solo lectura: toma las métricas ``metrics-v1`` de una fecha de referencia (por defecto, la
más reciente con métricas) y aplica ``brechas-v1`` a cada tema. No guarda nada: el análisis se
recalcula en cada consulta, así que siempre refleja lo último que calculó DETECTAR.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.modules.crear.detectar_reader import DetectarReader, MetricInfo, StageInfo
from app.modules.crear.gaps.engine import GapAnalysis, analyze_topic
from app.modules.crear.gaps.rules import SOURCE_METRICS, VERDICT_ORDER
from app.modules.detectar.storage.models import DataMode, Source


@dataclass(frozen=True)
class GapReport:
    data_mode: DataMode
    as_of: date | None  # None: DETECTAR todavía no calculó métricas en este modo
    analyses: list[GapAnalysis] = field(default_factory=list)
    stages: dict[str, StageInfo] = field(default_factory=dict)


def _sort_key(analysis: GapAnalysis) -> tuple[int, float, float, str]:
    return (
        VERDICT_ORDER.index(analysis.verdict),
        -(analysis.headline_ratio or 0.0),
        -analysis.english_volume,
        analysis.topic_name.casefold(),
    )


class GapService:
    def __init__(self, reader: DetectarReader) -> None:
        self._reader = reader

    def analyze(
        self,
        *,
        data_mode: DataMode | str,
        as_of: date | None = None,
        topic_ids: Sequence[str] | None = None,
    ) -> GapReport:
        mode = DataMode(data_mode)
        day = as_of or self._reader.latest_metrics_date(data_mode=mode)
        if day is None:
            return GapReport(mode, None)
        keys = [key for source_keys in SOURCE_METRICS.values() for key in source_keys]
        by_topic: dict[str, list[MetricInfo]] = defaultdict(list)
        for metric in self._reader.metrics(data_mode=mode, as_of=day, keys=keys, topic_ids=topic_ids):
            by_topic[metric.topic_id].append(metric)
        uses_trends = any(m.source is Source.GOOGLE_TRENDS_RSS for items in by_topic.values() for m in items)
        known = self._reader.gtr_known_captures(data_mode=mode, as_of=day) if uses_trends else {}
        names = self._reader.topic_names(list(by_topic), data_mode=mode)
        analyses = [
            analysis
            for topic_id, metrics in by_topic.items()
            if (analysis := analyze_topic(topic_id, names.get(topic_id, topic_id), metrics, known)).comparisons
        ]
        analyses.sort(key=_sort_key)
        stages = self._reader.current_stages([a.topic_id for a in analyses], data_mode=mode)
        return GapReport(mode, day, analyses, stages)

    def analyze_one(self, topic_id: str, *, data_mode: DataMode | str, as_of: date | None = None) -> GapReport:
        return self.analyze(data_mode=data_mode, as_of=as_of, topic_ids=[topic_id])
