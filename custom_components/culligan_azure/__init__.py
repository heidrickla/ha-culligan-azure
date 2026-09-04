"""Culligan (Azure-backed) integration.

Talks to uniapi.culliganiot.com, the same API the Culligan Connect app uses.
This is NOT the Ayla backend the existing community integration targets --
newer Culligan hardware was migrated to Azure IoT and cannot use it.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import CulliganApiClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_BYPASS_TIMED,
    SERVICE_SET_CLOCK,
)
from .coordinator import (
    STORAGE_KEY,
    STORAGE_VERSION,
    CulliganConfigEntry,
    CulliganCoordinator,
)
from .discovery import async_remove_stale_devices

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

BYPASS_TIMED_SCHEMA = vol.Schema(
    {
        vol.Required("serial_number"): cv.string,
        vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
    }
)

SET_CLOCK_SCHEMA = vol.Schema({vol.Required("serial_number"): cv.string})

# Config-entry only. A stray YAML block then raises the standard repair
# issue instead of being silently ignored.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services at component setup.

    Registered per entry they disappear while the entry is unloaded, and an
    automation calling one then fails validation as though it were a typo.
    """
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CulliganConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_get_clientsession(hass)
    client = CulliganApiClient(
        session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = CulliganCoordinator(hass, entry, client, scan_interval)
    # Resin history must be loaded before the first poll, or that poll's sample
    # would be appended to an empty list and the baseline lost on every restart.
    await coordinator.async_load_history()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    async_remove_stale_devices(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_remove_entry(hass: HomeAssistant, entry: CulliganConfigEntry) -> None:
    """Delete the entry's resin-history store file with the entry.

    The store is keyed per entry_id, so without this every removed account
    leaves an orphaned file in .storage forever.
    """
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}"
    )
    await store.async_remove()


def _register_services(hass: HomeAssistant) -> None:
    """Register services once, not per config entry."""

    def _find_coordinator(serial: str) -> CulliganCoordinator:
        entries: list[CulliganConfigEntry] = hass.config_entries.async_loaded_entries(
            DOMAIN
        )
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )
        for entry in entries:
            coord: CulliganCoordinator = entry.runtime_data
            if serial in (coord.data or {}):
                return coord
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_serial",
            translation_placeholders={"serial": serial},
        )

    async def _bypass_timed(call: ServiceCall) -> None:
        """Bypass for a fixed number of minutes.

        Exposed as a service rather than an entity because a duration cannot be
        expressed through a switch. The app offers 30/60/90/120/180; other
        values are accepted by the API but unverified on hardware.
        """
        serial = call.data["serial_number"]
        coord = _find_coordinator(serial)
        await coord.async_send_and_refresh(
            coord.client.async_bypass_timed(serial, call.data["duration"])
        )

    async def _set_clock(call: ServiceCall) -> None:
        serial = call.data["serial_number"]
        coord = _find_coordinator(serial)
        await coord.async_send_and_refresh(
            coord.client.async_set_datetime(serial, dt_util.now())
        )

    hass.services.async_register(
        DOMAIN, SERVICE_BYPASS_TIMED, _bypass_timed, schema=BYPASS_TIMED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLOCK, _set_clock, schema=SET_CLOCK_SCHEMA
    )


async def _async_reload_entry(hass: HomeAssistant, entry: CulliganConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CulliganConfigEntry) -> bool:
    """Unload a config entry.

    Services stay registered: they belong to the component, not the entry, and
    refuse with a translated error while nothing is loaded.
    """
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_flush_history()
    return unloaded
