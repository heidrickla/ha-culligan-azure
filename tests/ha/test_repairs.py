"""The controller-clock repair: when it is raised, when it clears, and what
confirming it actually sends.

The valve controller keeps its own clock, nothing syncs it, and the only fix
is one command - which is what makes it a repair with a fix flow rather than a
problem sensor the user can do nothing with.
"""

from unittest.mock import patch

from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.culligan_azure.api import CulliganError
from custom_components.culligan_azure.const import DOMAIN, ISSUE_CLOCK_WRONG
from custom_components.culligan_azure.repairs import async_create_fix_flow

from .conftest import DEVICE, SERIAL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"
SET_DATETIME = f"{CLIENT}.async_set_datetime"
ISSUE_ID = f"{ISSUE_CLOCK_WRONG}_{SERIAL}"


def device_with_clock(year_offset):
    """The softener, with a last power-up stamp that many years in the past."""
    year = dt_util.now().year + year_offset
    return {
        **DEVICE,
        "properties": {
            **DEVICE["properties"],
            "last_power_up_time": f"{year}-06-01 09:00:00",
        },
    }


async def _setup(hass, entry, devices):
    entry.add_to_hass(hass)
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=devices):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


async def test_a_clock_years_out_raises_a_fixable_repair(hass, config_entry):
    await _setup(hass, config_entry, [device_with_clock(-5)])

    raised = issue(hass)
    assert raised is not None
    assert raised.is_fixable is True
    assert raised.severity is ir.IssueSeverity.WARNING
    assert raised.translation_key == ISSUE_CLOCK_WRONG
    assert raised.translation_placeholders == {"device": "Softener"}
    assert raised.data == {"entry_id": config_entry.entry_id, "serial": SERIAL}
    # The problem sensor still says the same thing on the device page.
    assert (
        hass.states.get("binary_sensor.softener_controller_clock_wrong").state == "on"
    )


async def test_a_correct_clock_raises_nothing(hass, config_entry):
    """The positive control: the same code path with a plausible stamp."""
    await _setup(hass, config_entry, [device_with_clock(0)])
    assert issue(hass) is None
    assert (
        hass.states.get("binary_sensor.softener_controller_clock_wrong").state == "off"
    )


async def test_the_repair_clears_once_the_clock_is_right(hass, config_entry):
    await _setup(hass, config_entry, [device_with_clock(-5)])
    assert issue(hass) is not None

    with patch(DEVICES, return_value=[device_with_clock(0)]):
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert issue(hass) is None


async def test_the_repair_clears_when_the_softener_leaves_the_account(
    hass, config_entry
):
    other = {**DEVICE, "serialNumber": "GBX0009999", "name": "Basement"}
    await _setup(hass, config_entry, [device_with_clock(-5), other])
    assert issue(hass) is not None

    with patch(DEVICES, return_value=[other]):
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert issue(hass) is None


async def _fix_flow(hass, config_entry, data=None):
    flow = await async_create_fix_flow(
        hass,
        ISSUE_ID,
        {"entry_id": config_entry.entry_id, "serial": SERIAL} if data is None else data,
    )
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = ISSUE_ID
    return flow


async def test_confirming_the_repair_sets_the_clock(hass, config_entry):
    await _setup(hass, config_entry, [device_with_clock(-5)])
    flow = await _fix_flow(hass, config_entry)

    form = await flow.async_step_init()
    assert form["type"] == "form"
    assert form["step_id"] == "confirm"
    assert form["description_placeholders"] == {"device": "Softener"}

    with (
        patch(SET_DATETIME, return_value="CC") as command,
        patch(DEVICES, return_value=[device_with_clock(-5)]),
    ):
        result = await flow.async_step_confirm({})

    assert result["type"] == "create_entry"
    command.assert_awaited_once()
    assert command.await_args.args[0] == SERIAL


async def test_a_refused_fix_leaves_the_repair_standing(hass, config_entry):
    """Reporting a fix that did not happen is worse than asking again."""
    await _setup(hass, config_entry, [device_with_clock(-5)])
    flow = await _fix_flow(hass, config_entry)
    await flow.async_step_init()

    with (
        patch(SET_DATETIME, side_effect=CulliganError("device offline")),
        patch(DEVICES, return_value=[device_with_clock(-5)]),
    ):
        result = await flow.async_step_confirm({})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "command_failed"}
    assert issue(hass) is not None


async def test_a_repair_whose_entry_is_gone_falls_back_to_acknowledging(hass):
    """The entry can be removed between the repair being raised and the user
    opening it; there is nothing left to send."""
    flow = await async_create_fix_flow(
        hass, ISSUE_ID, {"entry_id": "no-such-entry", "serial": SERIAL}
    )
    assert type(flow).__name__ == "ConfirmRepairFlow"


async def test_a_repair_with_no_data_falls_back_to_acknowledging(hass):
    assert type(await async_create_fix_flow(hass, ISSUE_ID, None)).__name__ == (
        "ConfirmRepairFlow"
    )
    assert type(await async_create_fix_flow(hass, ISSUE_ID, {})).__name__ == (
        "ConfirmRepairFlow"
    )
    assert type(await async_create_fix_flow(hass, "something_else", {})).__name__ == (
        "ConfirmRepairFlow"
    )


async def test_removing_the_entry_takes_its_repairs_with_it(hass, config_entry):
    """A repair for a softener that is no longer configured can never be
    fixed, so it must not outlive the entry."""
    await _setup(hass, config_entry, [device_with_clock(-5)])
    assert issue(hass) is not None

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert issue(hass) is None
