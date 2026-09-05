"""Capability detection.

Pure module, no Home Assistant. The absent-hardware cases are the REAL readings
from a GBX1 with no Aqua-Sensor, single tank, no chem feed and no external
filter - the unit this was built against. The present-hardware cases are
constructed, because no unit with the hardware was available to read; that
asymmetry is the point of the "any non-zero means present" rule, which cannot
hide a sensor that reports real values.
"""

import pytest

from .pure import load

caps = load("capabilities")
Capability = caps.Capability

# Verbatim from the live unit: every accessory datapoint reads zero.
REAL_ABSENT = {
    "aquasensor_z_ratio_current_tank_1": 0,
    "aquasensor_z_ratio_current_tank_2": 0,
    "aquasensor_z_min_tank_1": 0,
    "aquasensor_z_min_tank_2": 0,
    "aquasensor_auto_rinse_enabled": 0,
    "total_capacity_volume_tank_1": 0,
    "total_capacity_volume_tank_2": 0,
    "unit_status_tank_2": 0,
    "total_water_usage_since_install_tank_2": 0,
    "capacity_remaining_tank_2": 0,
    "days_since_last_regen_tank_2": 0,
    "last_regen_date_time_tank_2": "0000-00-00 00:00:00",
    "chem_feed_mode": 0,
    "chem_feed_capacity_remaining": 0,
    "chem_feed_alarm_capacity": 0,
    "external_filter_mode": 0,
    "external_filter_capacity_remaining": 0,
    "external_filter_alarm_capacity": 0,
    "filter_media_life": 0,
    "media_life_remaining": 0,
    # Present and non-zero, but belonging to no capability group.
    "hardness_value": 10,
    "total_capacity": 1000,
    "capacity_remaining_tank_1": -515,
}


def test_the_real_unit_has_no_accessories():
    assert caps.detect(REAL_ABSENT) == set()
    # capacity_remaining is gated on the Aqua-Sensor precisely because the
    # controller reports it as -515 when the derived capacity is 0.
    assert Capability.AQUA_SENSOR not in caps.detect(REAL_ABSENT)


@pytest.mark.parametrize(
    ("key", "value", "capability"),
    [
        ("aquasensor_z_ratio_current_tank_1", 0.82, Capability.AQUA_SENSOR),
        ("total_capacity_volume_tank_1", 1109, Capability.AQUA_SENSOR),
        ("unit_status_tank_2", 1, Capability.SECOND_TANK),
        ("chem_feed_mode", 2, Capability.CHEM_FEED),
        ("media_life_remaining", 340, Capability.EXTERNAL_FILTER),
    ],
)
def test_one_non_zero_indicator_is_enough(key, value, capability):
    assert capability in caps.detect({**REAL_ABSENT, key: value})


@pytest.mark.parametrize(
    "datapoints",
    [
        {},
        {"last_regen_date_time_tank_2": "0000-00-00 00:00:00"},
        {"chem_feed_mode": "0"},
        {"aquasensor_auto_rinse_enabled": False},
    ],
)
def test_degenerate_values_do_not_read_as_present(datapoints):
    assert caps.detect(datapoints) == set()


def test_a_string_number_is_present():
    assert Capability.CHEM_FEED in caps.detect({"chem_feed_mode": "2"})


def test_user_overrides():
    assert Capability.AQUA_SENSOR in caps.resolve(
        REAL_ABSENT, forced_on=["aqua_sensor"]
    )
    assert Capability.CHEM_FEED not in caps.resolve(
        {**REAL_ABSENT, "chem_feed_mode": 2}, forced_off=["chem_feed"]
    )
    # Off beats on: turning something off is the explicit request.
    assert (
        caps.resolve(REAL_ABSENT, forced_on=["aqua_sensor"], forced_off=["aqua_sensor"])
        == set()
    )
    assert caps.resolve(REAL_ABSENT, forced_on=["not_a_capability"]) == set()


def test_evidence_reports_every_group_with_its_readings():
    ev = caps.evidence(REAL_ABSENT)
    assert sorted(ev) == sorted(c.value for c in Capability)
    assert ev["aqua_sensor"]["present"] is False
    assert ev["aqua_sensor"]["indicators"]["aquasensor_z_ratio_current_tank_1"] == 0


def test_what_counts_as_a_meaningful_reading():
    """The shapes this API actually returns: numbers as strings, date
    sentinels, blanks, and the occasional list."""
    meaningful = caps._is_meaningful
    assert meaningful("") is False
    assert meaningful("   ") is False
    assert meaningful("0000-00-00 00:00:00") is False
    assert meaningful("0.0") is False
    assert meaningful("2.5") is True
    # A word is real content: it cannot be a zero reading.
    assert meaningful("installed") is True
    assert meaningful([]) is False
    assert meaningful([1]) is True
    assert meaningful({}) is False
    assert meaningful(object()) is True
