"""Unit tests for the derived health metrics. No Home Assistant required.

    python test_health.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "custom_components", "culligan_azure"))
import health  # noqa: E402

FAILURES = []


def check(name, got, want):
    ok = got == want or (
        isinstance(got, float) and isinstance(want, float) and abs(got - want) < 1e-6
    )
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    if not ok:
        FAILURES.append(name)


# Real values from the unit under test, 2026-08-10.
REAL = {
    "total_regens_since_install": 749,
    "days_since_install": 747,
    "total_regens_last_14_days": 14,
    "total_capacity": 1000,
    "average_daily_use": 204,
    "days_since_last_service": 747,
    "last_power_up_time": "2026-08-10 10:12:00",
    "errors": [
        {"num": 20, "date": "2023-08-25 03:12:07"},
        {"num": 20, "date": "2023-06-21 03:12:08"},
        {"num": 12, "date": "2023-06-08 14:52:28"},
        {"num": 20, "date": "2021-06-15 03:12:09"},
    ],
}

# A correctly configured unit: weekly regeneration, recently serviced.
HEALTHY = {
    "total_regens_since_install": 100,
    "days_since_install": 700,
    "total_regens_last_14_days": 2,
    "total_capacity": 1400,
    "average_daily_use": 200,
    "days_since_last_service": 30,
    "last_power_up_time": "2026-08-01 09:00:00",
    "errors": [],
}

print("=== real device (over-regenerating) ===")
check("recent_regens_per_day", health.recent_regens_per_day(REAL), 1.0)
check("actual_days_between_regens", health.actual_days_between_regens(REAL), 1.0)
check("expected_days_between_regens",
      round(health.expected_days_between_regens(REAL), 3), 4.902)
check("regen_efficiency_ratio", round(health.regen_efficiency_ratio(REAL), 3), 0.204)
check("is_over_regenerating", health.is_over_regenerating(REAL), True)
check("excess_regens_per_year", round(health.excess_regens_per_year(REAL)), 291)
check("error_count", health.error_count(REAL), 4)
check("most_common_error", health.most_common_error(REAL), (20, 3))
check("last_error_is_newest",
      health.last_error(REAL)["date"], "2023-08-25 03:12:07")
check("service_overdue", health.service_overdue(REAL), True)
check("clock_is_wrong_after_fix", health.clock_is_wrong(REAL, 2026), False)

print("\n=== healthy unit ===")
check("healthy_actual_interval", health.actual_days_between_regens(HEALTHY), 7.0)
check("healthy_expected_interval", health.expected_days_between_regens(HEALTHY), 7.0)
check("healthy_ratio", health.regen_efficiency_ratio(HEALTHY), 1.0)
check("healthy_not_over_regenerating", health.is_over_regenerating(HEALTHY), False)
check("healthy_no_excess", health.excess_regens_per_year(HEALTHY), 0.0)
check("healthy_service_ok", health.service_overdue(HEALTHY), False)
check("healthy_error_count", health.error_count(HEALTHY), 0)
check("healthy_no_common_error", health.most_common_error(HEALTHY), None)

print("\n=== clock detection ===")
check("clock_wrong_when_years_behind",
      health.clock_is_wrong({"last_power_up_time": "2023-11-06 02:24:00"}, 2026), True)
check("clock_sentinel_ignored",
      health.clock_is_wrong({"last_power_up_time": "0000-00-00 00:00:00"}, 2026), None)
check("clock_missing_is_none", health.clock_is_wrong({}, 2026), None)

print("\n=== degenerate inputs must not raise or lie ===")
check("empty_ratio", health.regen_efficiency_ratio({}), None)
check("zero_usage", health.expected_days_between_regens(
    {"total_capacity": 1000, "average_daily_use": 0}), None)
check("zero_days_install", health.regens_per_day(
    {"total_regens_since_install": 5, "days_since_install": 0}), None)
check("string_numbers_coerced", health.regens_per_day(
    {"total_regens_since_install": "10", "days_since_install": "5"}), 2.0)
check("errors_not_a_list", health.error_count({"errors": "nope"}), None)
check("summary_on_empty_is_safe",
      health.summary({}, now_year=2026)["over_regenerating"], None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all checks passed")
