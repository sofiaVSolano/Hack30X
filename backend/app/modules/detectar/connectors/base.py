"""Contrato común de los conectores de fuentes de datos.

Un conector:

1. informa su disponibilidad a partir de la configuración, sin hacer llamadas de red;
2. ejecuta una consulta con parámetros explícitos (:class:`ConnectorQuery`);
3. devuelve siempre un :class:`ConnectorResult`, nunca una excepción, que distingue
   resultado con datos, respuesta vacía, omisión, error temporal y error definitivo.

Los conectores solo producen datos reales. Los datos simulados no pasan por aquí.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.detectar.connectors.errors import (
    MAX_DETAIL_LENGTH,
    PermanentSourceError,
    SourceError,
)
from app.modules.detectar.connectors.params import GdeltParams, WikimediaParams
from app.modules.detectar.logsafety import redact
from app.modules.detectar.storage.models import Source
from app.modules.detectar.storage.repository import ObservationIn

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Availability(StrEnum):
    DISABLED = "disabled"  # apagado por configuración
    UNCONFIGURED = "unconfigured"  # activo pero sin credenciales o datos obligatorios
    READY = "ready"  # configurado; no garantiza que la fuente responda


@dataclass(frozen=True)
class ConnectorAvailability:
    availability: Availability
    detail: str


class Outcome(StrEnum):
    OK = "ok"  # al menos una observación
    EMPTY = "empty"  # la fuente respondió bien, pero sin datos
    PARTIAL = "partial"  # hay observaciones y también un error controlado
    SKIPPED = "skipped"  # no se ejecutó (deshabilitado o sin configurar)
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"


class ConnectorQuery(BaseModel):
    """Parámetros explícitos de una consulta. Los conectores pueden extenderlos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    countries: tuple[str, ...] = Field(default=(), max_length=30)
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None
    # Parámetros propios de Wikimedia; los demás conectores los ignoran.
    wikimedia: WikimediaParams | None = None
    gdelt: GdeltParams | None = None

    @model_validator(mode="after")
    def _check(self) -> "ConnectorQuery":
        for country in self.countries:
            if len(country) != 2 or not country.isascii() or not country.isupper():
                raise ValueError(f"Código de país inválido: {country!r}")
        if self.since and self.until and self.since >= self.until:
            raise ValueError("since debe ser anterior a until")
        return self


class ConnectorError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=64)
    detail: str = Field(max_length=MAX_DETAIL_LENGTH)
    retryable: bool


class ConnectorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Source
    outcome: Outcome
    started_at: AwareDatetime
    finished_at: AwareDatetime
    observations: tuple[ObservationIn, ...] = ()
    http_calls: int = Field(default=0, ge=0)
    error: ConnectorError | None = None
    skipped_reason: Availability | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "ConnectorResult":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at no puede ser anterior a started_at")
        has_data = bool(self.observations)
        outcome = self.outcome
        if outcome is Outcome.OK and (not has_data or self.error):
            raise ValueError("OK requiere observaciones y ningún error")
        if outcome is Outcome.EMPTY and (has_data or self.error):
            raise ValueError("EMPTY no admite observaciones ni errores")
        if outcome is Outcome.PARTIAL and (not has_data or not self.error):
            raise ValueError("PARTIAL requiere observaciones y un error")
        if outcome in (Outcome.TRANSIENT_ERROR, Outcome.PERMANENT_ERROR):
            if has_data or self.error is None:
                raise ValueError("Un error requiere el detalle del error y ninguna observación")
            if self.error.retryable != (outcome is Outcome.TRANSIENT_ERROR):
                raise ValueError("retryable no coincide con el tipo de error")
        if outcome is Outcome.SKIPPED:
            if has_data or self.error or self.http_calls:
                raise ValueError("SKIPPED no admite datos, errores ni llamadas HTTP")
            if self.skipped_reason not in (Availability.DISABLED, Availability.UNCONFIGURED):
                raise ValueError("SKIPPED requiere el motivo de la omisión")
        elif self.skipped_reason is not None:
            raise ValueError("skipped_reason solo aplica a SKIPPED")
        if any(obs.source is not self.source for obs in self.observations):
            raise ValueError("Todas las observaciones deben pertenecer a la fuente del conector")
        return self


@dataclass
class FetchOutput:
    """Lo que devuelve la implementación concreta de un conector."""

    observations: Sequence[ObservationIn]
    http_calls: int = 0
    # Error controlado cuando se obtuvieron datos solo parcialmente.
    partial_error: SourceError | None = field(default=None)


class BaseConnector(ABC):
    """Base de todos los conectores. Las subclases implementan ``availability`` y ``_fetch``."""

    source: Source

    def __init__(self, *, clock: Clock = utc_now) -> None:
        self._clock = clock

    @abstractmethod
    def availability(self) -> ConnectorAvailability:
        """Estado según la configuración. No debe hacer llamadas de red."""

    @abstractmethod
    async def _fetch(self, query: ConnectorQuery) -> FetchOutput:
        """Consulta la fuente. Lanza ``SourceError`` ante errores controlados."""

    def _http_calls_so_far(self) -> int:
        """Llamadas HTTP hechas hasta un error. Los conectores con HttpClient la sobrescriben."""
        return 0

    def _error_result(
        self, started_at: datetime, error: SourceError, http_calls: int = 0
    ) -> ConnectorResult:
        return ConnectorResult(
            source=self.source,
            outcome=Outcome.TRANSIENT_ERROR if error.retryable else Outcome.PERMANENT_ERROR,
            started_at=started_at,
            finished_at=self._clock(),
            http_calls=http_calls,
            error=ConnectorError(code=error.code, detail=error.detail, retryable=error.retryable),
        )

    async def run(self, query: ConnectorQuery) -> ConnectorResult:
        started_at = self._clock()
        status = self.availability()
        if status.availability is not Availability.READY:
            return ConnectorResult(
                source=self.source,
                outcome=Outcome.SKIPPED,
                started_at=started_at,
                finished_at=self._clock(),
                skipped_reason=status.availability,
            )

        try:
            output = await self._fetch(query)
        except SourceError as error:
            logger.warning("Conector %s: %s", self.source.value, error)
            return self._error_result(started_at, error, self._http_calls_so_far())
        except Exception as error:  # noqa: BLE001 - un conector nunca debe propagar
            # Solo se registra el tipo: el mensaje podría contener datos sensibles.
            logger.error(
                "Error inesperado en el conector %s: %s", self.source.value, type(error).__name__
            )
            internal = PermanentSourceError("internal_error", redact(type(error).__name__))
            return self._error_result(started_at, internal, self._http_calls_so_far())

        observations = tuple(output.observations)
        if output.partial_error is not None and not observations:
            return self._error_result(started_at, output.partial_error, output.http_calls)
        try:
            return ConnectorResult(
                source=self.source,
                outcome=(
                    Outcome.PARTIAL
                    if output.partial_error
                    else Outcome.OK
                    if observations
                    else Outcome.EMPTY
                ),
                started_at=started_at,
                finished_at=self._clock(),
                observations=observations,
                http_calls=output.http_calls,
                error=(
                    ConnectorError(
                        code=output.partial_error.code,
                        detail=output.partial_error.detail,
                        retryable=output.partial_error.retryable,
                    )
                    if output.partial_error
                    else None
                ),
            )
        except ValueError as error:
            # La salida del conector no cumple el contrato (por ejemplo, otra fuente).
            invalid = PermanentSourceError("invalid_connector_output", str(error))
            return self._error_result(started_at, invalid, output.http_calls)
