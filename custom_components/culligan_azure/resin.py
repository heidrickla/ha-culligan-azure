"""Resin life estimation from observed capacity fade.

Softening resin degrades: oxidation (chlorine attacks the divinylbenzene
crosslinks), osmotic shock each regeneration, and iron/sediment fouling. As it
degrades, the volume of water it can soften per regeneration falls.

Rather than assert a manufacturer life figure, this measures the ACTUAL decline
on this unit and extrapolates it. The device exposes no resin-life datapoint
(`media_life_remaining` relates to an external filter and reads 0 here), so it
must be derived.

METHOD
------
Each sample records cumulative treated volume and cumulative regeneration count.
Between two samples:

    capacity_per_cycle = (gallons_now - gallons_then) / (regens_now - regens_then)

That windowed figure is the unit's real working capacity at that moment. A
least-squares fit of capacity_per_cycle against time gives the fade rate in
gallons-per-cycle lost per year. Extrapolating from the current value down to
END_OF_LIFE_FRACTION of the baseline gives years remaining.

WHY WINDOWED, NOT LIFETIME AVERAGE
----------------------------------
total_water / total_regens is a lifetime average. It is so heavily smoothed that
a unit could lose half its capacity this year and barely move the number. The
windowed delta responds immediately.

HONESTY
-------
This needs history. It returns None with a stated reason until there is enough,
and it will not extrapolate from noise. Early estimates are wide; they narrow as
samples accumulate. Nothing here is a manufacturer specification.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Resin is conventionally considered spent when working capacity has fallen to
# roughly this fraction of its original value. Configurable; not a vendor spec.
END_OF_LIFE_FRACTION = 0.6

# Minimum evidence before any extrapolation is offered.
MIN_SAMPLES = 4
MIN_SPAN_DAYS = 21.0
# A window must contain at least this many regenerations for its capacity figure
# to be meaningful -- one or two cycles is mostly noise.
MIN_REGENS_PER_WINDOW = 3

SECONDS_PER_DAY = 86400.0
DAYS_PER_YEAR = 365.25


def capacity_per_cycle_lifetime(dp: dict[str, Any]) -> float | None:
    """Lifetime average gallons treated per regeneration.

    Useful as a headline figure, but far too smoothed to detect fade. Use the
    windowed series for trend work.
    """
    try:
        gallons = float(dp["total_water_usage_since_install_tank_1"])
        regens = float(dp["total_regens_since_install"])
    except (KeyError, TypeError, ValueError):
        return None
    if regens <= 0:
        return None
    return gallons / regens


def cycle_age_years(
    dp: dict[str, Any], expected_interval_days: float | None
) -> float | None:
    """Equivalent years of NORMAL operation, by regeneration count.

    Pure arithmetic: if the unit should regenerate every `expected_interval_days`
    but has actually done N cycles, the resin has experienced the cycling of
    N / (365.25 / expected_interval) years of correct operation.

    This deliberately measures only the cycle-count axis of wear. It says
    nothing about oxidation, which scales with treated volume and is unaffected
    by regeneration frequency -- see the module note on interpretation.
    """
    if not expected_interval_days or expected_interval_days <= 0:
        return None
    try:
        regens = float(dp["total_regens_since_install"])
    except (KeyError, TypeError, ValueError):
        return None
    if regens < 0:
        return None
    cycles_per_normal_year = DAYS_PER_YEAR / expected_interval_days
    if cycles_per_normal_year <= 0:
        return None
    return regens / cycles_per_normal_year


def excess_cycles_lifetime(
    dp: dict[str, Any], expected_interval_days: float | None
) -> float | None:
    """Regenerations performed beyond what capacity and usage justified."""
    if not expected_interval_days or expected_interval_days <= 0:
        return None
    try:
        regens = float(dp["total_regens_since_install"])
        days = float(dp["days_since_install"])
    except (KeyError, TypeError, ValueError):
        return None
    if days <= 0 or regens < 0:
        return None
    expected = days / expected_interval_days
    return max(0.0, regens - expected)


def cycle_age_acceleration(
    dp: dict[str, Any], expected_interval_days: float | None
) -> float | None:
    """How many times faster the resin is cycling than it should be.

    1.0 = correct. 5.0 = five years of cycle wear per calendar year.
    """
    equivalent = cycle_age_years(dp, expected_interval_days)
    try:
        days = float(dp["days_since_install"])
    except (KeyError, TypeError, ValueError):
        return None
    if equivalent is None or days <= 0:
        return None
    calendar_years = days / DAYS_PER_YEAR
    if calendar_years <= 0:
        return None
    return equivalent / calendar_years


def make_sample(timestamp: float, dp: dict[str, Any]) -> dict[str, float] | None:
    """Build one persistable observation, or None if the datapoints are unusable."""
    try:
        gallons = float(dp["total_water_usage_since_install_tank_1"])
        regens = float(dp["total_regens_since_install"])
    except (KeyError, TypeError, ValueError):
        return None
    if gallons < 0 or regens < 0:
        return None
    return {"ts": float(timestamp), "gallons": gallons, "regens": regens}


def windowed_capacities(
    samples: Iterable[dict[str, float]],
) -> list[tuple[float, float]]:
    """Convert cumulative samples into [(timestamp, gallons_per_cycle), ...].

    Consecutive pairs are collapsed forward until a window contains enough
    regenerations to be meaningful, so a dense poll interval does not produce a
    series of noisy one-cycle windows.
    """
    ordered = sorted(
        (s for s in samples if isinstance(s, dict) and "ts" in s),
        key=lambda s: s["ts"],
    )
    out: list[tuple[float, float]] = []
    anchor: dict[str, float] | None = None
    for s in ordered:
        if anchor is None:
            anchor = s
            continue
        d_regens = s["regens"] - anchor["regens"]
        d_gallons = s["gallons"] - anchor["gallons"]
        # Counter resets (firmware reflash, board swap) would produce negatives.
        if d_regens < 0 or d_gallons < 0:
            anchor = s
            continue
        if d_regens >= MIN_REGENS_PER_WINDOW and d_gallons > 0:
            out.append((s["ts"], d_gallons / d_regens))
            anchor = s
    return out


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares (slope, intercept) of y against x. None if degenerate."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if denom <= 0:
        return None
    slope = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denom
    return slope, mean_y - slope * mean_x


def _r_squared(
    points: list[tuple[float, float]], slope: float, intercept: float
) -> float:
    mean_y = sum(p[1] for p in points) / len(points)
    ss_tot = sum((p[1] - mean_y) ** 2 for p in points)
    ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in points)
    if ss_tot <= 0:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)


def analyse(
    samples: list[dict[str, float]], end_of_life_fraction: float = END_OF_LIFE_FRACTION
) -> dict[str, Any]:
    """Estimate resin condition and remaining life from the sample history.

    Always returns a dict. `status` explains why numeric fields are None.
    """
    result: dict[str, Any] = {
        "status": "insufficient_data",
        "samples": len(samples or []),
        "span_days": None,
        "baseline_capacity": None,
        "current_capacity": None,
        "capacity_fade_percent": None,
        "fade_per_year": None,
        "years_remaining": None,
        "confidence": None,
    }

    series = windowed_capacities(samples or [])
    result["windows"] = len(series)
    if len(series) < MIN_SAMPLES:
        return result

    span_days = (series[-1][0] - series[0][0]) / SECONDS_PER_DAY
    result["span_days"] = round(span_days, 1)
    if span_days < MIN_SPAN_DAYS:
        result["status"] = "collecting"
        return result

    # Baseline is the mean of the earliest third, current the mean of the latest
    # third -- less jumpy than single endpoints.
    third = max(1, len(series) // 3)
    baseline = sum(v for _, v in series[:third]) / third
    current = sum(v for _, v in series[-third:]) / third
    result["baseline_capacity"] = round(baseline, 1)
    result["current_capacity"] = round(current, 1)
    if baseline <= 0:
        result["status"] = "invalid_baseline"
        return result

    result["capacity_fade_percent"] = round((1.0 - current / baseline) * 100.0, 1)

    fit = _linear_fit([(ts / SECONDS_PER_DAY, v) for ts, v in series])
    if fit is None:
        result["status"] = "no_trend"
        return result
    slope_per_day, intercept = fit
    fade_per_year = -slope_per_day * DAYS_PER_YEAR  # positive when declining
    result["fade_per_year"] = round(fade_per_year, 2)

    r2 = _r_squared(
        [(ts / SECONDS_PER_DAY, v) for ts, v in series], slope_per_day, intercept
    )
    result["confidence"] = round(r2, 3)

    threshold = baseline * end_of_life_fraction
    if current <= threshold:
        result["status"] = "at_end_of_life"
        result["years_remaining"] = 0.0
        return result

    # A flat or improving trend means no measurable degradation yet. Saying
    # "infinite years" would be worse than saying we cannot tell.
    if fade_per_year <= 0:
        result["status"] = "no_degradation_detected"
        return result

    years = (current - threshold) / fade_per_year
    result["years_remaining"] = round(min(years, 50.0), 1)
    result["status"] = "ok" if r2 >= 0.3 else "low_confidence"
    return result


def prune(
    samples: list[dict[str, float]],
    max_samples: int = 400,
    min_interval_days: float = 1.0,
) -> list[dict[str, float]]:
    """Keep the history bounded without losing the long baseline.

    Thins to at most one sample per `min_interval_days`, then caps the total,
    dropping from the middle so the oldest (baseline) and newest (current)
    observations both survive.
    """
    ordered = sorted(
        (s for s in samples if isinstance(s, dict) and "ts" in s),
        key=lambda s: s["ts"],
    )
    thinned: list[dict[str, float]] = []
    for s in ordered:
        if (
            not thinned
            or (s["ts"] - thinned[-1]["ts"]) >= min_interval_days * SECONDS_PER_DAY
        ):
            thinned.append(s)
    if len(thinned) <= max_samples:
        return thinned
    keep_head = max_samples // 3
    keep_tail = max_samples - keep_head
    return thinned[:keep_head] + thinned[-keep_tail:]
