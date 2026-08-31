"""Capability detection tests.

    python tests/test_capabilities.py

Pure module, no Home Assistant. The absent-hardware cases are the REAL readings
from a GBX1 with no Aqua-Sensor, single tank, no chem feed and no external
filter - the unit this was built against. The present-hardware cases are
constructed, because no unit with the hardware was available to read; that
asymmetry is the point of the "any non-zero means present" rule, which cannot
hide a sensor that reports real values.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMP = ROOT / "custom_components" / "culligan_azure"

_spec = importlib.util.spec_from_file_location("caps", COMP / "capabilities.py")
assert _spec and _spec.loader
caps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(caps)

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

CHECKS: list[tuple[str, bool]] = []


def check(name: str, got: object, want: object) -> None:
    ok = got == want
    CHECKS.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")


def main() -> int:
    print("absent hardware (real readings)")
    check("nothing detected", caps.detect(REAL_ABSENT), set())

    print("\nthe -515 case this exists to prevent")
    # capacity_remaining is gated on the Aqua-Sensor precisely because the
    # controller reports it as negative when the derived capacity is 0.
    check(
        "aqua sensor absent so capacity is not shown",
        Capability.AQUA_SENSOR in caps.detect(REAL_ABSENT),
        False,
    )

    print("\npresent hardware")
    check(
        "a reading Aqua-Sensor is detected",
        Capability.AQUA_SENSOR
        in caps.detect({**REAL_ABSENT, "aquasensor_z_ratio_current_tank_1": 0.82}),
        True,
    )
    check(
        "a derived working capacity alone is enough",
        Capability.AQUA_SENSOR
        in caps.detect({**REAL_ABSENT, "total_capacity_volume_tank_1": 1109}),
        True,
    )
    check(
        "a second tank in service is detected",
        Capability.SECOND_TANK in caps.detect({**REAL_ABSENT, "unit_status_tank_2": 1}),
        True,
    )
    check(
        "chem feed is detected",
        Capability.CHEM_FEED in caps.detect({**REAL_ABSENT, "chem_feed_mode": 2}),
        True,
    )
    check(
        "external filter is detected",
        Capability.EXTERNAL_FILTER
        in caps.detect({**REAL_ABSENT, "media_life_remaining": 340}),
        True,
    )

    print("\ndegenerate values must not read as present")
    check("empty datapoints", caps.detect({}), set())
    check(
        "the zero-date sentinel is absent",
        caps.detect({"last_regen_date_time_tank_2": "0000-00-00 00:00:00"}),
        set(),
    )
    check(
        "a string zero is absent",
        caps.detect({"chem_feed_mode": "0"}),
        set(),
    )
    check(
        "a string number is present",
        Capability.CHEM_FEED in caps.detect({"chem_feed_mode": "2"}),
        True,
    )
    check(
        "false is absent",
        caps.detect({"aquasensor_auto_rinse_enabled": False}),
        set(),
    )

    print("\nuser overrides")
    check(
        "forcing on adds it",
        Capability.AQUA_SENSOR in caps.resolve(REAL_ABSENT, forced_on=["aqua_sensor"]),
        True,
    )
    check(
        "forcing off removes a detected one",
        Capability.CHEM_FEED
        in caps.resolve({**REAL_ABSENT, "chem_feed_mode": 2}, forced_off=["chem_feed"]),
        False,
    )
    check(
        "off beats on",
        caps.resolve(
            REAL_ABSENT, forced_on=["aqua_sensor"], forced_off=["aqua_sensor"]
        ),
        set(),
    )
    check(
        "an unknown override name is ignored",
        caps.resolve(REAL_ABSENT, forced_on=["not_a_capability"]),
        set(),
    )

    print("\nevidence for diagnostics")
    ev = caps.evidence(REAL_ABSENT)
    check("every group reported", sorted(ev), sorted(c.value for c in Capability))
    check("aqua sensor marked absent", ev["aqua_sensor"]["present"], False)
    check(
        "the readings behind the verdict are included",
        ev["aqua_sensor"]["indicators"]["aquasensor_z_ratio_current_tank_1"],
        0,
    )

    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
