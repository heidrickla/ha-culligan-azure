"""Number entity: salt level."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CulliganCoordinator
from .entity import CulliganEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CulliganCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CulliganSaltLevelNumber(coordinator, serial) for serial in coordinator.data
    )


class CulliganSaltLevelNumber(CulliganEntity, NumberEntity):
    """Tell the softener how full the salt tank is, after a refill.

    Verified: salt.set {"level": N}. The app only ever offers 25/50/75/100, so
    intermediate values are accepted by the API but unproven on the device --
    hence the step of 25 rather than 1.

    This is an input, not a measurement: the unit has no salt sensor on this
    model and simply counts down from whatever you tell it.
    """

    _attr_name = "Salt level"
    _attr_icon = "mdi:shaker-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 25
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_salt_level_set"

    @property
    def native_value(self) -> float | None:
        v = self.datapoints.get("manual_salt_level_rem_calc")
        return float(v) if isinstance(v, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_set_salt_level(self._serial, int(value))
        )
