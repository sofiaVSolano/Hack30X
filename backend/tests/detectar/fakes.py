"""Conectores y relojes falsos para las pruebas. No hacen llamadas de red."""

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta

from app.modules.detectar.connectors.base import (
    Availability,
    BaseConnector,
    ConnectorAvailability,
    ConnectorQuery,
    FetchOutput,
)
from app.modules.detectar.storage.models import Source

START = datetime(2026, 10, 16, 22, 0, tzinfo=UTC)


class StepClock:
    """Reloj determinista: cada llamada avanza un segundo."""

    def __init__(self, start: datetime = START) -> None:
        self._ticks: Iterator[int] = iter(range(10_000))
        self._start = start

    def __call__(self) -> datetime:
        return self._start + timedelta(seconds=next(self._ticks))


Behaviour = Callable[[ConnectorQuery], Awaitable[FetchOutput]]


class FakeConnector(BaseConnector):
    def __init__(
        self,
        source: Source,
        behaviour: Behaviour,
        *,
        availability: Availability = Availability.READY,
        http_calls: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(clock=clock or StepClock())
        self.source = source
        self._behaviour = behaviour
        self._availability = availability
        self._calls = http_calls
        self.fetch_count = 0

    def availability(self) -> ConnectorAvailability:
        return ConnectorAvailability(self._availability, f"Prueba: {self._availability.value}")

    async def _fetch(self, query: ConnectorQuery) -> FetchOutput:
        self.fetch_count += 1
        return await self._behaviour(query)

    def _http_calls_so_far(self) -> int:
        return self._calls
