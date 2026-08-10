"""Derived health metrics for a Culligan softener.

The raw telemetry says nothing is wrong. The RELATIONSHIPS between datapoints
do -- a unit regenerating daily when its capacity implies weekly is burning
several times the salt and backwash water it should, and nothing in the app or
the API flags it.

Pure functions over a datapoints dict, so the maths is testable without Home
Assistant. Every derived value returns None when its inputs are missing or
nonsensical rather than guessing.

UNITS CAVEAT, stated plainly because it drives the headline metric:
`total_capacity` is assumed to be *gallons of treated water per regeneration
cycle*. That is consistent with the observed unit (total_capacity 1000,
average_daily_use 204, reserve_capacity_volume 500) but is NOT confirmed against
Culligan documentation. If it turns out to be grains, the expected-interval
figure scales but the "actual vs expected" comparison keeps its shape.
"""

from __future__ import annotations

from typing import Any

# Regenerating more than this many times more often than capacity implies is
# treated as a fault worth surfacing. 2x is deliberately forgiving -- reserve
# capacity and safety margins legitimately pull the real interval below the
# theoretical one.
OVER_REGEN_RATIO = 0.5

# Most residential softeners are serviced annually.
SERVICE_INTERVAL_DAYS = 365


def _num(dp: dict[str, Any], key: str) -> float | None:
    """Fetch a numeric datapoint, or None if absent/not a number."""
    v = dp.get(key)
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def regens_per_day(dp: dict[str, Any]) -> float | None:
    """Lifetime average regenerations per day."""
    total = _num(dp, "total_regens_since_install")
    days = _num(dp, "days_since_install")
    if total is None or days is None or days <= 0:
        return None
    return total / days


def recent_regens_per_day(dp: dict[str, Any]) -> float | None:
    """Regenerations per day over the trailing 14 days -- catches a unit that
    has recently started over-cycling, which the lifetime average would dilute."""
    recent = _num(dp, "total_regens_last_14_days")
    if recent is None:
        return None
    return recent / 14.0


def actual_days_between_regens(dp: dict[str, Any]) -> float | None:
    """Observed interval, preferring recent behaviour over the lifetime average."""
    rate = recent_regens_per_day(dp)
    if rate is None or rate <= 0:
        rate = regens_per_day(dp)
    if rate is None or rate <= 0:
        return None
    return 1.0 / rate


def expected_days_between_regens(dp: dict[str, Any]) -> float | None:
    """How often the unit *should* regenerate, from capacity and usage.

    See the units caveat in the module docstring.
    """
    capacity = _num(dp, "total_capacity")
    usage = _num(dp, "average_daily_use")
    if capacity is None or usage is None or usage <= 0 or capacity <= 0:
        return None
    return capacity / usage


def regen_efficiency_ratio(dp: dict[str, Any]) -> float | None:
    """actual / expected interval.

    1.0  = regenerating exactly as often as capacity implies
    <1.0 = regenerating MORE often than needed (wasting salt and water)
    >1.0 = regenerating less often (may indicate hardness breakthrough)
    """
    actual = actual_days_between_regens(dp)
    expected = expected_days_between_regens(dp)
    if actual is None or expected is None or expected <= 0:
        return None
    return actual / expected


def is_over_regenerating(dp: dict[str, Any]) -> bool | None:
    """True when the unit cycles far more often than its capacity justifies."""
    ratio = regen_efficiency_ratio(dp)
    if ratio is None:
        return None
    return ratio < OVER_REGEN_RATIO


def excess_regens_per_year(dp: dict[str, Any]) -> float | None:
    """Regenerations per year beyond what capacity implies. This is the number
    that translates into wasted salt and water."""
    actual = actual_days_between_regens(dp)
    expected = expected_days_between_regens(dp)
    if actual is None or expected is None or actual <= 0 or expected <= 0:
        return None
    excess = (365.0 / actual) - (365.0 / expected)
    return max(0.0, excess)


def error_count(dp: dict[str, Any]) -> int | None:
    """Number of entries in the on-device fault log."""
    errors = dp.get("errors")
    if not isinstance(errors, list):
        return None
    return len(errors)


def last_error(dp: dict[str, Any]) -> dict[str, Any] | None:
    """Most recent fault-log entry, by date. Dates are device-clock stamped, so
    they are only as trustworthy as the controller clock was at the time."""
    errors = dp.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    dated = [e for e in errors if isinstance(e, dict) and e.get("date")]
    if not dated:
        return None
    return max(dated, key=lambda e: str(e.get("date")))


def most_common_error(dp: dict[str, Any]) -> tuple[int, int] | None:
    """(error_number, occurrences) for the most frequent fault.

    A code that repeats is a pattern; a one-off usually is not.
    """
    errors = dp.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    counts: dict[int, int] = {}
    for e in errors:
        if isinstance(e, dict) and isinstance(e.get("num"), int):
            counts[e["num"]] = counts.get(e["num"], 0) + 1
    if not counts:
        return None
    num = max(counts, key=lambda k: counts[k])
    return num, counts[num]


def service_overdue(dp: dict[str, Any]) -> bool | None:
    days = _num(dp, "days_since_last_service")
    if days is None:
        return None
    return days > SERVICE_INTERVAL_DAYS


def clock_is_wrong(dp: dict[str, Any], now_year: int) -> bool | None:
    """True if the controller clock is implausibly far off.

    The controller keeps its own clock, separate from the wifi module's
    NTP-synced one, and nothing syncs it -- so it can sit years behind without
    any alert. Detected by comparing the last power-up stamp against reality.
    """
    stamp = dp.get("last_power_up_time")
    if not isinstance(stamp, str) or len(stamp) < 4:
        return None
    try:
        year = int(stamp[:4])
    except ValueError:
        return None
    if year < 2000:  # zero/sentinel value, not a real reading
        return None
    return abs(year - now_year) >= 1


def summary(dp: dict[str, Any], now_year: int | None = None) -> dict[str, Any]:
    """All derived metrics in one dict, for diagnostics and attributes."""
    common = most_common_error(dp)
    return {
        "regens_per_day": regens_per_day(dp),
        "recent_regens_per_day": recent_regens_per_day(dp),
        "actual_days_between_regens": actual_days_between_regens(dp),
        "expected_days_between_regens": expected_days_between_regens(dp),
        "regen_efficiency_ratio": regen_efficiency_ratio(dp),
        "over_regenerating": is_over_regenerating(dp),
        "excess_regens_per_year": excess_regens_per_year(dp),
        "error_count": error_count(dp),
        "last_error": last_error(dp),
        "most_common_error_code": common[0] if common else None,
        "most_common_error_count": common[1] if common else None,
        "service_overdue": service_overdue(dp),
        "clock_is_wrong": clock_is_wrong(dp, now_year) if now_year else None,
    }
