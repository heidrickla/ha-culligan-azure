"""Async client for the Culligan Connect cloud API (Azure-backed devices).

Protocol documented in API.md, derived by TLS interception of the Android app
plus decompilation of AzureDeviceCommandFactory.

Two behaviours worth knowing, both learned the hard way:

  * `expiresIn` is a lie. The server issued 3600 and rejected the token after
    ~27 minutes. Do not refresh on a timer -- re-authenticate reactively when a
    call returns 401 INVALID_TOKEN, which is exactly what the app does.
  * A 200 from /device/command only means the CLOUD accepted the request. It
    does not mean the device applied it. Callers should re-poll to confirm.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://uniapi.culliganiot.com"
# Constant the Android app sends with every login.
APP_ID = "OAhRjZjfBSwKLV8MTCjscAdoyJKzjxQW"
REQUEST_TIMEOUT = 30


class CulliganError(Exception):
    """Base error."""


class CulliganAuthError(CulliganError):
    """Credentials rejected."""


class CulliganApiClient:
    """Talks to uniapi.culliganiot.com on behalf of one account."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._lock = asyncio.Lock()

    # -- auth -------------------------------------------------------------

    async def async_login(self) -> None:
        """Obtain an access token. Raises CulliganAuthError on bad credentials."""
        payload = {"email": self._email, "password": self._password, "appId": APP_ID}
        try:
            async with self._session.post(
                f"{BASE_URL}/api/v1/auth/login",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status in (400, 401, 403):
                    raise CulliganAuthError(f"login rejected: HTTP {resp.status}")
                if resp.status != 200 or not body.get("success"):
                    raise CulliganError(f"login failed: HTTP {resp.status} {body}")
                self._token = body["data"]["accessToken"]
        except aiohttp.ClientError as err:
            raise CulliganError(f"login transport error: {err}") from err

    async def _request(
        self, method: str, path: str, json_body: dict | None = None, _retry: bool = True
    ) -> dict[str, Any]:
        """Make an authenticated request, re-logging-in once on 401."""
        async with self._lock:
            if self._token is None:
                await self.async_login()
            token = self._token

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with self._session.request(
                method,
                f"{BASE_URL}{path}",
                json=json_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 401 and _retry:
                    # Reactive re-auth: the token died early, as it always does.
                    _LOGGER.debug("401 from %s, re-authenticating", path)
                    async with self._lock:
                        self._token = None
                    return await self._request(method, path, json_body, _retry=False)
                body = await resp.json(content_type=None)
                if resp.status != 200:
                    raise CulliganError(f"{method} {path}: HTTP {resp.status} {body}")
                return body
        except aiohttp.ClientError as err:
            raise CulliganError(f"{method} {path}: transport error: {err}") from err

    # -- reads ------------------------------------------------------------

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Device list WITH full telemetry -- one call gets everything."""
        body = await self._request("GET", "/api/v1/device/registry")
        return body.get("data", {}).get("devices", [])

    async def async_get_state(self, serial: str) -> dict[str, Any]:
        """Connection/health for one device. serialNumber is required."""
        body = await self._request("GET", f"/api/v1/device/state?serialNumber={serial}")
        return body.get("data", {})

    async def async_get_datapoints(self, serial: str) -> dict[str, Any]:
        """Telemetry only. serialNumber is required."""
        body = await self._request("GET", f"/api/v1/device/data?serialNumber={serial}")
        return body.get("data", {}).get("datapoints", {})

    # -- writes -----------------------------------------------------------

    @staticmethod
    def _request_id() -> str:
        """Mirror the app's format: CC-<ISO8601 micros>-<8 hex>."""
        # Naive local time on purpose: the app's requestId carries no UTC
        # offset, and an aware isoformat() would append one, changing the
        # wire format we are deliberately mirroring.
        return f"CC-{datetime.datetime.now().isoformat()}-{uuid.uuid4().hex[:8]}"  # noqa: DTZ005

    async def async_send_command(
        self, serial: str, command: str, params: dict[str, Any] | None = None
    ) -> str:
        """Send a device command. Returns the requestId.

        NOTE: success here means the cloud queued it, NOT that the device acted.
        """
        payload = {
            "command": command,
            "params": params or {},
            "protocolVersion": 1,
            "requestId": self._request_id(),
            "serialNumber": serial,
        }
        body = await self._request("POST", "/api/v1/device/command", payload)
        if not body.get("success"):
            raise CulliganError(f"command {command} rejected: {body}")
        return body.get("data", {}).get("requestId", "")

    # Convenience wrappers -- shapes verified against real hardware.

    async def async_refresh_telemetry(self, serial: str) -> str:
        return await self.async_send_command(serial, "telemetry.get", {})

    async def async_set_away_mode(self, serial: str, active: bool) -> str:
        return await self.async_send_command(
            serial, "awayMode.set", {"active": 1 if active else 0}
        )

    async def async_set_salt_level(self, serial: str, level: int) -> str:
        return await self.async_send_command(serial, "salt.set", {"level": int(level)})

    async def async_bypass_timed(self, serial: str, minutes: int) -> str:
        return await self.async_send_command(
            serial, "bypass.timed.on", {"duration": int(minutes)}
        )

    async def async_bypass_permanent(self, serial: str) -> str:
        return await self.async_send_command(serial, "bypass.permanent.on", {})

    async def async_bypass_off(self, serial: str) -> str:
        return await self.async_send_command(serial, "bypass.off", {})

    async def async_regenerate(self, serial: str, immediate: bool = True) -> str:
        """type 1 = start now, type 2 = schedule. Confirmed by controlled test."""
        return await self.async_send_command(
            serial, "regen.set", {"type": 1 if immediate else 2}
        )

    async def async_set_datetime(
        self, serial: str, when: datetime.datetime | None = None
    ) -> str:
        """Set the controller clock. Format is M-d-yyyy_HH:mm:ss (no zero padding
        on month/day) -- taken from AzureDeviceCommandFactory.setDateTime."""
        # Naive LOCAL time on purpose: this sets the controller's own wall
        # clock, which has no timezone concept - it wants local time.
        when = when or datetime.datetime.now()  # noqa: DTZ005
        value = f"{when.month}-{when.day}-{when.year}_{when:%H:%M:%S}"
        return await self.async_send_command(
            serial, "timeDate.set", {"dateTimeValue": value}
        )
