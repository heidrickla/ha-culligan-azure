"""Softeners appearing on and leaving the account after setup.

The account is re-read on every poll, so both directions have to work without
the user reloading anything.
"""

from unittest.mock import patch

from homeassistant.helpers import device_registry as dr

from custom_components.culligan_azure import async_remove_config_entry_device
from custom_components.culligan_azure.api import CulliganError
from custom_components.culligan_azure.const import DOMAIN

from .conftest import DEVICE, SERIAL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"

SECOND_SERIAL = "GBX0009999"
SECOND = {**DEVICE, "serialNumber": SECOND_SERIAL, "name": "Basement"}


async def _setup(hass, entry, devices):
    entry.add_to_hass(hass)
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=devices):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def device(hass, serial):
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, serial)})


async def test_a_softener_added_later_appears_without_a_reload(hass, config_entry):
    await _setup(hass, config_entry, [DEVICE])
    assert device(hass, SECOND_SERIAL) is None

    with patch(DEVICES, return_value=[DEVICE, SECOND]):
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert device(hass, SECOND_SERIAL) is not None
    assert hass.states.get("sensor.basement_water_used_today") is not None


async def test_a_softener_that_leaves_the_account_is_removed_on_the_next_poll(
    hass, config_entry
):
    """Checking only at setup left the device page showing hardware that was
    gone until the next restart."""
    await _setup(hass, config_entry, [DEVICE, SECOND])
    assert device(hass, SECOND_SERIAL) is not None

    with patch(DEVICES, return_value=[DEVICE]):
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert device(hass, SECOND_SERIAL) is None
    assert device(hass, SERIAL) is not None


async def test_a_failed_poll_removes_nothing(hass, config_entry):
    """An empty result is a failed read, not an emptied account."""
    await _setup(hass, config_entry, [DEVICE, SECOND])

    with patch(DEVICES, side_effect=CulliganError("gateway timeout")):
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert device(hass, SERIAL) is not None
    assert device(hass, SECOND_SERIAL) is not None


async def test_a_device_the_account_still_lists_cannot_be_deleted_by_hand(
    hass, config_entry
):
    await _setup(hass, config_entry, [DEVICE])
    live = device(hass, SERIAL)
    assert await async_remove_config_entry_device(hass, config_entry, live) is False


async def test_a_device_the_account_no_longer_lists_can_be_deleted_by_hand(
    hass, config_entry
):
    """The way out when a poll keeps failing and automatic removal never gets
    to say the softener is gone."""
    await _setup(hass, config_entry, [DEVICE])
    orphan = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "GBX0000000")},
        name="Sold",
    )
    assert await async_remove_config_entry_device(hass, config_entry, orphan) is True


async def test_manual_deletion_is_allowed_while_the_entry_is_unloaded(
    hass, config_entry
):
    """An unloaded entry knows no serials, so nothing it owns can be claimed
    to still be present."""
    await _setup(hass, config_entry, [DEVICE])
    live = device(hass, SERIAL)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await async_remove_config_entry_device(hass, config_entry, live) is True
