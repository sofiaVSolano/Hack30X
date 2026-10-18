"""Configuración tipada de CREAR.

Solo se leen variables de entorno con el prefijo ``CREAR_``. La credencial de Claude no es
una variable de CREAR: el SDK oficial de Anthropic la toma de ``ANTHROPIC_API_KEY`` (o de un
perfil de ``ant auth login``), así que CREAR nunca la guarda, la devuelve ni la registra.
``backend/crear.env.example`` documenta las variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "claude-opus-5-5"


class CrearSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CREAR_", extra="ignore", frozen=True)

    # Archivo SQLite de las propuestas. Sin definir: crear.db junto a la base de DETECTAR si
    # DETECTAR_DB_PATH está definida (la demostración guarda así sus propuestas en su carpeta
    # temporal); si no, una ruta fuera del repositorio (ver storage.db.default_db_path).
    db_path: Path | None = None

    # Motor de generación:
    # - auto: Claude si hay una credencial de Anthropic en el entorno; si no, plantillas.
    # - plantillas: siempre el motor determinista, sin red.
    # - claude: siempre Claude (si falla, se usan plantillas y la propuesta lo indica).
    motor: Literal["auto", "plantillas", "claude"] = "auto"
    modelo: str = Field(default=DEFAULT_MODEL, pattern=r"^claude-[a-z0-9-]{3,60}$")
    # Esfuerzo de razonamiento de Claude (output_config.effort).
    esfuerzo: Literal["low", "medium", "high"] = "medium"
    claude_timeout_seconds: float = Field(default=90.0, ge=10, le=300)
    claude_max_retries: int = Field(default=1, ge=0, le=3)


@lru_cache
def get_crear_settings() -> CrearSettings:
    return CrearSettings()
