"""Buttons: regeneration, telemetry refresh, clock sync."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CulliganCoordinator
from .entity import CulliganEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CulliganCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []
    for serial in coordinator.data:
        entities.append(CulliganRegenNowButton(coordinator, serial))
        entities.append(CulliganRegenScheduledButton(coordinator, serial))
        entities.append(CulliganRefreshButton(coordinator, serial))
        entities.append(CulliganSetClockButton(coordinator, serial))
    async_add_entities(entities)


class CulliganRegenNowButton(CulliganEntity, ButtonEntity):
    """Start a regeneration immediately.

    Verified: regen.set {"type": 1} -> last_regen_trigger 10, cycle starts.
    Consumes salt and backwash water, so this is not a free action.
    """

    _attr_name = "Regenerate now"
    _attr_icon = "mdi:autorenew"

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_regen_now"

    async def async_press(self) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_regenerate(self._serial, immediate=True)
        )


class CulliganRegenScheduledButton(CulliganEntity, ButtonEntity):
    """Schedule a regeneration for the next cycle time.

    Verified: regen.set {"type": 2} -> last_regen_trigger 11.
    """

    _attr_name = "Schedule regeneration"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_regen_scheduled"

    async def async_press(self) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_regenerate(self._serial, immediate=False)
        )


class CulliganRefreshButton(CulliganEntity, ButtonEntity):
    """Ask the device to push fresh telemetry, then re-poll."""

    _attr_name = "Refresh telemetry"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_refresh_telemetry(self._serial)
        )


class CulliganSetClockButton(CulliganEntity, ButtonEntity):
    """Set the controller clock to Home Assistant's local time.

    The valve controller keeps a clock separate from the wifi module's
    NTP-synced one, and nothing syncs it -- it can drift years behind without
    any alert, and the app exposes no way to correct it.

    NOTE: the change is not observable until the device next powers up, because
    no datapoint reports the current controller time.
    """

    _attr_name = "Sync controller clock"
    _attr_icon = "mdi:clock-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_set_clock"

    async def async_press(self) -> None:
        await self.coordinator.async_send_and_refresh(
            self.coordinator.client.async_set_datetime(self._serial)
        )
