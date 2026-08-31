"""Binary sensors — including the health flags that surface a misconfigured unit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capabilities import Capability
from .coordinator import CulliganConfigEntry, CulliganCoordinator
from .discovery import async_add_capability_entities
from .entity import CulliganEntity
from .health import as_number


@dataclass(frozen=True, kw_only=True)
class CulliganBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor with a value extractor over (datapoints, health, entry)."""

    value_fn: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool | None]
    attrs_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    # Hardware this sensor needs. None = always created.
    capability: Capability | None = None


def _fault_state(flags: float | None, days: float | None) -> bool | None:
    if flags is None and days is None:
        return None
    return bool(flags or days)


BINARY_SENSORS: tuple[CulliganBinaryDescription, ...] = (
    CulliganBinaryDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _dp, _h, entry: entry.get("connected"),
    ),
    CulliganBinaryDescription(
        key="away_mode",
        translation_key="away_mode",
        value_fn=lambda dp, _h, _e: (
            None if (v := as_number(dp, "away_mode")) is None else bool(v)
        ),
    ),
    CulliganBinaryDescription(
        key="regenerating",
        translation_key="regenerating",
        # time_rem_in_position counts down only while a cycle is running.
        value_fn=lambda dp, _h, _e: bool(
            isinstance(dp.get("time_rem_in_position"), (int, float))
            and dp["time_rem_in_position"] > 0
        ),
    ),
    CulliganBinaryDescription(
        key="aquasensor_auto_rinse",
        translation_key="aquasensor_auto_rinse",
        entity_category=EntityCategory.DIAGNOSTIC,
        capability=Capability.AQUA_SENSOR,
        value_fn=lambda dp, _h, _e: (
            None
            if (v := as_number(dp, "aquasensor_auto_rinse_enabled")) is None
            else bool(v)
        ),
    ),
    CulliganBinaryDescription(
        key="regen_pending",
        translation_key="regen_pending",
        value_fn=lambda dp, _h, _e: (
            None if (v := as_number(dp, "regen_tonight_pending")) is None else bool(v)
        ),
    ),
    # --- health flags ---
    CulliganBinaryDescription(
        key="over_regenerating",
        translation_key="over_regenerating",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda _dp, h, _e: h.get("over_regenerating"),
        attrs_fn=lambda _dp, h: {
            "actual_days_between_regens": h.get("actual_days_between_regens"),
            "expected_days_between_regens": h.get("expected_days_between_regens"),
            "efficiency_ratio": h.get("regen_efficiency_ratio"),
            "excess_regens_per_year": h.get("excess_regens_per_year"),
            "meaning": (
                "The unit is regenerating far more often than its capacity and "
                "measured usage imply. Usually a hardness, resin-capacity or "
                "flow-meter configuration problem. Costs salt and water."
            ),
        },
    ),
    CulliganBinaryDescription(
        key="has_faults",
        translation_key="has_faults",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Coerced: telemetry values can arrive as strings, and bool("0")
        # is True. Both absent means unknown, not healthy.
        value_fn=lambda dp, _h, _e: _fault_state(
            as_number(dp, "system_error_bit_flags"), as_number(dp, "days_in_error")
        ),
        attrs_fn=lambda dp, h: {
            "system_error_bit_flags": dp.get("system_error_bit_flags"),
            "days_in_error": dp.get("days_in_error"),
            "most_common_code": h.get("most_common_error_code"),
            "most_common_count": h.get("most_common_error_count"),
        },
    ),
    CulliganBinaryDescription(
        key="resin_replacement_due",
        translation_key="resin_replacement_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        # Only fires on a measured, confident trend -- never on assumption, and
        # never while still collecting history.
        value_fn=lambda _dp, h, _e: (
            None
            if (h.get("resin") or {}).get("status")
            not in ("ok", "low_confidence", "at_end_of_life")
            else (
                (h["resin"]["status"] == "at_end_of_life")
                or (
                    isinstance(h["resin"].get("years_remaining"), (int, float))
                    and h["resin"]["years_remaining"] < 1.0
                )
            )
        ),
        attrs_fn=lambda _dp, h: {
            "years_remaining": (h.get("resin") or {}).get("years_remaining"),
            "capacity_fade_percent": (h.get("resin") or {}).get(
                "capacity_fade_percent"
            ),
            "status": (h.get("resin") or {}).get("status"),
            "confidence": (h.get("resin") or {}).get("confidence"),
        },
    ),
    CulliganBinaryDescription(
        key="service_overdue",
        translation_key="service_overdue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _dp, h, _e: h.get("service_overdue"),
    ),
    CulliganBinaryDescription(
        key="clock_wrong",
        translation_key="clock_wrong",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _dp, h, _e: h.get("clock_is_wrong"),
        attrs_fn=lambda dp, _h: {
            "last_power_up_time": dp.get("last_power_up_time"),
            "meaning": (
                "The valve controller keeps its own clock, separate from the "
                "wifi module's NTP-synced one, and nothing syncs it. If this is "
                "on, call the culligan_azure.set_clock service."
            ),
        },
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

    def _build(serial: str, caps: set[str]) -> list[CulliganBinarySensor]:
        # None stands for "needs no capability", so the ungated entities are
        # built exactly once - with the empty group.
        wanted: set[str | None] = set(caps) if caps else {None}
        return [
            CulliganBinarySensor(coordinator, serial, desc)
            for desc in BINARY_SENSORS
            if (desc.capability.value if desc.capability else None) in wanted
        ]

    async_add_capability_entities(entry, coordinator, async_add_entities, _build)


class CulliganBinarySensor(CulliganEntity, BinarySensorEntity):
    """A boolean state or health flag."""

    entity_description: CulliganBinaryDescription

    def __init__(
        self,
        coordinator: CulliganCoordinator,
        serial: str,
        description: CulliganBinaryDescription,
    ) -> None:
        super().__init__(coordinator, serial)
        self.entity_description = description
        self._attr_unique_id = f"{serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        try:
            return self.entity_description.value_fn(
                self.datapoints, self.health, self._entry
            )
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
