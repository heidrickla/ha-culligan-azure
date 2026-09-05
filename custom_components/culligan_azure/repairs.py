"""Fix flow for the controller-clock repair issue.

The valve controller keeps its own clock, nothing syncs it, and it can sit
years behind without any alert. Confirming the repair sets it to Home
Assistant's local time - the same command the Sync controller clock button and
the set_clock action send.
"""

from __future__ import annotations

from typing import cast

import voluptuous as vol
from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import ISSUE_CLOCK_WRONG
from .coordinator import CulliganConfigEntry


class ClockRepairFlow(RepairsFlow):
    """Set one softener's controller clock, then clear the issue."""

    def __init__(self, entry: CulliganConfigEntry, serial: str) -> None:
        super().__init__()
        self._entry = entry
        self._serial = serial

    @callback
    def _placeholders(self) -> dict[str, str]:
        """The placeholders the issue was raised with, for the form text."""
        issue = ir.async_get(self.hass).async_get_issue(self.handler, self.issue_id)
        if issue is None or not issue.translation_placeholders:
            return {}
        return dict(issue.translation_placeholders)

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = self._entry.runtime_data
            try:
                await coordinator.async_send_and_refresh(
                    coordinator.client.async_set_datetime(self._serial, dt_util.now())
                )
            except HomeAssistantError:
                # The cloud refused or the device is offline. Leave the issue
                # standing and let the user try again rather than reporting a
                # fix that did not happen.
                errors["base"] = "command_failed"
            else:
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=self._placeholders(),
            errors=errors,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Build the flow for an issue this integration raised."""
    if data is not None and issue_id.startswith(f"{ISSUE_CLOCK_WRONG}_"):
        entry_id = data.get("entry_id")
        serial = data.get("serial")
        if isinstance(entry_id, str) and isinstance(serial, str):
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.state is ConfigEntryState.LOADED:
                return ClockRepairFlow(cast(CulliganConfigEntry, entry), serial)
    # The entry was removed or unloaded between the issue being raised and the
    # user opening it. Acknowledging is all that is left to offer.
    return ConfirmRepairFlow()
