"""Fórmulas de metrics-v1 con datos conocidos."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.detectar.metrics import calculators as calc

AS_OF = date(2026, 10, 15)
CUR, PREV, BEFORE = calc.windows(AS_OF, 7, 3)


def series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def full(cur: float, prev: float | None = None, before: float | None = None) -> dict[date, float]:
    data = series(CUR.start, [cur] * 7)
    if prev is not None:
        data |= series(PREV.start, [prev] * 7)
    if before is not None:
        data |= series(BEFORE.start, [before] * 7)
    return data


def test_windows_are_consecutive_closed_days() -> None:
    assert (CUR.start, CUR.end) == (date(2026, 10, 9), date(2026, 10, 15))
    assert (PREV.start, PREV.end) == (date(2026, 10, 2), date(2026, 10, 8))
    assert (BEFORE.start, BEFORE.end) == (date(2026, 9, 25), date(2026, 10, 1))
    assert len(CUR.days) == 7
    with pytest.raises(ValueError):
        calc.windows(AS_OF, 0, 1)


def test_total_and_mean_with_known_values() -> None:
    data = series(CUR.start, [1, 2, 3, 4, 5, 6, 7])

    assert calc.window_total(data, CUR).value == 28.0
    assert calc.daily_mean(data, CUR).value == 4.0


def test_missing_days_are_never_zero() -> None:
    data = series(CUR.start, [10] * 6)  # falta el último día

    total = calc.window_total(data, CUR)

    assert total.value is None
    assert total.reason == "missing_days:1"
    assert total.details["missing"] == ["2026-10-15"]


def test_reported_zeros_are_kept() -> None:
    assert calc.window_total(full(0.0), CUR).value == 0.0


def test_abs_change_is_a_difference_not_a_rate() -> None:
    result = calc.abs_change(full(20, 10), CUR, PREV)

    assert result.value == 70.0  # 140 - 70
    assert result.details == {"current": 140.0, "previous": 70.0}


def test_growth_rate_formula() -> None:
    result = calc.growth(full(20, 10), CUR, PREV, min_base=70)

    assert result.value == pytest.approx(1.0)  # (140 - 70) / 70


def test_negative_growth() -> None:
    assert calc.growth(full(5, 10), CUR, PREV, min_base=70).value == pytest.approx(-0.5)


@pytest.mark.parametrize("prev_daily", [0.0, 1.0, 9.0])
def test_growth_with_small_or_zero_base_is_insufficient(prev_daily: float) -> None:
    result = calc.growth(full(50, prev_daily), CUR, PREV, min_base=70)

    assert result.value is None
    assert result.reason == "base_below_minimum:70"


def test_growth_rejects_non_positive_minimum() -> None:
    with pytest.raises(ValueError):
        calc.growth(full(1, 1), CUR, PREV, min_base=0)


def test_growth_reports_which_window_is_incomplete() -> None:
    data = full(20, 10)
    del data[PREV.start]

    assert calc.growth(data, CUR, PREV, min_base=70).reason == "previous_missing_days:1"


def test_acceleration_is_difference_of_rates() -> None:
    # before 10/día, previous 20/día (+100 %), current 30/día (+50 %) => -0.5
    result = calc.acceleration(full(30, 20, 10), CUR, PREV, BEFORE, min_base=70)

    assert result.value == pytest.approx(-0.5)
    assert result.details["recent_growth"] == pytest.approx(0.5)
    assert result.details["earlier_growth"] == pytest.approx(1.0)


def test_acceleration_needs_three_complete_windows() -> None:
    result = calc.acceleration(full(30, 20), CUR, PREV, BEFORE, min_base=70)

    assert result.reason == "earlier_previous_missing_days:7"


def test_result_invariants() -> None:
    with pytest.raises(ValueError):
        calc.Result()
    with pytest.raises(ValueError):
        calc.Result(value=1.0, reason="x")
    with pytest.raises(ValueError):
        calc.Result(value=math.inf)
    with pytest.raises(ValueError):
        calc.Result(value=math.nan)


# --- Google Trends ----------------------------------------------------------------------


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


KNOWN = [at(CUR.start + timedelta(days=i)) for i in range(4)] + [at(PREV.start + timedelta(days=i)) for i in range(5)]


def test_presence_share_formula() -> None:
    present = [KNOWN[0], KNOWN[2], KNOWN[4]]  # 2 en la actual, 1 en la anterior

    result = calc.presence_share(present, KNOWN, CUR, min_known=3)

    assert result.value == pytest.approx(0.5)  # 2 / 4
    assert result.details == {"present": 2, "known": 4}


def test_presence_share_needs_enough_known_captures() -> None:
    result = calc.presence_share([KNOWN[0]], KNOWN[:2], CUR, min_known=3)

    assert result.reason == "known_captures_below_minimum:3"


def test_presence_share_change_is_a_difference() -> None:
    present = [KNOWN[0], KNOWN[1], KNOWN[2], KNOWN[3], KNOWN[4]]  # actual 4/4, anterior 1/5

    result = calc.presence_share_change(present, KNOWN, CUR, PREV, min_known=3)

    assert result.value == pytest.approx(1.0 - 0.2)


def test_presence_must_be_subset_of_known_captures() -> None:
    with pytest.raises(ValueError):
        calc.presence_share([at(CUR.start, 3)], KNOWN, CUR, min_known=1)


def test_max_lower_bound_ignores_text_only_traffic() -> None:
    values = [(KNOWN[0], 200.0), (KNOWN[1], None), (KNOWN[2], 1000.0), (KNOWN[4], 5000.0)]

    result = calc.max_lower_bound(values, CUR)

    assert result.value == 1000.0  # el 5000 es de la ventana anterior
    assert calc.max_lower_bound([(KNOWN[0], None)], CUR).reason == "no_numeric_traffic_in_window"
