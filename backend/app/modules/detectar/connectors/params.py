"""Parámetros explícitos por fuente que viajan dentro de ``ConnectorQuery``."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Primer día con datos según la documentación de Wikimedia ("starting on July 1, 2015").
WIKIMEDIA_FIRST_DAY = date(2015, 7, 1)
# Dominio de una edición de Wikipedia: es.wikipedia.org, en.wikipedia.org, zh-yue.wikipedia.org
WIKIPEDIA_PROJECT_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,8})*\.wikipedia\.org$")
# Caracteres que MediaWiki no admite en títulos, más los de control.
_FORBIDDEN_TITLE_CHARS = re.compile(r"[#<>\[\]{}|\x00-\x1f\x7f]")
MAX_TITLE_LENGTH = 255


def normalize_article_title(title: str) -> str:
    """Espacios a guiones bajos, como en las URLs de Wikipedia. No cambia mayúsculas."""
    normalized = "_".join(title.strip().split(" "))
    if not normalized or normalized.strip("_") == "":
        raise ValueError("Título de artículo vacío")
    if len(normalized.encode()) > MAX_TITLE_LENGTH:
        raise ValueError("Título de artículo demasiado largo")
    if _FORBIDDEN_TITLE_CHARS.search(normalized):
        raise ValueError(f"Título con caracteres no permitidos: {normalized!r}")
    return normalized


class WikimediaParams(BaseModel):
    """Consulta de visitas diarias. ``start`` y ``end`` son días incluidos (UTC)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    articles: tuple[str, ...] = Field(min_length=1, max_length=100)
    start: date
    end: date
    # Vacío: se usan los proyectos configurados en DETECTAR_WIKIMEDIA_PROJECTS.
    projects: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("articles")
    @classmethod
    def _check_articles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_article_title(title) for title in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Hay artículos repetidos")
        return normalized

    @field_validator("projects")
    @classmethod
    def _check_projects(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for project in value:
            if not WIKIPEDIA_PROJECT_RE.match(project):
                raise ValueError(f"Proyecto de Wikipedia inválido: {project!r}")
        if len(set(value)) != len(value):
            raise ValueError("Hay proyectos repetidos")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "WikimediaParams":
        if self.start > self.end:
            raise ValueError("start no puede ser posterior a end")
        if self.start < WIKIMEDIA_FIRST_DAY:
            raise ValueError(f"No hay datos antes de {WIKIMEDIA_FIRST_DAY.isoformat()}")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


# --- GDELT DOC 2.0 ----------------------------------------------------------------------

# Con más de una semana de intervalo la línea de tiempo es diaria (documentación oficial);
# exigir 8 días o más evita resoluciones de 15 minutos u horarias que el esquema no admite.
GDELT_MIN_DAYS = 8
# "STARTDATETIME must be within the last 3 months": se usa un margen conservador.
GDELT_MAX_LOOKBACK_DAYS = 85
# País del MEDIO (no de la audiencia): ISO 3166-1 -> valor de "sourcecountry:".
# La documentación admite un código FIPS o el nombre del país sin espacios. Se usan
# nombres para no confundir FIPS con ISO (Chile es "CI" en FIPS y "CL" en ISO); para
# Estados Unidos, el código FIPS "US" coincide con el ISO. No verificado con la API real.
GDELT_SOURCE_COUNTRIES = {
    "AR": "argentina",
    "CL": "chile",
    "CO": "colombia",
    "EC": "ecuador",
    "MX": "mexico",
    "PE": "peru",
    "US": "US",
    "VE": "venezuela",
}
# Idioma original del artículo ("sourcelang:") -> código BCP 47 que se registra.
GDELT_SOURCE_LANGUAGES = {"spanish": "es", "english": "en", "portuguese": "pt"}
# Solo letras, números, espacios, guiones y apóstrofos: impide inyectar operadores
# (sourcecountry:, comillas, paréntesis, OR) dentro del término.
_GDELT_TERM_RE = re.compile(r"^[\w][\w '\-]{1,98}[\w]$", re.UNICODE)


class GdeltParams(BaseModel):
    """Consulta de cobertura de noticias. ``start`` y ``end`` son días cerrados incluidos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    terms: tuple[str, ...] = Field(min_length=1, max_length=20)
    start: date
    end: date
    source_language: Literal["spanish", "english", "portuguese"] | None = None
    # Países de los medios (ISO). Vacío: sin filtro de país.
    source_countries: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("terms")
    @classmethod
    def _check_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(" ".join(term.split()) for term in value)
        for term in cleaned:
            if not _GDELT_TERM_RE.match(term) or "_" in term:
                raise ValueError(f"Término no admitido: {term!r}")
            if term.upper() in {"OR", "AND", "NOT"}:
                raise ValueError("Un término no puede ser un operador")
        if len({t.casefold() for t in cleaned}) != len(cleaned):
            raise ValueError("Hay términos repetidos")
        return cleaned

    @field_validator("source_countries")
    @classmethod
    def _check_countries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for country in value:
            if country not in GDELT_SOURCE_COUNTRIES:
                raise ValueError(f"País de medios no admitido: {country!r}")
        if len(set(value)) != len(value):
            raise ValueError("Hay países repetidos")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> "GdeltParams":
        if self.start > self.end:
            raise ValueError("start no puede ser posterior a end")
        if self.days < GDELT_MIN_DAYS:
            raise ValueError(f"El intervalo mínimo es de {GDELT_MIN_DAYS} días (resolución diaria)")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def queries(self) -> tuple[tuple[str, str, str | None], ...]:
        """(término, consulta GDELT, país ISO del medio o None), en orden estable."""
        countries: tuple[str | None, ...] = self.source_countries or (None,)
        result = []
        for term in self.terms:
            for country in countries:
                parts = [f'"{term}"' if " " in term else term]
                if self.source_language:
                    parts.append(f"sourcelang:{self.source_language}")
                if country:
                    parts.append(f"sourcecountry:{GDELT_SOURCE_COUNTRIES[country]}")
                result.append((term, " ".join(parts), country))
        return tuple(result)
