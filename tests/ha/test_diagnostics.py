"""What the diagnostics download says, and what it must never say.

Serials identify the customer's hardware, so devices are reported by position
and the credentials are redacted.
"""

from unittest.mock import patch

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from custom_components.culligan_azure.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import DEVICE, EMAIL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"


async def _setup(hass, entry, devices=None):
    entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[DEVICE] if devices is None else devices),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_diagnostics_redact_the_credentials(hass, config_entry):
    await _setup(hass, config_entry)
    data = await async_get_config_entry_diagnostics(hass, config_entry)

    assert data["config"][CONF_EMAIL] != EMAIL
    assert data["config"][CONF_PASSWORD] != "secret"
    assert "secret" not in str(data)


async def test_diagnostics_describe_the_hardware_without_naming_it(hass, config_entry):
    """Both firmware versions, the capability verdicts with the readings
    behind them, and no serial anywhere."""
    device = {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "gbx_firmware_version": "3.14",
            "wifi_module_fw_version": "1.2.3",
        },
    }
    await _setup(hass, config_entry, devices=[device])
    data = await async_get_config_entry_diagnostics(hass, config_entry)

    assert data["device_count"] == 1
    assert data["last_update_success"] is True
    assert data["update_interval"] == "0:02:00"
    section = data["devices"][0]
    assert section["index"] == 0
    assert section["connected"] is True
    assert section["model"] == "GBX"
    assert section["firmware"] == {"controller": "3.14", "wifi_module": "1.2.3"}
    assert section["capabilities"] == []
    assert section["capability_evidence"]["aqua_sensor"]["present"] is False
    assert "days_since_install" in section["datapoints"]
    assert section["datapoint_count"] == len(device["properties"])
    assert "over_regenerating" in section["health"]
    assert DEVICE["serialNumber"] not in str(data)


async def test_diagnostics_survive_a_device_with_no_telemetry(hass, config_entry):
    """Older firmware omits properties entirely; the download must still be
    readable rather than raising halfway through."""
    bare = {"serialNumber": DEVICE["serialNumber"], "name": "Softener"}
    with (
        patch(f"{CLIENT}.async_get_datapoints", return_value={}),
        patch(f"{CLIENT}.async_get_state", return_value={"connected": False}),
    ):
        await _setup(hass, config_entry, devices=[bare])
    data = await async_get_config_entry_diagnostics(hass, config_entry)

    section = data["devices"][0]
    assert section["datapoints"] == []
    assert section["model"] is None
    assert section["firmware"] == {"controller": None, "wifi_module": None}
