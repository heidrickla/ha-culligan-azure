"""Setup, teardown, services, and what a failing poll does to the entry."""

import logging
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.culligan_azure.api import CulliganAuthError, CulliganError
from custom_components.culligan_azure.const import DOMAIN

from .conftest import DEVICE, SERIAL

CLIENT = "custom_components.culligan_azure.api.CulliganApiClient"
LOGIN = f"{CLIENT}.async_login"
DEVICES = f"{CLIENT}.async_get_devices"
DATAPOINTS = f"{CLIENT}.async_get_datapoints"
BYPASS = f"{CLIENT}.async_bypass_timed"
ANALYSE = "custom_components.culligan_azure.coordinator.resin.analyse"
RESIN_DUE = "binary_sensor.softener_resin_replacement_due"


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


async def test_an_empty_device_list_is_a_failed_poll(hass, config_entry):
    """Zero devices from a working login is a read failure, not an emptied
    account; the entry retries rather than loading with nothing."""
    await _setup(hass, config_entry, devices=[])
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_noisy_diagnostics_are_registered_but_disabled(hass, config_entry):
    """Wi-Fi signal and the other niche diagnostics exist in the registry so a
    user can switch them on, and have no state until they do."""
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    for key in ("rssi", "last_power_up", "regens_lifetime", "resin_capacity_lifetime"):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_{key}")
        assert entity_id is not None, key
        entry = registry.async_get(entity_id)
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key
        assert hass.states.get(entity_id) is None, key


async def test_a_string_zero_bypass_flag_reads_as_off(hass, config_entry):
    """The API returns numbers as strings on some fields, and bool("0") is
    True. The switch must read the number, not the truthiness."""
    device = {
        **DEVICE,
        "properties": {**DEVICE["properties"], "actual_state_dealer_bypass": "0"},
    }
    await _setup(hass, config_entry, devices=[device])
    assert hass.states.get("switch.softener_bypass").state == "off"


async def test_regenerating_is_unknown_until_the_timer_is_reported(hass, config_entry):
    await _setup(hass, config_entry)
    assert hass.states.get("binary_sensor.softener_regenerating").state == "unknown"


async def test_regenerating_is_on_while_the_position_timer_runs(hass, config_entry):
    device = {
        **DEVICE,
        "properties": {**DEVICE["properties"], "time_rem_in_position": 12},
    }
    await _setup(hass, config_entry, devices=[device])
    assert hass.states.get("binary_sensor.softener_regenerating").state == "on"


async def _setup_with_resin(hass, entry, result):
    entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[DEVICE]),
        patch(ANALYSE, return_value=result),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_resin_replacement_due_reads_off_on_a_low_confidence_trend(
    hass, config_entry
):
    """The README promises the problem sensor never fires on a noisy fit, even
    one that extrapolates to under a year."""
    await _setup_with_resin(
        hass,
        config_entry,
        {"status": "low_confidence", "years_remaining": 0.4, "confidence": 0.1},
    )
    state = hass.states.get(RESIN_DUE)
    assert state.state == "off"
    assert state.attributes["status"] == "low_confidence"


async def test_resin_replacement_due_fires_on_a_confident_trend_under_a_year(
    hass, config_entry
):
    """The positive control for the low-confidence case above."""
    await _setup_with_resin(
        hass,
        config_entry,
        {"status": "ok", "years_remaining": 0.4, "confidence": 0.9},
    )
    assert hass.states.get(RESIN_DUE).state == "on"


async def test_resin_replacement_due_is_unknown_while_collecting(hass, config_entry):
    await _setup_with_resin(hass, config_entry, {"status": "collecting"})
    assert hass.states.get(RESIN_DUE).state == "unknown"


async def test_a_failing_telemetry_fallback_is_logged_once(hass, config_entry, caplog):
    """Older firmware omits `properties`; the /device/data fallback failing
    is logged on loss and on recovery, not on every poll in between."""
    bare = {k: v for k, v in DEVICE.items() if k != "properties"}
    caplog.set_level(logging.INFO, logger="custom_components.culligan_azure")
    config_entry.add_to_hass(hass)
    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[bare]),
        patch(DATAPOINTS, side_effect=CulliganError("HTTP 502")),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        coordinator = config_entry.runtime_data
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert config_entry.state is ConfigEntryState.LOADED
    assert caplog.text.count("telemetry fetch failed") == 1

    with (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[bare]),
        patch(DATAPOINTS, return_value=DEVICE["properties"]),
    ):
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert caplog.text.count("telemetry fetch for GBX0001234 recovered") == 1


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

    assert hass.states.get("sensor.softener_working_capacity") is None
    assert hass.states.get("sensor.softener_capacity_remaining") is None
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_aquasensor_ratio")
        is None
    )
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

    assert hass.states.get("sensor.softener_working_capacity").state == "1109"
    assert hass.states.get("sensor.softener_capacity_remaining").state == "640"
    # The raw ratio is registered too, disabled until someone wants it.
    registry = er.async_get(hass)
    ratio = registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_aquasensor_ratio")
    assert ratio is not None
    assert registry.async_get(ratio).disabled_by is er.RegistryEntryDisabler.INTEGRATION


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
            "total_capacity_volume_tank_1": 1109,
        },
    }
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={"force_capabilities_off": ["aqua_sensor"]}
    )
    with patch(LOGIN, return_value=None), patch(DEVICES, return_value=[device]):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.softener_working_capacity") is None
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_aquasensor_ratio")
        is None
    )
