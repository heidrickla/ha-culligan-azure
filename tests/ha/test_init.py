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


async def test_the_services_exist_before_any_entry_is_added(hass, config_entry):
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
