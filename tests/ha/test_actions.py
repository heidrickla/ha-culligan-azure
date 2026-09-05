"""What the buttons, the number and the switches actually send, and what a
refused command does to the user.

Every write goes through the coordinator's async_send_and_refresh, so this is
also where the auth-failure path that starts reauthentication is proven.
"""

from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.culligan_azure.api import CulliganAuthError, CulliganError
from custom_components.culligan_azure.const import DOMAIN

from .conftest import DEVICE, SERIAL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"
REGENERATE = f"{CLIENT}.async_regenerate"
REFRESH = f"{CLIENT}.async_refresh_telemetry"
SET_DATETIME = f"{CLIENT}.async_set_datetime"
SET_SALT = f"{CLIENT}.async_set_salt_level"
AWAY = f"{CLIENT}.async_set_away_mode"
BYPASS_ON = f"{CLIENT}.async_bypass_permanent"
BYPASS_OFF = f"{CLIENT}.async_bypass_off"


async def _setup(hass, entry, devices=None):
    entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[DEVICE] if devices is None else devices),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _press(hass, entity_id):
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )


@pytest.mark.parametrize(
    ("entity_id", "target", "expected"),
    [
        ("button.softener_regenerate_now", REGENERATE, {"immediate": True}),
        ("button.softener_schedule_regeneration", REGENERATE, {"immediate": False}),
        ("button.softener_refresh_telemetry", REFRESH, None),
        ("button.softener_sync_controller_clock", SET_DATETIME, None),
    ],
)
async def test_each_button_sends_its_own_command(
    hass, config_entry, entity_id, target, expected
):
    await _setup(hass, config_entry)
    with (
        patch(target, return_value="CC") as command,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await _press(hass, entity_id)
    command.assert_awaited_once()
    assert command.await_args.args[0] == SERIAL
    if expected is not None:
        assert command.await_args.kwargs == expected


async def test_the_salt_level_number_sends_the_value(hass, config_entry):
    """The unit has no salt sensor on this model: this is an input that the
    controller counts down from."""
    await _setup(hass, config_entry)
    with (
        patch(SET_SALT, return_value="CC") as command,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.softener_salt_level", "value": 75},
            blocking=True,
        )
    command.assert_awaited_once_with(SERIAL, 75)


async def test_away_mode_switches_both_ways(hass, config_entry):
    await _setup(hass, config_entry)
    with (
        patch(AWAY, return_value="CC") as command,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.softener_away_mode"},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.softener_away_mode"},
            blocking=True,
        )
    assert [call.args for call in command.await_args_list] == [
        (SERIAL, True),
        (SERIAL, False),
    ]


async def test_bypass_uses_two_different_commands(hass, config_entry):
    """Bypass is not one boolean on this API: on and off are separate
    commands, and the timed form is an action because a switch has no
    duration."""
    await _setup(hass, config_entry)
    with (
        patch(BYPASS_ON, return_value="CC") as on,
        patch(BYPASS_OFF, return_value="CC") as off,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.softener_bypass"}, blocking=True
        )
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.softener_bypass"}, blocking=True
        )
    on.assert_awaited_once_with(SERIAL)
    off.assert_awaited_once_with(SERIAL)


async def test_away_mode_reads_a_string_zero_as_off(hass, config_entry):
    """The API returns numbers as strings on some fields, and bool("0") is
    True."""
    device = {**DEVICE, "properties": {**DEVICE["properties"], "away_mode": "0"}}
    await _setup(hass, config_entry, devices=[device])
    assert hass.states.get("switch.softener_away_mode").state == "off"
    assert hass.states.get("binary_sensor.softener_away_mode").state == "off"


async def test_an_absent_bypass_reading_is_unknown_not_off(hass, config_entry):
    """No bypass state was ever captured while active, so a missing value must
    not be reported as confidently off."""
    await _setup(hass, config_entry)
    assert hass.states.get("switch.softener_bypass").state == "unknown"


async def test_the_salt_number_is_unknown_without_a_reading(hass, config_entry):
    await _setup(hass, config_entry)
    assert hass.states.get("number.softener_salt_level").state == "unknown"


async def test_the_salt_number_reports_the_stored_level(hass, config_entry):
    device = {
        **DEVICE,
        "properties": {**DEVICE["properties"], "manual_salt_level_rem_calc": 50},
    }
    await _setup(hass, config_entry, devices=[device])
    assert hass.states.get("number.softener_salt_level").state == "50.0"


async def test_a_refused_command_reaches_the_user_translated(hass, config_entry):
    """UpdateFailed would be the wrong contract here and its message reaches
    the user untranslated."""
    await _setup(hass, config_entry)
    with (
        patch(REGENERATE, side_effect=CulliganError("HTTP 503")),
        patch(DEVICES, return_value=[DEVICE]),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _press(hass, "button.softener_regenerate_now")
    assert err.value.translation_key == "command_failed"


async def test_a_command_rejected_for_auth_starts_reauthentication(hass, config_entry):
    """Dead credentials fail every future command too, so the first one starts
    the flow rather than letting each press fail the same way."""
    await _setup(hass, config_entry)
    with (
        patch(REGENERATE, side_effect=CulliganAuthError("token dead")),
        patch(DEVICES, return_value=[DEVICE]),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _press(hass, "button.softener_regenerate_now")
    assert err.value.translation_key == "auth_failed"

    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f for f in flows if f["context"].get("source") == "reauth"]


async def test_the_set_clock_action_sends_the_command(hass, config_entry):
    await _setup(hass, config_entry)
    with (
        patch(SET_DATETIME, return_value="CC") as command,
        patch(DEVICES, return_value=[DEVICE]),
    ):
        await hass.services.async_call(
            DOMAIN, "set_clock", {"serial_number": SERIAL}, blocking=True
        )
    command.assert_awaited_once()
    assert command.await_args.args[0] == SERIAL
