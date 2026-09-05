"""Resin life estimation from synthesised capacity histories.

Pure functions; no Home Assistant involved.
"""

from .pure import load

resin = load("resin")

DAY = 86400.0

# The real unit's counters and the expected interval health.py derives for it.
REAL = {"total_regens_since_install": 749, "days_since_install": 747}
CORRECT = {"total_regens_since_install": 152, "days_since_install": 747}
EXPECTED_INTERVAL = 4.902
REAL_COUNTERS = {
    "total_water_usage_since_install_tank_1": 182179,
    "total_regens_since_install": 749,
}


def build(
    days: int,
    start_cap: float,
    fade_per_year: float,
    regens_per_day: float = 1.0,
    step_days: int = 7,
):
    """Synthesize cumulative samples for a unit whose capacity fades linearly."""
    samples, gallons, regens, t = [], 0.0, 0.0, 0.0
    for d in range(0, days + 1, step_days):
        cap = start_cap - fade_per_year * (d / 365.25)
        cap = max(cap, 1.0)
        n = regens_per_day * step_days
        if d > 0:
            regens += n
            gallons += n * cap
        t = d * DAY
        samples.append({"ts": t, "gallons": gallons, "regens": regens})
    return samples


def test_no_history_is_insufficient_data():
    r = resin.analyse([])
    assert r["status"] == "insufficient_data"
    assert r["years_remaining"] is None


def test_a_short_history_is_not_extrapolated():
    r = resin.analyse(build(14, 243, 20, step_days=7))
    assert r["status"] in ("insufficient_data", "collecting")


def test_clear_degradation_is_measured():
    """243 gal/cycle fading 20/yr over two years."""
    r = resin.analyse(build(730, 243, 20))
    assert r["status"] == "ok"
    assert r["fade_per_year"] > 0
    assert 15 < r["fade_per_year"] < 25
    assert 235 < r["baseline_capacity"] < 250
    assert r["current_capacity"] < r["baseline_capacity"]
    assert r["confidence"] > 0.9
    # Baseline 243, end of life at 60% = 145.8; after two years at -20/yr the
    # current figure is ~203, so (203 - 145.8) / 20 is roughly 2.9 years.
    assert 1.5 < r["years_remaining"] < 5


def test_a_flat_trend_refuses_to_claim_infinite_life():
    r = resin.analyse(build(730, 243, 0.0))
    assert r["status"] == "no_degradation_detected"
    assert r["years_remaining"] is None


def test_a_spent_bed_reports_little_remaining():
    r = resin.analyse(build(2000, 243, 40))
    assert r["status"] in ("at_end_of_life", "ok")
    assert (r["years_remaining"] or 0) < 2


def test_a_counter_reset_does_not_invent_a_negative_life():
    s = build(730, 243, 20)
    s.append({"ts": s[-1]["ts"] + DAY, "gallons": 0.0, "regens": 0.0})
    r = resin.analyse(s)
    assert isinstance(r, dict)
    assert r["years_remaining"] is None or r["years_remaining"] >= 0


def test_malformed_and_degenerate_samples_are_ignored():
    r = resin.analyse([{"ts": 0, "gallons": 100, "regens": 0}] * 10)
    assert r["years_remaining"] is None
    bad = [{"nope": 1}, {"ts": 0, "gallons": "x", "regens": 1}]
    assert isinstance(resin.analyse(bad), dict)


def test_windows_track_the_true_capacity():
    w = resin.windowed_capacities(build(90, 243, 0.0, regens_per_day=1.0, step_days=7))
    assert len(w) > 5
    assert all(235 < v < 250 for _, v in w)


def test_sparse_regenerations_do_not_produce_noisy_windows():
    w = resin.windowed_capacities(build(30, 243, 0.0, regens_per_day=0.05, step_days=1))
    assert len(w) <= 2


def test_pruning_keeps_the_baseline_and_the_newest_sample():
    many = build(2000, 243, 10, step_days=1)
    p = resin.prune(many, max_samples=100)
    assert len(p) <= 100
    assert p[0]["ts"] == many[0]["ts"]
    assert p[-1]["ts"] == many[-1]["ts"]


def test_the_lifetime_average_capacity():
    lt = resin.capacity_per_cycle_lifetime(
        {
            "total_water_usage_since_install_tank_1": 182179,
            "total_regens_since_install": 749,
        }
    )
    assert 240 < lt < 246
    assert (
        resin.capacity_per_cycle_lifetime(
            {
                "total_water_usage_since_install_tank_1": 100,
                "total_regens_since_install": 0,
            }
        )
        is None
    )


def test_cycle_age_of_an_over_regenerating_unit():
    assert abs(resin.cycle_age_years(REAL, EXPECTED_INTERVAL) - 10.05) < 0.2
    assert abs(resin.cycle_age_acceleration(REAL, EXPECTED_INTERVAL) - 4.9) < 0.2
    assert abs(resin.excess_cycles_lifetime(REAL, EXPECTED_INTERVAL) - 597) < 3


def test_cycle_age_of_a_correctly_configured_unit_matches_the_calendar():
    assert abs(resin.cycle_age_years(CORRECT, EXPECTED_INTERVAL) - 747 / 365.25) < 0.1
    assert abs(resin.cycle_age_acceleration(CORRECT, EXPECTED_INTERVAL) - 1.0) < 0.05
    assert resin.excess_cycles_lifetime(CORRECT, EXPECTED_INTERVAL) < 1.0


def test_cycle_age_degenerate_inputs():
    under = {"total_regens_since_install": 50, "days_since_install": 747}
    assert resin.excess_cycles_lifetime(under, EXPECTED_INTERVAL) == 0.0
    assert resin.cycle_age_years(REAL, None) is None
    assert resin.cycle_age_years(REAL, 0) is None
    assert resin.cycle_age_acceleration({}, EXPECTED_INTERVAL) is None


def test_missing_or_nonsensical_counters_produce_no_figure():
    """Every counter here can be absent on older firmware, and a negative one
    means a reset. Neither may reach an entity as a number."""
    assert resin.capacity_per_cycle_lifetime({}) is None
    assert (
        resin.capacity_per_cycle_lifetime(
            {
                "total_water_usage_since_install_tank_1": "x",
                "total_regens_since_install": 1,
            }
        )
        is None
    )
    assert resin.cycle_age_years({}, EXPECTED_INTERVAL) is None
    assert (
        resin.cycle_age_years({"total_regens_since_install": -1}, EXPECTED_INTERVAL)
        is None
    )
    assert resin.excess_cycles_lifetime(REAL, None) is None
    assert resin.excess_cycles_lifetime({}, EXPECTED_INTERVAL) is None
    assert (
        resin.excess_cycles_lifetime(
            {"total_regens_since_install": 5, "days_since_install": 0},
            EXPECTED_INTERVAL,
        )
        is None
    )
    assert (
        resin.cycle_age_acceleration(
            {"total_regens_since_install": 5, "days_since_install": 0},
            EXPECTED_INTERVAL,
        )
        is None
    )


def test_a_sample_is_only_built_from_usable_counters():
    good = resin.make_sample(1000.0, REAL_COUNTERS)
    assert good == {"ts": 1000.0, "gallons": 182179.0, "regens": 749.0}
    assert resin.make_sample(1000.0, {}) is None
    assert (
        resin.make_sample(
            1000.0,
            {
                "total_water_usage_since_install_tank_1": -1,
                "total_regens_since_install": 5,
            },
        )
        is None
    )


def test_a_fit_needs_two_points_that_differ():
    assert resin._linear_fit([]) is None
    assert resin._linear_fit([(1.0, 2.0)]) is None
    # Every sample at the same instant: no slope exists.
    assert resin._linear_fit([(1.0, 2.0), (1.0, 3.0)]) is None
    slope, intercept = resin._linear_fit([(0.0, 10.0), (1.0, 8.0)])
    assert abs(slope + 2.0) < 1e-9
    assert abs(intercept - 10.0) < 1e-9


def test_a_short_history_says_it_is_still_collecting():
    """Four windows inside three weeks is a trend line drawn through noise."""
    r = resin.analyse(build(14, 243, 40, regens_per_day=2.0, step_days=2))
    assert r["status"] == "collecting"
    assert r["years_remaining"] is None
    assert r["span_days"] is not None


def test_a_baseline_of_zero_is_reported_rather_than_divided_by(monkeypatch):
    """windowed_capacities cannot produce a zero capacity today; the guard is
    what stops a future change there from dividing by zero silently."""
    flat = [(day * 86400.0, 0.0) for day in (0, 30, 60, 90)]
    monkeypatch.setattr(resin, "windowed_capacities", lambda _s: flat)
    assert resin.analyse([{"ts": 0.0}])["status"] == "invalid_baseline"


def test_a_series_with_no_usable_trend_says_so(monkeypatch):
    monkeypatch.setattr(resin, "_linear_fit", lambda _p: None)
    r = resin.analyse(build(200, 243, 40))
    assert r["status"] == "no_trend"
    assert r["years_remaining"] is None


def test_a_short_history_is_returned_unpruned():
    samples = build(30, 243, 10, step_days=1)
    assert resin.prune(samples, max_samples=1000) == samples
