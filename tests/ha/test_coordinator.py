"""Poll-time behaviour that no single entity shows: the connection fallback,
the resin history store, and what unloading writes.
"""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState

from custom_components.culligan_azure.api import CulliganError
from custom_components.culligan_azure.coordinator import STORAGE_KEY

from .conftest import DEVICE, SERIAL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"
STATE = f"{CLIENT}.async_get_state"

# The registry entry with the connection flag stripped, which is the case the
# per-device /device/state call exists for.
NO_STATUS = {k: v for k, v in DEVICE.items() if k != "status"}


async def test_the_connection_flag_falls_back_to_the_state_call(hass, config_entry):
    """registry reports `online` less reliably than /device/state, so a
    missing flag is asked for rather than assumed."""
    config_entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[NO_STATUS]),
        patch(STATE, return_value={"connected": True}) as state,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    state.assert_awaited_with(SERIAL)
    assert hass.states.get("binary_sensor.softener_connected").state == "on"


async def test_a_failing_state_call_leaves_the_connection_unknown(hass, config_entry):
    """The rest of the poll succeeded; one missing flag must not fail it."""
    config_entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[NO_STATUS]),
        patch(STATE, side_effect=CulliganError("HTTP 502")),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.softener_connected").state == "unknown"


async def test_the_resin_history_is_written_and_read_back(
    hass, config_entry, hass_storage
):
    """The baseline is the whole point of the estimate: losing it on every
    restart would reset the measurement to nothing."""
    device = {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "total_water_usage_since_install_tank_1": 182179,
            "total_regens_since_install": 749,
        },
    }
    config_entry.add_to_hass(hass)
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    key = f"{STORAGE_KEY}_{config_entry.entry_id}"
    stored = hass_storage[key]["data"]
    assert len(stored[SERIAL]) == 1
    assert stored[SERIAL][0]["gallons"] == 182179
    assert stored[SERIAL][0]["regens"] == 749

    # A fresh setup must read that sample back rather than starting empty.
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    assert coordinator._resin_history[SERIAL][0]["gallons"] == 182179


async def test_a_second_sample_is_not_taken_on_the_next_poll(hass, config_entry):
    """Resin fade is a multi-month signal; sampling every poll would fill the
    store with noise."""
    device = {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "total_water_usage_since_install_tank_1": 182179,
            "total_regens_since_install": 749,
        },
    }
    config_entry.add_to_hass(hass)
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert len(config_entry.runtime_data._resin_history[SERIAL]) == 1


async def test_a_device_with_no_serial_is_skipped(hass, config_entry):
    """Nothing can be keyed on a device with no serial number."""
    config_entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[{"name": "Nameless"}, DEVICE]),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert set(config_entry.runtime_data.data) == {SERIAL}
