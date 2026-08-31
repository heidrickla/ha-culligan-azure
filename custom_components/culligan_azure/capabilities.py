"""What this particular softener actually has fitted.

A GBX controller reports the same ~180 datapoints whatever accessories are
installed; the ones for absent hardware simply read zero. Creating an entity
for every one of them gives a page of permanent zeros - and worse, figures
DERIVED from them go wrong rather than absent. On the unit this was built
against, which has no Aqua-Sensor, `total_capacity_volume_tank_1` is 0 and so
`capacity_remaining_tank_1` reads **-515 gallons**. A number that confident and
that wrong is worse than no entity at all.

WHAT THE AQUA-SENSOR IS. On Culligan units it measures conductivity in the
resin bed and computes the working capacity from it, replacing the programmed
influent-hardness figure. So a unit either determines capacity by Aqua-Sensor
or by `hardness_value` - and which one it is decides whether a whole family of
capacity datapoints means anything.

DETECTION RULE, and its one honest limit: a capability counts as present when
ANY of its datapoints is present and non-zero. That direction is safe - a
sensor reporting real values can never be hidden by it. The reverse is not
provable from here: this house's softener has no Aqua-Sensor, so every reading
below is a NEGATIVE example and no positive control was available. A unit that
has the sensor but happens to read exactly zero everywhere would be treated as
not having it, until the first non-zero reading brings the entities in (the
platforms re-check on every poll). The options flow can override either way for
anyone whose unit the rule gets wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    """A piece of hardware that may or may not be fitted."""

    AQUA_SENSOR = "aqua_sensor"
    SECOND_TANK = "second_tank"
    CHEM_FEED = "chem_feed"
    EXTERNAL_FILTER = "external_filter"


# Datapoints that only carry a non-zero value when the hardware is there.
# Deliberately NOT including anything whose zero is a legitimate reading on a
# fitted unit (a full tank at rest, a filter with no alarm set).
_INDICATORS: dict[Capability, tuple[str, ...]] = {
    Capability.AQUA_SENSOR: (
        "aquasensor_z_ratio_current_tank_1",
        "aquasensor_z_ratio_current_tank_2",
        "aquasensor_z_min_tank_1",
        "aquasensor_z_min_tank_2",
        "aquasensor_auto_rinse_enabled",
        # Capacity the controller derived from the sensor. Zero on a unit that
        # works from the programmed hardness figure instead.
        "total_capacity_volume_tank_1",
        "total_capacity_volume_tank_2",
    ),
    Capability.SECOND_TANK: (
        "unit_status_tank_2",
        "total_water_usage_since_install_tank_2",
        "capacity_remaining_tank_2",
        "days_since_last_regen_tank_2",
    ),
    Capability.CHEM_FEED: (
        "chem_feed_mode",
        "chem_feed_capacity_remaining",
        "chem_feed_alarm_capacity",
    ),
    Capability.EXTERNAL_FILTER: (
        "external_filter_mode",
        "external_filter_capacity_remaining",
        "external_filter_alarm_capacity",
        "filter_media_life",
        "media_life_remaining",
    ),
}


def _is_meaningful(value: Any) -> bool:
    """True when a datapoint carries something other than a zero/blank.

    Strings are included because this API returns numbers as strings on some
    fields, and a date sentinel of `0000-00-00 00:00:00` must read as absent.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip()
        if not text or text.startswith("0000-00-00"):
            return False
        try:
            return float(text) != 0.0
        except ValueError:
            return True  # a non-numeric string is real content
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def detect(datapoints: dict[str, Any]) -> set[Capability]:
    """Which capabilities this device's telemetry shows evidence of."""
    found: set[Capability] = set()
    for capability, keys in _INDICATORS.items():
        if any(_is_meaningful(datapoints.get(key)) for key in keys):
            found.add(capability)
    return found


def evidence(datapoints: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per capability, the datapoints looked at and what they read.

    Surfaced in diagnostics so a wrong verdict can be argued with from the
    actual numbers rather than guessed at.
    """
    return {
        capability.value: {
            "present": capability in detect(datapoints),
            "indicators": {
                key: datapoints.get(key) for key in keys if key in datapoints
            },
        }
        for capability, keys in _INDICATORS.items()
    }


def resolve(
    datapoints: dict[str, Any],
    forced_on: Iterable[str] = (),
    forced_off: Iterable[str] = (),
) -> set[Capability]:
    """Detection, with the user's overrides applied.

    `forced_off` wins over `forced_on`: turning something off is the explicit
    request to stop seeing it, and should not be undone by a stale include.
    """
    on = {c for c in Capability if c.value in set(forced_on)}
    off = {c for c in Capability if c.value in set(forced_off)}
    return (detect(datapoints) | on) - off
