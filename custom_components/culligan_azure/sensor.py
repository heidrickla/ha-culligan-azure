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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CulliganCoordinator
from .entity import CulliganEntity

GALLONS = UnitOfVolume.GALLONS


@dataclass(frozen=True, kw_only=True)
class CulliganSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None


def _dp(key: str) -> Callable[[dict, dict], Any]:
    return lambda dp, _h: dp.get(key)


def _hl(key: str, ndigits: int | None = None) -> Callable[[dict, dict], Any]:
    def _get(_dp: dict, h: dict) -> Any:
        v = h.get(key)
        if ndigits is not None and isinstance(v, (int, float)):
            return round(v, ndigits)
        return v

    return _get


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
        # Parsed naive, then stamped UTC on the next line.
        naive = datetime.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
    except (ValueError, TypeError):
        return None
    return naive.replace(tzinfo=datetime.timezone.utc)


def _dp_dt(key: str) -> Callable[[dict, dict], Any]:
    return lambda dp, _h: _parse_dt(dp.get(key))


SENSORS: tuple[CulliganSensorDescription, ...] = (
    # --- water ---
    CulliganSensorDescription(
        key="current_flow_rate",
        translation_key="current_flow_rate",
        name="Current flow rate",
        native_unit_of_measurement="gal/min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water",
        value_fn=_dp("current_flow_rate"),
    ),
    CulliganSensorDescription(
        key="water_today",
        name="Water used today",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_dp("total_water_usage_today_tank_1"),
    ),
    CulliganSensorDescription(
        key="water_lifetime",
        name="Water used lifetime",
        native_unit_of_measurement=GALLONS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("total_water_usage_since_install_tank_1"),
    ),
    CulliganSensorDescription(
        key="average_daily_use",
        name="Average daily use",
        native_unit_of_measurement=GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("average_daily_use"),
    ),
    CulliganSensorDescription(
        key="capacity_remaining",
        name="Capacity remaining",
        native_unit_of_measurement=GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=_dp("capacity_remaining_tank_1"),
    ),
    # --- salt ---
    CulliganSensorDescription(
        key="salt_level",
        name="Salt level",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:shaker-outline",
        value_fn=_dp("manual_salt_level_rem_calc"),
    ),
    CulliganSensorDescription(
        key="days_salt_remaining",
        name="Salt days remaining",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-clock",
        value_fn=_dp("days_salt_remaining"),
    ),
    # --- regeneration ---
    CulliganSensorDescription(
        key="regen_time_remaining",
        name="Regeneration time remaining",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:progress-clock",
        value_fn=_dp("time_rem_in_position"),
    ),
    CulliganSensorDescription(
        key="days_since_last_regen",
        name="Days since last regeneration",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_dp("days_since_last_regen_tank_1"),
    ),
    CulliganSensorDescription(
        key="last_regen",
        name="Last regeneration",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_dp_dt("last_regen_date_time_tank_1"),
    ),
    CulliganSensorDescription(
        key="next_regen",
        name="Next regeneration",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_dp_dt("next_regen_date_time"),
    ),
    CulliganSensorDescription(
        key="regens_lifetime",
        name="Regenerations lifetime",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("total_regens_since_install"),
    ),
    # --- DERIVED HEALTH METRICS ---
    # These are the point of the integration: the raw values look fine in
    # isolation, and only their ratios reveal a misconfigured unit.
    CulliganSensorDescription(
        key="actual_regen_interval",
        name="Regeneration interval (actual)",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-refresh",
        value_fn=_hl("actual_days_between_regens", 2),
    ),
    CulliganSensorDescription(
        key="expected_regen_interval",
        name="Regeneration interval (expected)",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-check",
        value_fn=_hl("expected_days_between_regens", 2),
    ),
    CulliganSensorDescription(
        key="regen_efficiency",
        name="Regeneration efficiency",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:leaf",
        value_fn=lambda _dp, h: (
            round(h["regen_efficiency_ratio"] * 100, 1)
            if isinstance(h.get("regen_efficiency_ratio"), (int, float))
            else None
        ),
        attrs_fn=lambda _dp, h: {
            "actual_days_between_regens": h.get("actual_days_between_regens"),
            "expected_days_between_regens": h.get("expected_days_between_regens"),
            "interpretation": (
                "100% = regenerating exactly as often as capacity implies; "
                "below 100% = regenerating more often than needed, wasting "
                "salt and backwash water"
            ),
        },
    ),
    CulliganSensorDescription(
        key="excess_regens_per_year",
        name="Excess regenerations per year",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-decagram-outline",
        value_fn=_hl("excess_regens_per_year", 0),
        attrs_fn=lambda _dp, h: {
            "note": (
                "Regenerations beyond what capacity and usage imply. Multiply "
                "by your salt dose and backwash volume per cycle to estimate "
                "annual waste."
            )
        },
    ),
    # --- resin condition, measured over time ---
    # These stay unavailable until enough history accumulates. That is
    # deliberate: an estimate from three days of data would be fiction.
    CulliganSensorDescription(
        key="resin_life_remaining",
        name="Resin life remaining",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:hourglass-bottom",
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("years_remaining"),
        attrs_fn=lambda _dp, h: {
            **{
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
            "method": (
                "Measured, not assumed. Windowed gallons-per-regeneration is "
                "tracked over time and the decline extrapolated to 60% of the "
                "observed baseline. Needs ~3 weeks of history before it reports; "
                "accuracy improves for months afterwards. `status` explains any "
                "unavailable reading."
            ),
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_fade",
        name="Resin capacity fade",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line-variant",
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("capacity_fade_percent"),
        attrs_fn=lambda _dp, h: {
            "baseline_capacity": (h.get("resin") or {}).get("baseline_capacity"),
            "current_capacity": (h.get("resin") or {}).get("current_capacity"),
            "note": "Percent drop in gallons treated per regeneration since tracking began.",
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_current",
        name="Capacity per regeneration",
        native_unit_of_measurement=GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cup-water",
        value_fn=lambda _dp, h: (h.get("resin") or {}).get("current_capacity"),
    ),
    CulliganSensorDescription(
        key="resin_cycle_age",
        name="Resin cycle age",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-account",
        value_fn=lambda _dp, h: (
            round(h["resin_cycle_age_years"], 1)
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
            "interpretation": (
                "Years of NORMAL cycling the resin has experienced, from "
                "regeneration count alone. Compare with calendar age: a higher "
                "value means the resin is being cycled harder than it should be. "
                "This covers osmotic shock and backwash attrition only -- "
                "oxidation by chlorine scales with treated VOLUME, which "
                "regeneration frequency does not change. So this is an upper "
                "bound on accelerated ageing, not a total."
            ),
        },
    ),
    CulliganSensorDescription(
        key="resin_capacity_lifetime",
        name="Capacity per regeneration (lifetime avg)",
        native_unit_of_measurement=GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:cup-water",
        value_fn=lambda _dp, h: (
            round(h["resin_lifetime_capacity"], 1)
            if isinstance(h.get("resin_lifetime_capacity"), (int, float))
            else None
        ),
    ),
    # --- diagnostics ---
    CulliganSensorDescription(
        key="error_count",
        name="Fault log entries",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
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
        name="Days since service",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("days_since_last_service"),
    ),
    CulliganSensorDescription(
        key="hardness",
        name="Hardness setting",
        native_unit_of_measurement="gpg",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:water-percent",
        value_fn=_dp("hardness_value"),
    ),
    CulliganSensorDescription(
        key="rssi",
        name="Wi-Fi signal",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp("rssi"),
    ),
    CulliganSensorDescription(
        key="last_power_up",
        name="Last power up",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_dp_dt("last_power_up_time"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CulliganCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CulliganSensor(coordinator, serial, desc)
        for serial in coordinator.data
        for desc in SENSORS
    )


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
