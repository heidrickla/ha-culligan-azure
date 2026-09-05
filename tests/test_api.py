"""The cloud client, against a real HTTP server that answers like Culligan's.

No Home Assistant: the client takes an aiohttp session and nothing else, so
the whole protocol - reactive re-auth on 401 included - is testable here.

A local aiohttp server rather than a request mock: how the client behaves on a
502 HTML page, on a body that is not an object and on a refused connection is
exactly what a mock library gets to define, and those are the branches worth
proving against a real socket.
"""

import datetime
import socket

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from .pure import load

api = load("api")

SERIAL = "GBX0001234"
LOGIN = "/api/v1/auth/login"
REGISTRY = "/api/v1/device/registry"
STATE = "/api/v1/device/state"
DATA = "/api/v1/device/data"
COMMAND = "/api/v1/device/command"

TOKEN_BODY = {"success": True, "data": {"accessToken": "token-1"}}
DEVICES_BODY = {"data": {"devices": [{"serialNumber": SERIAL}]}}


class FakeCloud:
    """Answers each path from a queue and records what was asked."""

    def __init__(self):
        self.calls = []
        self._queues = {}

    def queue(self, path, status=200, payload=None, text=None):
        self._queues.setdefault(path, []).append((status, payload, text))
        return self

    def bodies(self, path):
        return [c["json"] for c in self.calls if c["path"] == path]

    def auth_headers(self, path):
        return [c["auth"] for c in self.calls if c["path"] == path]

    async def handle(self, request):
        self.calls.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "json": await request.json() if request.body_exists else None,
                "auth": request.headers.get("Authorization"),
            }
        )
        queue = self._queues.get(request.path)
        if not queue:
            raise AssertionError(f"unexpected request to {request.path}")
        status, payload, text = queue.pop(0)
        if text is not None:
            return web.Response(status=status, text=text, content_type="text/html")
        if payload is None:
            return web.Response(status=status)
        return web.json_response(payload, status=status)


def closed_port():
    """A port that was just released, so connecting to it is refused."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def cloud(monkeypatch):
    """A running fake cloud, with the client pointed at it."""
    fake = FakeCloud()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setattr(api, "BASE_URL", str(server.make_url("")).rstrip("/"))
    yield fake
    await server.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client_session:
        yield client_session


def make_client(session):
    return api.CulliganApiClient(session, "someone@example.com", "secret")


async def test_a_successful_login_keeps_the_token(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    client = make_client(session)
    await client.async_login()

    assert client._token == "token-1"
    assert cloud.bodies(LOGIN)[0] == {
        "email": "someone@example.com",
        "password": "secret",
        "appId": api.APP_ID,
    }


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_credentials_are_an_auth_error(cloud, session, status):
    """These three must be distinguishable from a broken connection: only they
    should send the user to reauthentication."""
    cloud.queue(LOGIN, status=status, payload={"message": "no"})
    with pytest.raises(api.CulliganAuthError):
        await make_client(session).async_login()


async def test_a_server_error_at_login_is_not_an_auth_error(cloud, session):
    cloud.queue(LOGIN, status=502, text="<html>bad gateway</html>")
    with pytest.raises(api.CulliganError) as err:
        await make_client(session).async_login()
    assert not isinstance(err.value, api.CulliganAuthError)


async def test_a_200_that_is_not_a_successful_login_is_an_error(cloud, session):
    """A proxy or a maintenance page can answer 200 with anything."""
    cloud.queue(LOGIN, payload={"success": False, "message": "nope"})
    with pytest.raises(api.CulliganError):
        await make_client(session).async_login()


async def test_an_html_page_answered_as_200_does_not_crash(cloud, session):
    """Status is checked before the body is parsed, so an HTML page surfaces
    as an error rather than a decode failure escaping the handler."""
    cloud.queue(LOGIN, status=200, text="<html>hello</html>")
    with pytest.raises(api.CulliganError):
        await make_client(session).async_login()


async def test_a_refused_connection_at_login_is_an_error(session, monkeypatch):
    monkeypatch.setattr(api, "BASE_URL", f"http://127.0.0.1:{closed_port()}")
    with pytest.raises(api.CulliganError):
        await make_client(session).async_login()


async def test_a_read_logs_in_first_and_sends_the_token(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, payload=DEVICES_BODY)
    devices = await make_client(session).async_get_devices()

    assert devices == [{"serialNumber": SERIAL}]
    assert cloud.auth_headers(REGISTRY) == ["Bearer token-1"]


async def test_a_401_mid_session_re_authenticates_once_and_retries(cloud, session):
    """expiresIn is a lie - the token died at about 27 minutes against a
    claimed hour - so the client re-authenticates reactively, not on a timer."""
    second = {"success": True, "data": {"accessToken": "token-2"}}
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, status=401, payload={})
    cloud.queue(LOGIN, payload=second).queue(REGISTRY, payload=DEVICES_BODY)

    client = make_client(session)
    assert await client.async_get_devices() == [{"serialNumber": SERIAL}]
    assert client._token == "token-2"
    assert cloud.auth_headers(REGISTRY) == ["Bearer token-1", "Bearer token-2"]


async def test_a_second_401_is_an_error_rather_than_a_loop(cloud, session):
    """The positive control for the retry above: one retry, never a loop."""
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, status=401, payload={})
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, status=401, payload={})

    with pytest.raises(api.CulliganError):
        await make_client(session).async_get_devices()
    assert len(cloud.bodies(LOGIN)) == 2


async def test_a_non_200_read_is_an_error(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, status=500, payload={})
    with pytest.raises(api.CulliganError):
        await make_client(session).async_get_devices()


async def test_a_read_that_answers_with_a_list_is_an_error(cloud, session):
    """The client indexes into the body, so a list would raise something
    opaque several frames later."""
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, payload=[1, 2, 3])
    with pytest.raises(api.CulliganError):
        await make_client(session).async_get_devices()


async def test_a_refused_connection_mid_read_is_an_error(cloud, session, monkeypatch):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    client = make_client(session)
    await client.async_login()
    monkeypatch.setattr(api, "BASE_URL", f"http://127.0.0.1:{closed_port()}")
    with pytest.raises(api.CulliganError):
        await client.async_get_devices()


async def test_an_empty_registry_reads_as_no_devices(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY).queue(REGISTRY, payload={"data": {}})
    assert await make_client(session).async_get_devices() == []


async def test_state_and_datapoints_are_read_per_serial(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(STATE, payload={"data": {"connected": True}})
    cloud.queue(DATA, payload={"data": {"datapoints": {"rssi": -61}}})

    client = make_client(session)
    assert await client.async_get_state(SERIAL) == {"connected": True}
    assert await client.async_get_datapoints(SERIAL) == {"rssi": -61}
    assert [c["query"] for c in cloud.calls if c["path"] in (STATE, DATA)] == [
        {"serialNumber": SERIAL},
        {"serialNumber": SERIAL},
    ]


async def test_missing_sections_in_a_read_are_empty_not_a_crash(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(STATE, payload={}).queue(DATA, payload={"data": {}})
    client = make_client(session)
    assert await client.async_get_state(SERIAL) == {}
    assert await client.async_get_datapoints(SERIAL) == {}


async def test_a_command_returns_the_request_id(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(COMMAND, payload={"success": True, "data": {"requestId": "CC-1"}})
    client = make_client(session)
    assert await client.async_send_command(SERIAL, "telemetry.get") == "CC-1"


async def test_a_command_the_cloud_rejects_raises(cloud, session):
    """A 200 carrying success false is a refusal, not an acknowledgement."""
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(COMMAND, payload={"success": False, "message": "bad command"})
    with pytest.raises(api.CulliganError):
        await make_client(session).async_send_command(SERIAL, "nope")


async def test_every_command_wrapper_sends_the_shape_the_device_expects(cloud, session):
    """The payloads were verified against real hardware; pinned here so a
    refactor cannot quietly change one."""
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    for _ in range(8):
        cloud.queue(COMMAND, payload={"success": True, "data": {"requestId": "CC"}})

    client = make_client(session)
    await client.async_refresh_telemetry(SERIAL)
    await client.async_set_away_mode(SERIAL, True)
    await client.async_set_away_mode(SERIAL, False)
    await client.async_set_salt_level(SERIAL, 75)
    await client.async_bypass_timed(SERIAL, 60)
    await client.async_bypass_permanent(SERIAL)
    await client.async_bypass_off(SERIAL)
    await client.async_regenerate(SERIAL, immediate=False)

    posts = cloud.bodies(COMMAND)
    assert [p["command"] for p in posts] == [
        "telemetry.get",
        "awayMode.set",
        "awayMode.set",
        "salt.set",
        "bypass.timed.on",
        "bypass.permanent.on",
        "bypass.off",
        "regen.set",
    ]
    assert posts[1]["params"] == {"active": 1}
    assert posts[2]["params"] == {"active": 0}
    assert posts[3]["params"] == {"level": 75}
    assert posts[4]["params"] == {"duration": 60}
    assert posts[7]["params"] == {"type": 2}
    assert all(p["serialNumber"] == SERIAL for p in posts)
    assert all(p["protocolVersion"] == 1 for p in posts)
    assert all(p["requestId"].startswith("CC-") for p in posts)


async def test_an_immediate_regeneration_is_type_one(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(COMMAND, payload={"success": True, "data": {"requestId": "CC"}})
    await make_client(session).async_regenerate(SERIAL)
    assert cloud.bodies(COMMAND)[0]["params"] == {"type": 1}


async def test_the_clock_command_sends_the_controllers_own_format(cloud, session):
    """M-d-yyyy_HH:mm:ss with no zero padding on month or day, taken from
    AzureDeviceCommandFactory.setDateTime."""
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(COMMAND, payload={"success": True, "data": {"requestId": "CC"}})
    await make_client(session).async_set_datetime(
        SERIAL, datetime.datetime(2026, 9, 4, 7, 5, 3)
    )
    assert cloud.bodies(COMMAND)[0]["params"] == {"dateTimeValue": "9-4-2026_07:05:03"}


async def test_the_clock_command_defaults_to_now(cloud, session):
    cloud.queue(LOGIN, payload=TOKEN_BODY)
    cloud.queue(COMMAND, payload={"success": True, "data": {"requestId": "CC"}})
    assert await make_client(session).async_set_datetime(SERIAL) == "CC"


def test_the_request_id_mirrors_the_apps_format():
    request_id = api.CulliganApiClient._request_id()
    assert request_id.startswith("CC-")
    # CC-<ISO8601 micros>-<8 hex>. A UTC offset would change the wire format,
    # so the timestamp is deliberately naive.
    assert "+" not in request_id
    assert len(request_id.rsplit("-", 1)[1]) == 8
