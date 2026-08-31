"""The config flow: login, the three ways it can fail, and both repair paths.

The Azure API is never contacted. `async_login` and `async_get_devices` are
the only two calls the flow makes, so replacing them exercises the flow's own
code without a socket.
"""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType

from custom_components.culligan_azure.api import CulliganAuthError, CulliganError
from custom_components.culligan_azure.const import DEFAULT_SCAN_INTERVAL, DOMAIN

from .conftest import DEVICE, EMAIL

LOGIN = "custom_components.culligan_azure.api.CulliganApiClient.async_login"
DEVICES = "custom_components.culligan_azure.api.CulliganApiClient.async_get_devices"


def _ok(devices=None):
    return (
        patch(LOGIN, return_value=None),
        patch(DEVICES, return_value=[DEVICE] if devices is None else devices),
    )


async def test_user_step_creates_the_entry(hass):
    login, devices = _ok()
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"][CONF_EMAIL] == EMAIL


async def test_the_email_is_trimmed_and_the_unique_id_lowercased(hass):
    """A stray space or a capital letter must not create a second account."""
    login, devices = _ok()
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_EMAIL: f"  {EMAIL.upper()}  ", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_EMAIL] == EMAIL.upper()
    assert result["result"].unique_id == EMAIL


async def test_the_first_form_is_shown_with_no_input(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (CulliganAuthError("rejected"), "invalid_auth"),
        (CulliganError("gateway timeout"), "cannot_connect"),
    ],
)
async def test_a_failed_login_names_its_own_cause(hass, raised, expected):
    with patch(LOGIN, side_effect=raised):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_an_account_with_no_devices_is_refused(hass):
    """Credentials work but there is nothing to add. Creating an empty entry
    would look like success and then produce no entities at all."""
    login, devices = _ok(devices=[])
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices"}


async def test_the_same_account_cannot_be_added_twice(hass, config_entry):
    config_entry.add_to_hass(hass)
    login, devices = _ok()
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_password_in_place(hass, config_entry):
    config_entry.add_to_hass(hass)
    login, devices = _ok()
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "newsecret"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PASSWORD] == "newsecret"


async def test_reconfigure_refuses_to_swap_in_another_account(hass, config_entry):
    """Repointing the entry at a different account would silently rebind
    every entity to another household's hardware."""
    config_entry.add_to_hass(hass)
    login, devices = _ok()
    with login, devices:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={CONF_EMAIL: "other@example.com", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_account"
    assert config_entry.data[CONF_EMAIL] == EMAIL


async def test_reconfigure_shows_the_error_rather_than_saving(hass, config_entry):
    config_entry.add_to_hass(hass)
    with patch(LOGIN, side_effect=CulliganAuthError("rejected")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "wrong"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_PASSWORD] == "secret"


async def test_reauth_asks_only_for_the_password(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    login, devices = _ok()
    with login, devices:
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "newsecret"}
        )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "newsecret"
    assert config_entry.data[CONF_EMAIL] == EMAIL


async def test_reauth_reports_a_still_wrong_password(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    with patch(LOGIN, side_effect=CulliganAuthError("rejected")):
        again = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_PASSWORD] == "secret"


async def test_the_options_flow_sets_the_poll_interval(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    done = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 300}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["scan_interval"] == 300


async def test_the_poll_interval_has_a_floor(hass, config_entry):
    """This is an undocumented third-party API. A user typing 1 should be
    stopped by the schema, not by the vendor."""
    import voluptuous as vol

    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 1}
        )
    assert config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL) == 120
