"""Polling coordinator for Culligan devices."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import health, resin
from .api import CulliganApiClient, CulliganAuthError, CulliganError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_resin_history"

# Resin fade is a multi-month signal. Sampling more than daily just fills the
# store with noise -- prune() thins to one per day anyway.
SAMPLE_INTERVAL_SECONDS = 6 * 3600


class CulliganCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches every device's state in a single poll.

    /device/registry returns the device list AND the full telemetry object, so
    one request per cycle covers everything -- verified against the live API.
    /device/state is fetched additionally only for the `connected` flag, which
    registry reports less reliably.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CulliganApiClient,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        self.client = client
        # {serial: [ {ts, gallons, regens}, ... ] } persisted across restarts.
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}"
        )
        self._resin_history: dict[str, list[dict[str, float]]] = {}
        self._history_loaded = False

    async def async_load_history(self) -> None:
        """Load persisted resin samples. Must run before the first refresh."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            for serial, samples in stored.items():
                if isinstance(samples, list):
                    self._resin_history[serial] = [
                        s for s in samples if isinstance(s, dict) and "ts" in s
                    ]
        self._history_loaded = True
        _LOGGER.debug("loaded resin history for %d device(s)", len(self._resin_history))

    def _record_resin_sample(self, serial: str, datapoints: dict[str, Any]) -> None:
        """Append a sample if enough time has passed since the last one."""
        sample = resin.make_sample(dt_util.utcnow().timestamp(), datapoints)
        if sample is None:
            return
        history = self._resin_history.setdefault(serial, [])
        if history and (sample["ts"] - history[-1]["ts"]) < SAMPLE_INTERVAL_SECONDS:
            return
        history.append(sample)
        self._resin_history[serial] = resin.prune(history)
        # Store writes are debounced by HA; this is cheap at one per 6h.
        self._store.async_delay_save(lambda: dict(self._resin_history), 30)

    async def _async_update_data(self) -> dict[str, Any]:
        """Return {serial: {"device": ..., "datapoints": ..., "health": ...}}."""
        try:
            devices = await self.client.async_get_devices()
        except CulliganAuthError as err:
            # Credentials genuinely rejected -- prompt the user to reauth rather
            # than retrying forever with a password that will never work.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CulliganError as err:
            raise UpdateFailed(f"registry poll failed: {err}") from err

        now_year = dt_util.now().year
        result: dict[str, Any] = {}

        for dev in devices:
            serial = dev.get("serialNumber")
            if not serial:
                continue
            datapoints = dev.get("properties") or {}
            if not datapoints:
                # Older firmware may not embed properties in registry.
                try:
                    datapoints = await self.client.async_get_datapoints(serial)
                except CulliganError as err:
                    _LOGGER.warning("telemetry fetch failed for %s: %s", serial, err)
                    datapoints = {}

            connected = dev.get("status", {}).get("connection", {}).get("online")
            if connected is None:
                try:
                    connected = (await self.client.async_get_state(serial)).get(
                        "connected"
                    )
                except CulliganError:
                    connected = None

            if datapoints:
                self._record_resin_sample(serial, datapoints)

            # Resin analysis lives inside the health dict so entity value
            # functions only ever need (datapoints, health).
            summary = health.summary(datapoints, now_year=now_year)
            summary["resin"] = resin.analyse(self._resin_history.get(serial, []))
            summary["resin_lifetime_capacity"] = resin.capacity_per_cycle_lifetime(
                datapoints
            )
            expected = summary.get("expected_days_between_regens")
            summary["resin_cycle_age_years"] = resin.cycle_age_years(
                datapoints, expected
            )
            summary["resin_excess_cycles"] = resin.excess_cycles_lifetime(
                datapoints, expected
            )
            summary["resin_cycle_acceleration"] = resin.cycle_age_acceleration(
                datapoints, expected
            )

            result[serial] = {
                "device": dev,
                "datapoints": datapoints,
                "connected": connected,
                "health": summary,
            }

        if not result:
            raise UpdateFailed("no devices returned")
        return result

    async def async_send_and_refresh(self, coro) -> None:
        """Await a command, then refresh.

        The API acknowledges commands without confirming the device acted, so a
        refresh is the only way to learn what actually happened. The device
        needs a moment to round-trip via Azure IoT Hub before the change shows.
        """
        try:
            await coro
        except CulliganError as err:
            raise UpdateFailed(f"command failed: {err}") from err
        await self.async_request_refresh()
