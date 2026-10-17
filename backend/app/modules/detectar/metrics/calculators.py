"""Cálculos puros de ``metrics-v1`` (sin base de datos).

Cada función devuelve un ``Result``: un valor finito o un motivo de insuficiencia,
nunca ambos. Los datos ausentes nunca se convierten en cero.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Window:
    """Días cerrados [start, end] (ambos incluidos)."""

    start: date
    end: date

    @property
    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment.date() <= self.end


def windows(as_of: date, window_days: int, count: int) -> list[Window]:
    """``count`` ventanas consecutivas; la primera es la actual (termina en ``as_of``)."""
    if window_days < 1 or count < 1:
        raise ValueError("window_days y count deben ser positivos")
    result = []
    end = as_of
    for _ in range(count):
        start = end - timedelta(days=window_days - 1)
        result.append(Window(start, end))
        end = start - timedelta(days=1)
    return result


@dataclass(frozen=True)
class Result:
    value: float | None = None
    reason: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.value is None) == (self.reason is None):
            raise ValueError("Un resultado tiene valor o motivo, nunca ambos ni ninguno")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("El valor debe ser finito")

    @property
    def ok(self) -> bool:
        return self.value is not None


def insufficient(reason: str, **details: object) -> Result:
    return Result(reason=reason, details=details)


# --- series diarias (Wikimedia y GDELT) ---------------------------------------------------


def window_total(series: Mapping[date, float], window: Window) -> Result:
    missing = [day for day in window.days if day not in series]
    if missing:
        return insufficient(
            f"missing_days:{len(missing)}", missing=[d.isoformat() for d in missing[:31]]
        )
    return Result(value=float(sum(series[day] for day in window.days)))


def daily_mean(series: Mapping[date, float], window: Window) -> Result:
    total = window_total(series, window)
    if not total.ok:
        return total
    return Result(value=total.value / len(window.days))


def abs_change(series: Mapping[date, float], current: Window, previous: Window) -> Result:
    cur, prev = window_total(series, current), window_total(series, previous)
    if not cur.ok:
        return insufficient(f"current_{cur.reason}", **cur.details)
    if not prev.ok:
        return insufficient(f"previous_{prev.reason}", **prev.details)
    return Result(value=cur.value - prev.value, details={"current": cur.value, "previous": prev.value})


def growth(
    series: Mapping[date, float], current: Window, previous: Window, *, min_base: float
) -> Result:
    """(actual - anterior) / anterior, solo si anterior >= min_base (> 0)."""
    if min_base <= 0:
        raise ValueError("min_base debe ser positivo para evitar divisiones por cero")
    change = abs_change(series, current, previous)
    if not change.ok:
        return change
    prev = change.details["previous"]
    assert isinstance(prev, float)
    if prev < min_base:
        return insufficient(f"base_below_minimum:{min_base:g}", previous=prev)
    return Result(value=change.value / prev, details=dict(change.details))


def acceleration(
    series: Mapping[date, float], current: Window, previous: Window, before: Window, *, min_base: float
) -> Result:
    recent = growth(series, current, previous, min_base=min_base)
    if not recent.ok:
        return insufficient(f"recent_{recent.reason}", **recent.details)
    earlier = growth(series, previous, before, min_base=min_base)
    if not earlier.ok:
        return insufficient(f"earlier_{earlier.reason}", **earlier.details)
    return Result(
        value=recent.value - earlier.value,
        details={"recent_growth": recent.value, "earlier_growth": earlier.value},
    )


# --- capturas de Google Trends --------------------------------------------------------------


def presence_share(
    topic_captures: Iterable[datetime], known_captures: Iterable[datetime], window: Window, *, min_known: int
) -> Result:
    known = {c for c in known_captures if window.contains(c)}
    present = {c for c in topic_captures if window.contains(c)}
    if not present <= known:
        raise ValueError("Una captura con el tema debe estar entre las capturas conocidas")
    if len(known) < min_known:
        return insufficient(f"known_captures_below_minimum:{min_known}", known=len(known))
    return Result(value=len(present) / len(known), details={"present": len(present), "known": len(known)})


def presence_share_change(
    topic_captures: list[datetime],
    known_captures: list[datetime],
    current: Window,
    previous: Window,
    *,
    min_known: int,
) -> Result:
    cur = presence_share(topic_captures, known_captures, current, min_known=min_known)
    if not cur.ok:
        return insufficient(f"current_{cur.reason}", **cur.details)
    prev = presence_share(topic_captures, known_captures, previous, min_known=min_known)
    if not prev.ok:
        return insufficient(f"previous_{prev.reason}", **prev.details)
    return Result(value=cur.value - prev.value, details={"current": cur.value, "previous": prev.value})


def max_lower_bound(values: Iterable[tuple[datetime, float | None]], window: Window) -> Result:
    numeric = [v for moment, v in values if window.contains(moment) and v is not None]
    if not numeric:
        return insufficient("no_numeric_traffic_in_window")
    return Result(value=float(max(numeric)), details={"captures_with_value": len(numeric)})
