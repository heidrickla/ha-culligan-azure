"""Downloadable diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import capabilities
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
            _device_section(i, entry_data)
            for i, entry_data in enumerate(devices.values())
        ],
    }


def _device_section(index: int, entry_data: dict[str, Any]) -> dict[str, Any]:
    datapoints: dict[str, Any] = entry_data.get("datapoints") or {}
    device: dict[str, Any] = entry_data.get("device") or {}
    return {
        "index": index,
        "connected": entry_data.get("connected"),
        "model": device.get("model") or datapoints.get("unit_type"),
        "firmware": {
            "controller": datapoints.get("gbx_firmware_version"),
            "wifi_module": datapoints.get("wifi_module_fw_version"),
        },
        "capabilities": sorted(entry_data.get("capabilities") or set()),
        # The indicator readings behind each capability verdict, so a wrong
        # verdict can be argued with from the numbers.
        "capability_evidence": capabilities.evidence(datapoints),
        "datapoints": sorted(datapoints),
        "datapoint_count": len(datapoints),
        "health": async_redact_data(entry_data.get("health") or {}, REDACT),
    }
