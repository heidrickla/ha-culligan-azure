"""Culligan (Azure-backed) integration.

Talks to uniapi.culliganiot.com, the same API the Culligan Connect app uses.
This is NOT the Ayla backend the existing community integration targets --
newer Culligan hardware was migrated to Azure IoT and cannot use it.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import CulliganApiClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import CulliganCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

SERVICE_BYPASS_TIMED = "bypass_timed"
SERVICE_SET_CLOCK = "set_clock"

BYPASS_TIMED_SCHEMA = vol.Schema(
    {
        vol.Required("serial_number"): cv.string,
        vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
    }
)

SET_CLOCK_SCHEMA = vol.Schema({vol.Required("serial_number"): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    session = async_get_clientsession(hass)
    client = CulliganApiClient(
        session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )

    scan_interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    coordinator = CulliganCoordinator(hass, entry, client, scan_interval)
    # Resin history must be loaded before the first poll, or that poll's sample
    # would be appended to an empty list and the baseline lost on every restart.
    await coordinator.async_load_history()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register services once, not per config entry."""

    def _find_coordinator(serial: str) -> CulliganCoordinator:
        for coord in hass.data.get(DOMAIN, {}).values():
            if isinstance(coord, CulliganCoordinator) and serial in (coord.data or {}):
                return coord
        raise vol.Invalid(f"no configured Culligan device with serial {serial}")

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

    if not hass.services.has_service(DOMAIN, SERVICE_BYPASS_TIMED):
        hass.services.async_register(
            DOMAIN, SERVICE_BYPASS_TIMED, _bypass_timed, schema=BYPASS_TIMED_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_CLOCK):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_CLOCK, _set_clock, schema=SET_CLOCK_SCHEMA
        )


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_BYPASS_TIMED)
            hass.services.async_remove(DOMAIN, SERVICE_SET_CLOCK)
    return unloaded
