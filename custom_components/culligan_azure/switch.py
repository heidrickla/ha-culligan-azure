"""Switches: away mode and bypass."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    entities: list[SwitchEntity] = []
    for serial in coordinator.data:
        entities.append(CulliganAwayModeSwitch(coordinator, serial))
        entities.append(CulliganBypassSwitch(coordinator, serial))
    async_add_entities(entities)


class CulliganAwayModeSwitch(CulliganEntity, SwitchEntity):
    """Vacation / away mode. Verified: awayMode.set {"active": 0|1}."""

    _attr_name = "Away mode"
    _attr_icon = "mdi:bag-suitcase"

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_away_mode_switch"

    @property
    def is_on(self) -> bool | None:
        v = self.datapoints.get("away_mode")
        return None if v is None else bool(v)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_set_away_mode(self._serial, True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_set_away_mode(self._serial, False)
        )


class CulliganBypassSwitch(CulliganEntity, SwitchEntity):
    """Permanent bypass.

    Bypass is three separate commands rather than one boolean:
      bypass.permanent.on {}          -- no timer
      bypass.timed.on {"duration": N} -- minutes; use the set_bypass_timed service
      bypass.off {}                   -- cancels either
    This switch models permanent-on/off. Timed bypass is a service because a
    duration cannot be expressed through a switch.

    WARNING: while bypassed the house receives UNSOFTENED water.
    """

    _attr_name = "Bypass"
    _attr_icon = "mdi:water-off"

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_bypass_switch"

    @property
    def is_on(self) -> bool | None:
        # actual_state_dealer_bypass is the closest observable bypass indicator.
        # It was 0 throughout testing and no bypass state was captured while
        # active, so treat a missing value as unknown rather than off.
        v = self.datapoints.get("actual_state_dealer_bypass")
        if v is None:
            return None
        return bool(v)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_bypass_permanent(self._serial)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_bypass_off(self._serial)
        )
