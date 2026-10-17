"""Configuración tipada de DETECTAR.

Solo se leen variables de entorno con el prefijo ``DETECTAR_``. No se carga ningún
archivo ``.env`` automáticamente; ``backend/detectar.env.example`` documenta las variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.detectar.connectors.params import WIKIPEDIA_PROJECT_RE

DEFAULT_COUNTRIES = ("CO", "MX", "AR", "CL", "PE", "EC", "VE", "US")
MIN_ADMIN_TOKEN_LENGTH = 32


class DetectarSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DETECTAR_",
        extra="ignore",
        frozen=True,
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    # Versión de las reglas de clasificación que usará el módulo. El archivo de reglas
    # todavía no existe (llega en E8), por eso /health lo informa como no cargado.
    rules_version: str = Field(default="v1", pattern=r"^v[0-9]+$")
    # Ruta del archivo SQLite. Si no se define, se usa una ruta fuera del repositorio
    # (ver storage.db.default_db_path). No se crea nada hasta llamar a init_db.
    db_path: Path | None = None

    # Cliente HTTP compartido por los conectores.
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    http_read_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    http_max_retries: int = Field(default=2, ge=0, le=3)
    # Contacto que se incluye en el User-Agent (Wikimedia lo exige antes de E5).
    http_contact: str | None = Field(default=None, min_length=3, max_length=200)
    # Tiempo máximo total de un conector dentro de una recolección.
    connector_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    # Frecuencia de cada agente en minutos, por id de agente. Vacío = solo ejecución manual.
    # Ejemplo: DETECTAR_AGENT_SCHEDULES='{"trend_hunter": 240}'. La usa el programador de E11.
    agent_schedules: dict[str, int] = Field(default_factory=dict)

    # --- E11: programador periódico (ver docs/e11-programador-periodico.md) ---
    # Apagado por defecto: sin esto no se ejecuta ni se recupera nada automáticamente.
    scheduler_enabled: bool = False
    scheduler_tick_seconds: float = Field(default=60.0, ge=5, le=3600)
    # data_mode de cada agente programado. Obligatorio: nunca se infiere.
    scheduler_agent_modes: dict[str, Literal["real", "simulated"]] = Field(default_factory=dict)
    # Fuentes que recolecta trend_hunter programado. Solo Google Trends: Wikimedia y GDELT
    # requieren artículos o términos explícitos. Vacío: solo procesa datos ya guardados.
    scheduler_trend_hunter_sources: tuple[Literal["google_trends_rss"], ...] = ()
    # Antigüedad mínima para considerar abandonada una ejecución pending/running que no esté
    # activa en este proceso. Debe superar holgadamente el tiempo máximo de una tarea (300 s).
    agent_abandon_after_seconds: int = Field(default=3600, ge=600, le=7 * 24 * 3600)

    # Token para POST /recolecciones. Sin valor por defecto: si no se define, el endpoint
    # responde 403 y no se puede iniciar ninguna recolección.
    admin_token: SecretStr | None = Field(default=None, min_length=MIN_ADMIN_TOKEN_LENGTH)

    # Países permitidos (ISO 3166-1 alfa-2), en JSON: DETECTAR_COUNTRIES='["MX","CO"]'.
    countries: tuple[str, ...] = Field(default=DEFAULT_COUNTRIES, min_length=1, max_length=30)
    max_countries_per_request: int = Field(default=8, ge=1, le=30)

    # Fuentes reales. Cada una se habilita explícitamente.
    gtr_mode: Literal["on", "off"] = "on"
    # Wikimedia está apagado por defecto: requiere activarlo y definir DETECTAR_HTTP_CONTACT.
    wikimedia_mode: Literal["on", "off"] = "off"
    # Ediciones de Wikipedia permitidas (dominios), en JSON.
    wikimedia_projects: tuple[str, ...] = Field(default=("es.wikipedia.org",), min_length=1, max_length=10)
    wikimedia_max_days: int = Field(default=90, ge=1, le=366)
    wikimedia_max_articles: int = Field(default=20, ge=1, le=100)
    # GDELT DOC 2.0: off por defecto. Sin credenciales; exige cita a GDELT al mostrar datos.
    gdelt_mode: Literal["on", "off"] = "off"
    # Solicitudes por recolección (términos x países de medios) y espera entre ellas.
    gdelt_max_requests: int = Field(default=5, ge=1, le=10)
    gdelt_min_interval_seconds: float = Field(default=5.0, ge=1, le=60)

    @field_validator("wikimedia_projects")
    @classmethod
    def _check_projects(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for project in value:
            if not WIKIPEDIA_PROJECT_RE.match(project):
                raise ValueError(f"Proyecto de Wikipedia inválido: {project!r}")
        if len(set(value)) != len(value):
            raise ValueError("Hay proyectos repetidos")
        return value

    @field_validator("countries")
    @classmethod
    def _check_countries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for country in value:
            if len(country) != 2 or not country.isascii() or not country.isalpha() or not country.isupper():
                raise ValueError(f"Código de país inválido: {country!r}")
        if len(set(value)) != len(value):
            raise ValueError("Hay países repetidos")
        return value


@lru_cache
def get_settings() -> DetectarSettings:
    return DetectarSettings()
