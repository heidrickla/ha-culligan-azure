"""Downloadable diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import CulliganConfigEntry

REDACT = {CONF_EMAIL, CONF_PASSWORD, "serial_number", "dsn", "token", "access_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CulliganConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    devices = coordinator.data or {}
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "device_count": len(devices),
        # Serials identify the customer's hardware, so devices are reported by
        # position. The names listed are the DEVICE's telemetry datapoints -
        # the coordinator wrapper keys would say nothing about the hardware.
        "devices": [
            {
                "index": i,
                "connected": entry_data.get("connected"),
                "datapoints": sorted(entry_data.get("datapoints") or {}),
                "datapoint_count": len(entry_data.get("datapoints") or {}),
                "health": async_redact_data(entry_data.get("health") or {}, REDACT),
            }
            for i, entry_data in enumerate(devices.values())
        ],
    }
