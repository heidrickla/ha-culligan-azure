"""Setup, teardown, services, and what a failing poll does to the entry."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.culligan_azure.api import CulliganAuthError, CulliganError
from custom_components.culligan_azure.const import DOMAIN

from .conftest import DEVICE, SERIAL

LOGIN = "custom_components.culligan_azure.api.CulliganApiClient.async_login"
DEVICES = "custom_components.culligan_azure.api.CulliganApiClient.async_get_devices"
BYPASS = "custom_components.culligan_azure.api.CulliganApiClient.async_bypass_timed"


async def _setup(hass, entry, devices=None, side_effect=None):
    entry.add_to_hass(hass)
    kwargs = (
        {"side_effect": side_effect}
        if side_effect
        else {"return_value": [DEVICE] if devices is None else devices}
    )
    with patch(LOGIN, return_value=None), patch(DEVICES, **kwargs):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_creates_the_device_and_its_entities(hass, config_entry):
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None
    assert device.name == "Softener"
    assert device.serial_number == SERIAL

    entities = [e for e in hass.states.async_entity_ids() if "softener" in e]
    assert entities, "the softener produced no entities"


async def test_a_failing_poll_leaves_the_entry_retrying(hass, config_entry):
    await _setup(hass, config_entry, side_effect=CulliganError("gateway timeout"))
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_credentials_start_a_reauth_flow(hass, config_entry):
    await _setup(hass, config_entry, side_effect=CulliganAuthError("rejected"))

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f for f in flows if f["context"].get("source") == "reauth"]


async def test_unload_removes_the_entities(hass, config_entry):
    await _setup(hass, config_entry)
    loaded = [e for e in hass.states.async_entity_ids() if "softener" in e]

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    for entity_id in loaded:
        state = hass.states.get(entity_id)
        assert state is None or state.state == "unavailable"


async def test_the_services_survive_an_unloaded_entry(hass, config_entry):
    """Registered per entry they vanish while the entry is unloaded, and an
    automation calling one then fails as though the service name were a typo."""
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "bypass_timed")
    assert hass.services.has_service(DOMAIN, "set_clock")


async def test_bypass_reaches_the_api_for_a_known_serial(hass, config_entry):
    await _setup(hass, config_entry)

    with (
        patch(BYPASS, return_value="ok") as bypass,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await hass.services.async_call(
            DOMAIN,
            "bypass_timed",
            {"serial_number": SERIAL, "duration": 60},
            blocking=True,
        )
    bypass.assert_awaited_once_with(SERIAL, 60)


async def test_an_unknown_serial_is_a_validation_error(hass, config_entry):
    """Naming the wrong softener must say so, not raise something opaque."""
    await _setup(hass, config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "bypass_timed",
            {"serial_number": "NOTMINE", "duration": 60},
            blocking=True,
        )


async def test_a_service_call_with_no_loaded_entry_is_a_validation_error(
    hass, config_entry
):
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_clock", {"serial_number": SERIAL}, blocking=True
        )


async def test_the_poll_interval_option_is_applied(hass, config_entry):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={"scan_interval": 300})
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[DEVICE]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.runtime_data.update_interval.total_seconds() == 300


async def test_changing_the_interval_reloads_the_entry(hass, config_entry):
    await _setup(hass, config_entry)
    assert config_entry.runtime_data.update_interval.total_seconds() == 120

    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[DEVICE]):
        hass.config_entries.async_update_entry(
            config_entry, options={"scan_interval": 600}
        )
        await hass.async_block_till_done()

    assert config_entry.runtime_data.update_interval.total_seconds() == 600


async def test_aqua_sensor_entities_are_absent_on_a_unit_without_one(
    hass, config_entry
):
    """The whole point: no entity for hardware that is not fitted.

    DEVICE has every aquasensor_* datapoint at zero, exactly as the real unit
    reports, so capacity_remaining (which reads -515 gal there) must not exist.
    """
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.softener_aqua_sensor_ratio") is None
    assert hass.states.get("sensor.softener_working_capacity") is None
    assert hass.states.get("sensor.softener_capacity_remaining") is None
    # An ungated sensor is still there, so this is not just a failed setup.
    assert hass.states.get("sensor.softener_water_used_today") is not None


async def test_aqua_sensor_entities_appear_when_the_sensor_reports(hass, config_entry):
    """A unit that does have one gets the entities, without a reload."""
    device = {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "aquasensor_z_ratio_current_tank_1": 0.82,
            "total_capacity_volume_tank_1": 1109,
            "capacity_remaining_tank_1": 640,
        },
    }
    config_entry.add_to_hass(hass)
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.softener_aqua_sensor_ratio").state == "0.82"
    assert hass.states.get("sensor.softener_working_capacity").state == "1109"
    assert hass.states.get("sensor.softener_capacity_remaining").state == "640"


async def test_a_user_can_force_a_capability_on(hass, config_entry):
    """The escape hatch for a unit the detector reads wrong."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={"force_capabilities_on": ["aqua_sensor"]}
    )
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[DEVICE]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.softener_working_capacity") is not None


async def test_a_user_can_force_a_detected_capability_off(hass, config_entry):
    device = {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "aquasensor_z_ratio_current_tank_1": 0.82,
        },
    }
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={"force_capabilities_off": ["aqua_sensor"]}
    )
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.softener_aqua_sensor_ratio") is None
