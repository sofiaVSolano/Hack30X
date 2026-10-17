"""Formato de los conjuntos de datos sintéticos y su conversión a observaciones.

El archivo declara su naturaleza (``sintetico_demostracion``), procedencia, propósito y
limitaciones. La conversión produce ``ObservationIn`` con el mismo formato que generan los
conectores reales, para que normalización, métricas y clasificación los traten igual.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.detectar.storage.models import (
    CountryBasis,
    Granularity,
    LanguageBasis,
    Source,
    SubjectType,
    Unit,
)
from app.modules.detectar.storage.repository import ObservationIn

DATASETS_DIR = Path(__file__).parent / "datasets"
DEFAULT_DATASET = DATASETS_DIR / "detectar_demo_sintetico-1.0.0.json"

Count = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WikimediaSeries(_Model):
    fuente: Literal["wikimedia"]
    proyecto: str = Field(pattern=r"^[a-z\-]+\.wikipedia\.org$")
    articulo: str = Field(min_length=1, max_length=200)
    idioma: str = Field(min_length=2, max_length=10)
    diario: dict[date, Count]


class GdeltSeries(_Model):
    fuente: Literal["gdelt"]
    termino: str = Field(min_length=2, max_length=200)
    idioma: str = Field(min_length=2, max_length=10)
    pais: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    diario: dict[date, Count]


class GtrCapture(_Model):
    momento: datetime
    titulos: list[str] = Field(min_length=1)


class GtrSeries(_Model):
    fuente: Literal["google_trends_rss"]
    pais: str = Field(pattern=r"^[A-Z]{2}$")
    capturas: list[GtrCapture] = Field(min_length=1)


class Period(_Model):
    inicio: date
    fin: date


class SyntheticDataset(_Model):
    dataset_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    # Obligatorio y fijo: un conjunto sin esta declaración no se carga.
    naturaleza: Literal["sintetico_demostracion"]
    descripcion: str = Field(min_length=20)
    procedencia: str = Field(min_length=20)
    proposito: str = Field(min_length=10)
    limitaciones: list[str] = Field(min_length=1)
    periodo: Period
    momento_registro: datetime
    fechas_metricas: list[date] = Field(min_length=1)
    fecha_clasificacion: date
    escenarios: dict[str, str]
    unidades: dict[str, str]
    series: list[Annotated[WikimediaSeries | GdeltSeries | GtrSeries, Field(discriminator="fuente")]] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "SyntheticDataset":
        if self.periodo.fin < self.periodo.inicio:
            raise ValueError("periodo.fin anterior a periodo.inicio")
        for item in self.series:
            days = item.capturas if isinstance(item, GtrSeries) else item.diario
            moments = [c.momento.date() for c in days] if isinstance(item, GtrSeries) else list(days)
            if any(d < self.periodo.inicio or d > self.periodo.fin for d in moments):
                raise ValueError("hay valores fuera del periodo declarado")
        if self.momento_registro.tzinfo is None:
            raise ValueError("momento_registro requiere zona horaria")
        if any(d < self.periodo.inicio or d > self.periodo.fin for d in [*self.fechas_metricas, self.fecha_clasificacion]):
            raise ValueError("las fechas de cálculo deben estar dentro del periodo")
        return self

    @property
    def key(self) -> str:
        """Identificador guardado en ``raw_observations.dataset_id``: id estable + versión."""
        return f"{self.dataset_id}@{self.version}"

    def sources(self) -> list[Source]:
        return sorted({Source(s.fuente) for s in self.series}, key=lambda s: s.value)

    def observations(self, source: Source) -> list[ObservationIn]:
        out: list[ObservationIn] = []
        mark = {"sintetico": True, "dataset": self.key}
        observed = self.momento_registro
        for item in self.series:
            if item.fuente != source.value:
                continue
            if isinstance(item, WikimediaSeries):
                for day, views in sorted(item.diario.items()):
                    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
                    out.append(ObservationIn(
                        source=Source.WIKIMEDIA, metric_key="wiki_pageviews", unit=Unit.VIEWS, value=views,
                        observed_at=observed, period_start=start, period_end=start + timedelta(days=1),
                        granularity=Granularity.DAY, language=item.idioma, language_basis=LanguageBasis.QUERY_FILTER,
                        subject_type=SubjectType.WIKI_ARTICLE, subject_ref=f"{item.proyecto}:{item.articulo}",
                        raw_excerpt={"article": item.articulo, **mark},
                    ))
            elif isinstance(item, GdeltSeries):
                query = f"{item.termino} sourcelang:spanish" + (f" sourcecountry:{item.pais.lower()}" if item.pais else "")
                for day, articles in sorted(item.diario.items()):
                    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
                    out.append(ObservationIn(
                        source=Source.GDELT, metric_key="gdelt_article_count", unit=Unit.ARTICLES, value=articles,
                        observed_at=observed, period_start=start, period_end=start + timedelta(days=1),
                        granularity=Granularity.DAY,
                        country=item.pais, country_basis=CountryBasis.PUBLISHER_COUNTRY if item.pais else CountryBasis.NONE,
                        language=item.idioma, language_basis=LanguageBasis.QUERY_FILTER,
                        subject_type=SubjectType.NEWS_QUERY, subject_ref=query,
                        raw_excerpt={"term": item.termino, "query": query, **mark},
                    ))
            else:
                for capture in item.capturas:
                    for title in capture.titulos:
                        out.append(ObservationIn(
                            source=Source.GOOGLE_TRENDS_RSS, metric_key="gtr_trending_presence", unit=Unit.PRESENCE,
                            value=1.0, observed_at=capture.momento, period_start=capture.momento,
                            granularity=Granularity.SNAPSHOT, country=item.pais,
                            country_basis=CountryBasis.REPORTED_BY_SOURCE, subject_type=SubjectType.SEARCH_TERM,
                            subject_ref=title, raw_excerpt=dict(mark),
                        ))
        return out


def load_dataset(path: Path = DEFAULT_DATASET) -> SyntheticDataset:
    return SyntheticDataset.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
