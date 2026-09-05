"""Sensors for Culligan softeners: raw telemetry plus derived health metrics."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .capabilities import Capability
from .coordinator import CulliganConfigEntry, CulliganCoordinator
from .discovery import async_add_capability_entities
from .entity import CulliganEntity

GALLONS = UnitOfVolume.GALLONS


@dataclass(frozen=True, kw_only=True)
class CulliganSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    # Hardware this sensor needs. None = always created.
    capability: Capability | None = None


def _dp(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    return lambda dp, _h: dp.get(key)


def _hl(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    """Fetch a derived health value. Display rounding is the description's
    suggested_display_precision; the recorded state keeps full precision."""
    return lambda _dp, h: h.get(key)


def _parse_dt(value: Any) -> datetime.datetime | None:
    """Parse the device's 'YYYY-MM-DD HH:MM:SS' stamps.

    These are written by the CONTROLLER clock, which is separate from the wifi
    module's NTP-synced clock and can be years out. Zero/sentinel values are
    common. Returns None rather than a nonsense datetime.
    """
    if not isinstance(value, str) or value.startswith("0000"):
        return None
    try:
        # The device emits no timezone at all, so %z is impossible here.
        naive = datetime.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    # The controller keeps local wall-clock time (async_set_datetime writes
    # local time back to it), so stamp the household timezone. Stamping UTC
    # shifted every timestamp sensor by the UTC offset.
    return naive.replace(tzinfo=dt_util.get_default_time_zone())


def _dp_dt(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    return lambda dp, _h: _parse_dt(dp.get(key))


SENSORS: tuple[CulliganSensorDescription, ...] = (
    # --- water ---
    CulliganSensorDescription(
        key="current_flow_rate",
        translation_key="current_flow_rate",
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("current_flow_rate"),
    ),
    CulliganSensorDescription(
        key="water_today",
        translation_key="water_today",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_dp("total_water_usage_today_tank_1"),
    ),
    CulliganSensorDescription(
        key="water_lifetime",
        translation_key="water_lifetime",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("total_water_usage_since_install_tank_1"),
    ),
    CulliganSensorDescription(
        key="average_daily_use",
        translation_key="average_daily_use",
        native_unit_of_measurement=GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        # No volume device class fits: this is gallons PER DAY, and both VOLUME
        # and VOLUME_STORAGE would declare it a volume standing still. Claiming
        # one for the unit conversion alone would make the state say something
        # it does not mean.
        value_fn=_dp("average_daily_use"),
    ),
    CulliganSensorDescription(
        key="capacity_remaining",
        translation_key="capacity_remaining",
        native_unit_of_measurement=GALLONS,
        # VOLUME_STORAGE, not VOLUME: this is a volume that stands still and
        # depletes, and VOLUME accepts only the total state classes.
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # Counts down from the Aqua-Sensor's derived working capacity. On a
        # unit without the sensor that base is 0 and this reads NEGATIVE
        # (-515 gal on the unit this was built against), so it is gated
        # rather than shown as a confident wrong number.
        capability=Capability.AQUA_SENSOR,
        value_fn=_dp("capacity_remaining_tank_1"),
    ),
    # --- Aqua-Sensor, only on units that have one ---
    # The raw conductivity figures are for arguing with the detector, not for
    # a dashboard, so they are registered disabled.
    CulliganSensorDescription(
        key="aquasensor_ratio",
        translation_key="aquasensor_ratio",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        capability=Capability.AQUA_SENSOR,
        suggested_display_precision=2,
        value_fn=_dp("aquasensor_z_ratio_current_tank_1"),
    ),
    CulliganSensorDescription(
        key="aquasensor_minimum",
        translation_key="aquasensor_minimum",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        capability=Capability.AQUA_SENSOR,
        suggested_display_precision=2,
        value_fn=_dp("aquasensor_z_min_tank_1"),
    ),
    CulliganSensorDescription(
        key="working_capacity",
        translation_key="working_capacity",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # The capacity the controller derived from the sensor, which is what
        # replaces the programmed hardness figure on an Aqua-Sensor unit.
        capability=Capability.AQUA_SENSOR,
        value_fn=_dp("total_capacity_volume_tank_1"),
    ),
    # --- salt ---
    CulliganSensorDescription(
        key="salt_level",
        translation_key="salt_level",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("manual_salt_level_rem_calc"),
    ),
    CulliganSensorDescription(
        key="days_salt_remaining",
        translation_key="days_salt_remaining",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("days_salt_remaining"),
    ),
    # --- regeneration ---
    CulliganSensorDescription(
        key="regen_time_remaining",
        translation_key="regen_time_remaining",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("time_rem_in_position"),
    ),
    CulliganSensorDescription(
        key="days_since_last_regen",
        translation_key="days_since_last_regen",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("days_since_last_regen_tank_1"),
    ),
    CulliganSensorDescription(
        key="last_regen",
        translation_key="last_regen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_dp_dt("last_regen_date_time_tank_1"),
    ),
    CulliganSensorDescription(
        key="next_regen",
        translation_key="next_regen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_dp_dt("next_regen_date_time"),
    ),
    CulliganSensorDescription(
        key="regens_lifetime",
        translation_key="regens_lifetime",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Also an attribute of Resin cycle age; a counter in the hundreds that
        # moves once a day is registry noise for most people.
        entity_registry_enabled_default=False,
        value_fn=_dp("total_regens_since_install"),
    ),
    # --- DERIVED HEALTH METRICS ---
    # These are the point of the integration: the raw values look fine in
    # isolation, and only their ratios reveal a misconfigured unit.
    CulliganSensorDescription(
        key="actual_regen_interval",
        translation_key="actual_regen_interval",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_hl("actual_days_between_regens"),
    ),
    CulliganSensorDescription(
        key="expected_regen_interval",
        translation_key="expected_regen_interval",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_hl("expected_days_between_regens"),
    ),
    CulliganSensorDescription(
        key="regen_efficiency",
        translation_key="regen_efficiency",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda _dp, h: (
            h["regen_efficiency_ratio"] * 100
            if isinstance(h.get("regen_efficiency_ratio"), (int, float))
            else None
        ),
        attrs_fn=lambda _dp, h: {
            "actual_days_between_regens": h.get("actual_days_between_regens"),
            "expected_days_between_regens": h.get("expected_days_between_regens"),
        },
    ),
    CulliganSensorDescription(
        key="excess_regens_per_year",
        translation_key="excess_regens_per_year",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_hl("excess_regens_per_year"),
    ),
    # --- resin condition, measured over time ---
    # These stay unavailable until enough history accumulates. That is
    # deliberate: an estimate from three days of data would be fiction.
    CulliganSensorDescription(
        key="resin_life_remaining",
        translation_key="resin_life_remaining",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("years_remaining"),
        # `status` says why a reading is unavailable; the README explains the
        # method and the status values.
        attrs_fn=lambda _dp, h: {
            k: (h.get("resin") or {}).get(k)
            for k in (
                "status",
                "samples",
                "windows",
                "span_days",
                "baseline_capacity",
                "current_capacity",
                "fade_per_year",
                "confidence",
            )
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_fade",
        translation_key="resin_capacity_fade",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("capacity_fade_percent"),
        attrs_fn=lambda _dp, h: {
            "baseline_capacity": (h.get("resin") or {}).get("baseline_capacity"),
            "current_capacity": (h.get("resin") or {}).get("current_capacity"),
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_current",
        translation_key="resin_capacity_current",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("current_capacity"),
    ),
    CulliganSensorDescription(
        key="resin_cycle_age",
        translation_key="resin_cycle_age",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda _dp, h: (
            h["resin_cycle_age_years"]
            if isinstance(h.get("resin_cycle_age_years"), (int, float))
            else None
        ),
        attrs_fn=lambda dp, h: {
            "calendar_age_years": (
                round(dp["days_since_install"] / 365.25, 1)
                if isinstance(dp.get("days_since_install"), (int, float))
                else None
            ),
            "acceleration_factor": (
                round(h["resin_cycle_acceleration"], 1)
                if isinstance(h.get("resin_cycle_acceleration"), (int, float))
                else None
            ),
            "excess_cycles_lifetime": (
                round(h["resin_excess_cycles"])
                if isinstance(h.get("resin_excess_cycles"), (int, float))
                else None
            ),
            "total_regens": dp.get("total_regens_since_install"),
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_lifetime",
        translation_key="resin_capacity_lifetime",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # A lifetime average that barely moves; the windowed figure above is
        # the one worth watching.
        entity_registry_enabled_default=False,
        value_fn=lambda _dp, h: (
            round(h["resin_lifetime_capacity"], 1)
            if isinstance(h.get("resin_lifetime_capacity"), (int, float))
            else None
        ),
    ),
    # --- diagnostics ---
    CulliganSensorDescription(
        key="error_count",
        translation_key="error_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_hl("error_count"),
        attrs_fn=lambda dp, h: {
            "most_common_code": h.get("most_common_error_code"),
            "most_common_count": h.get("most_common_error_count"),
            "last_error": h.get("last_error"),
            "log": dp.get("errors"),
        },
    ),
    CulliganSensorDescription(
        key="days_since_service",
        translation_key="days_since_service",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("days_since_last_service"),
    ),
    CulliganSensorDescription(
        key="hardness",
        translation_key="hardness",
        native_unit_of_measurement="gpg",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("hardness_value"),
    ),
    CulliganSensorDescription(
        key="rssi",
        translation_key="rssi",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Noisy and rarely wanted; the quality scale's own example of an
        # entity to register disabled.
        entity_registry_enabled_default=False,
        value_fn=_dp("rssi"),
    ),
    CulliganSensorDescription(
        key="last_power_up",
        translation_key="last_power_up",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Its job is done by the Controller clock wrong sensor, which carries
        # the raw stamp as an attribute.
        entity_registry_enabled_default=False,
        value_fn=_dp_dt("last_power_up_time"),
    ),
)


# One coordinator polls; entities do no I/O of their own.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulliganConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    def _build(serial: str, caps: set[str]) -> list[CulliganSensor]:
        """Sensors for one capability group - or the ungated ones when empty."""
        # None stands for "needs no capability", so the ungated entities are
        # built exactly once - with the empty group.
        wanted: set[str | None] = set(caps) if caps else {None}
        return [
            CulliganSensor(coordinator, serial, desc)
            for desc in SENSORS
            if (desc.capability.value if desc.capability else None) in wanted
        ]

    async_add_capability_entities(entry, coordinator, async_add_entities, _build)


class CulliganSensor(CulliganEntity, SensorEntity):
    """A single telemetry or derived value."""

    entity_description: CulliganSensorDescription

    def __init__(
        self,
        coordinator: CulliganCoordinator,
        serial: str,
        description: CulliganSensorDescription,
    ) -> None:
        super().__init__(coordinator, serial)
        self.entity_description = description
        self._attr_unique_id = f"{serial}_{description.key}"

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self.datapoints, self.health)
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        try:
            return self.entity_description.attrs_fn(self.datapoints, self.health)
        except (KeyError, TypeError, ValueError):
            return None
