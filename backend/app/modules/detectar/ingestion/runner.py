"""Ejecución aislada de varios conectores.

Cada conector corre con su propio tiempo límite. Un conector que falla, se cuelga o lanza
una excepción inesperada produce un resultado de error y no afecta a los demás.
No hay programación periódica: esta función se invoca explícitamente.
"""

import asyncio
import logging
from collections.abc import Sequence

from app.modules.detectar.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorQuery,
    ConnectorResult,
    Outcome,
)

logger = logging.getLogger(__name__)


async def _run_one(
    connector: BaseConnector, query: ConnectorQuery, timeout_seconds: float
) -> ConnectorResult:
    started_at = connector._clock()
    try:
        async with asyncio.timeout(timeout_seconds):
            return await connector.run(query)
    except TimeoutError:
        logger.warning("Conector %s superó %.1fs", connector.source.value, timeout_seconds)
        error = ConnectorError(
            code="connector_timeout",
            detail=f"El conector superó el tiempo máximo de {timeout_seconds:g} s",
            retryable=True,
        )
    except Exception as exc:  # noqa: BLE001 - BaseConnector.run no debería lanzar
        logger.error("Fallo no controlado en %s: %s", connector.source.value, type(exc).__name__)
        error = ConnectorError(code="internal_error", detail=type(exc).__name__, retryable=False)
    return ConnectorResult(
        source=connector.source,
        outcome=Outcome.TRANSIENT_ERROR if error.retryable else Outcome.PERMANENT_ERROR,
        started_at=started_at,
        finished_at=connector._clock(),
        http_calls=connector._http_calls_so_far(),
        error=error,
    )


async def run_connectors(
    connectors: Sequence[BaseConnector],
    query: ConnectorQuery,
    *,
    timeout_seconds: float,
) -> list[ConnectorResult]:
    """Ejecuta los conectores en paralelo y devuelve un resultado por conector, en orden."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds debe ser positivo")
    sources = [connector.source for connector in connectors]
    if len(set(sources)) != len(sources):
        raise ValueError("No se puede ejecutar dos veces la misma fuente en una recolección")
    return list(
        await asyncio.gather(*(_run_one(c, query, timeout_seconds) for c in connectors))
    )
