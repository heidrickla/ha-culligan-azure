"""The derived health metrics, on the real unit's readings and a healthy one.

Pure functions; no Home Assistant involved.
"""

import pytest

from .pure import load

health = load("health")

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


def test_the_real_unit_is_over_regenerating():
    assert health.recent_regens_per_day(REAL) == 1.0
    assert health.actual_days_between_regens(REAL) == 1.0
    assert round(health.expected_days_between_regens(REAL), 3) == 4.902
    assert round(health.regen_efficiency_ratio(REAL), 3) == 0.204
    assert health.is_over_regenerating(REAL) is True
    assert round(health.excess_regens_per_year(REAL)) == 291


def test_the_real_unit_fault_log_and_service_state():
    assert health.error_count(REAL) == 4
    assert health.most_common_error(REAL) == (20, 3)
    assert health.last_error(REAL)["date"] == "2023-08-25 03:12:07"
    assert health.service_overdue(REAL) is True
    # The clock was corrected before this capture.
    assert health.clock_is_wrong(REAL, 2026) is False


def test_a_healthy_unit_raises_no_flags():
    assert health.actual_days_between_regens(HEALTHY) == pytest.approx(7.0)
    assert health.expected_days_between_regens(HEALTHY) == pytest.approx(7.0)
    assert health.regen_efficiency_ratio(HEALTHY) == pytest.approx(1.0)
    assert health.is_over_regenerating(HEALTHY) is False
    assert health.excess_regens_per_year(HEALTHY) == pytest.approx(0.0)
    assert health.service_overdue(HEALTHY) is False
    assert health.error_count(HEALTHY) == 0
    assert health.most_common_error(HEALTHY) is None


@pytest.mark.parametrize(
    ("datapoints", "expected"),
    [
        ({"last_power_up_time": "2023-11-06 02:24:00"}, True),
        ({"last_power_up_time": "0000-00-00 00:00:00"}, None),
        ({}, None),
    ],
)
def test_clock_detection(datapoints, expected):
    assert health.clock_is_wrong(datapoints, 2026) is expected


def test_degenerate_inputs_do_not_raise_or_lie():
    assert health.regen_efficiency_ratio({}) is None
    assert (
        health.expected_days_between_regens(
            {"total_capacity": 1000, "average_daily_use": 0}
        )
        is None
    )
    assert (
        health.regens_per_day(
            {"total_regens_since_install": 5, "days_since_install": 0}
        )
        is None
    )
    assert health.error_count({"errors": "nope"}) is None
    assert health.summary({}, now_year=2026)["over_regenerating"] is None


def test_string_numbers_are_coerced():
    """The API returns numbers as strings on some fields."""
    assert (
        health.regens_per_day(
            {"total_regens_since_install": "10", "days_since_install": "5"}
        )
        == 2.0
    )
    assert health.as_number({"x": " 3.5 "}, "x") == 3.5
    assert health.as_number({"x": True}, "x") is None
    assert health.as_number({"x": "0"}, "x") == 0.0
    # A field carrying prose rather than a number is unknown, not zero.
    assert health.as_number({"x": "unavailable"}, "x") is None
    assert health.as_number({"x": ["1"]}, "x") is None


def test_a_fault_log_with_no_usable_entries_reads_as_unknown():
    """An entry with no date cannot be the last error and one with no numeric
    code cannot be counted; neither invents a value from the rest."""
    assert health.last_error({"errors": [{"num": 20}]}) is None
    assert (
        health.most_common_error({"errors": [{"date": "2026-01-01 00:00:00"}]}) is None
    )


def test_a_power_up_stamp_that_is_not_a_year_reads_as_unknown():
    def wrong(stamp):
        return health.clock_is_wrong({"last_power_up_time": stamp}, 2026)

    assert wrong("abcd-01-01 00:00:00") is None
    assert wrong("0000-00-00 00:00:00") is None
    assert wrong("no") is None
    assert health.clock_is_wrong({}, 2026) is None


def test_a_controller_clock_set_to_the_future_is_wrong_at_once():
    """The stamp records a past event, so a future year is wrong with no slack
    while a past year gets a year of it."""

    def wrong(stamp):
        return health.clock_is_wrong({"last_power_up_time": stamp}, 2026)

    assert wrong("2030-01-01 00:00:00") is True
    assert wrong("2025-12-31 23:00:00") is False
    assert wrong("2024-01-01 00:00:00") is True
