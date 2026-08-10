# Culligan Connect cloud API

Reverse-engineered from the Android app (`com.culligan.connect` 3.7.17, versionCode 264) by TLS
interception on an emulator with the mitmproxy CA in the system trust store. 398 flows captured
2026-08-10.

Base URL: `https://uniapi.culliganiot.com`
App config: `https://static.culliganiot.com/appconfig/culligan-connect/appconfig.json`

The app does **not** pin certificates (OkHttp is bundled but `CertificatePinner` is never configured),
and declares no `networkSecurityConfig`. A system-store CA is sufficient to intercept.

## Architecture

    Softener  ──MQTT/TLS──▶  Azure IoT Hub  ◀──  Culligan backend  ◀──REST──  App / this API

The device talks only to `iot-eastus2-hub-main-production-us.azure-devices.net` and validates its
certificate chain, so it cannot be intercepted or impersonated. This REST API is the only usable
integration point.

## Auth

    POST /api/v1/auth/login
    {"email": "...", "password": "...", "appId": "..."}

    200 -> {"success": true, "data": {
              "userId": str, "accessToken": str, "refreshToken": str,
              "expiresIn": int, "linkedAccounts": {}, "roles": [str], "tenantId": null }}

`appId` is a constant sent by the app.

### Token handling — do NOT trust `expiresIn`

Observed behaviour, measured across 900+ flows:

    14:17:27  POST /auth/login    -> 200, expiresIn 3600
    14:44:28  POST /device/command -> 401 {"success":false,"error":{"message":"INVALID_TOKEN"}}
    14:44:29  POST /auth/login    -> 200, resumes normally

- The token was rejected after **~27 minutes**, not the 3600s advertised. Treat `expiresIn` as
  advisory at best.
- **The app never uses `refreshToken`.** Zero calls to any refresh endpoint in the entire capture;
  on 401 it simply re-POSTs `/auth/login` with the stored credentials.

So an integration should hold the username/password, ignore `expiresIn`, and **re-authenticate
reactively on `401 INVALID_TOKEN`** rather than proactively on a timer. A refresh-token flow may
exist server-side but is unused by the client and therefore unverified.

## Read endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/device/registry` | Device list **including full telemetry** — the one call an integration needs. No query params. |
| GET | `/api/v1/device/data?serialNumber=<dsn>` | Telemetry datapoints only. **`serialNumber` is required** — omit it and the call fails. |
| GET | `/api/v1/device/state?serialNumber=<dsn>` | Connection/health: `connected`, heartbeat and event timestamps, `errors[]`, `alerts[]`. **`serialNumber` required.** |
| GET | `/api/v1/metadata/device` | Device schema/metadata |
| GET | `/api/v1/metadata/user` | User metadata (app polls this heavily) |
| GET | `/api/v1/user/profile` | Account profile |
| GET | `/api/v1/notifications`, `/notifications/channels` | Notification config |

`/device/registry` returns each device with `serialNumber`, `name`, `model`, `generation`,
`swVersion`, `status.connection.online`, and a full `properties` object identical to
`/device/data`'s `datapoints`. **Polling registry alone is enough for a Home Assistant
integration** — one request yields device identity plus every sensor.

### Telemetry datapoints

    current_flow_rate                          gallons/min
    total_water_usage_today_tank_1 / _tank_2
    total_water_usage_since_install_tank_1 / _tank_2
    daily_usage_day_01 .. daily_usage_day_30   rolling 30-day history
    away_mode_water_use
    time_rem_in_position                       regeneration position timer
    flow_profile_r2_minutes .. r5_minutes
    rssi                                       device wifi signal

## Control — the write path

    POST /api/v1/device/command
    {
      "command":         "<verb>",
      "params":          { ... },
      "protocolVersion": 1,
      "requestId":       "CC-<ISO8601 with microseconds>-<8 hex chars>",
      "serialNumber":    "GBX1-0000AA000W000000000"
    }

    200 -> {"success": true, "data": {"requestId": str}}

The response only acknowledges the request; it does not carry the result. Confirm by polling
`/device/registry` or `/device/data` afterwards.

`requestId` is client-generated. Format observed: `CC-` + ISO-8601 timestamp + `-` + 8 hex chars.
Whether the server validates the format is untested — mirroring it is the safe choice.

### Command vocabulary

Extracted from the APK. Note the verbs are **multi-segment** (`bypass.timed.on`, not `bypass.set`) —
an earlier extraction that assumed a single dot plus a fixed suffix list missed the entire bypass
family. Match on `name(.segment){1,3}` when re-deriving this.

| Command | Params | Status |
|---|---|---|
| `telemetry.get` | `{}` | ✅ verified — forces a device poll |
| `salt.set` | `{"level": 25\|50\|75\|100}` | ✅ verified |
| `awayMode.set` | `{"active": 0\|1}` | ✅ verified |
| `bypass.timed.on` | `{"duration": 30\|60\|90\|120\|180}` | ✅ verified — minutes |
| `bypass.permanent.on` | `{}` | ✅ verified |
| `bypass.off` | `{}` | ✅ verified — cancels either bypass mode |
| `regen.set` | `{"type": 1\|2}` | ✅ verified — **regeneration** |
| `timeDate.set` | `{"dateTimeValue": "M-d-yyyy_HH:mm:ss"}` | ✅ verified — **sets the device clock** |
| `alarm.silence` | `{"days": N}` | ⚠ accepted, **effect unobservable** — see below |
| `awayMode.alert.clear` | `{}` | accepted, **effect unobservable** |
| `salt.slm.set` | `{}` | untested — salt level monitor trigger |
| `property.set` | `{"<property_name>": <value>}` | untested — generic write, Gbx2 only in the app |

All param shapes above are read from `AzureDeviceCommandFactory` in the decompiled app, not guessed.

⚠ **`alarm.silence` hardcodes `days: 7`.** The app offers no choice — `silenceAlert()` builds
`{"days": 7}` from a literal `const/4 v0, #int 7`. So invoking it suppresses alerts for a full
week, including real ones. Not a no-op probe.

`awayMode.alert.clear` and `salt.slm.set` both construct the command with Kotlin's
default-argument constructor and a null map, i.e. they genuinely send **no params**.

`property.set` is only ever called by `setBypassSchedule(dsn, property, DeviceBypassSchedule)`,
and that method lives on **`CulliganGbx2Device`** — a different model from the `gbx1` under test.
Its property-name argument is supplied by the caller and was not resolvable statically, so the
writable property namespace remains unknown.

#### `timeDate.set` — verified end to end

The app exposes **no UI** for this, but the command works. Shape taken from
`AzureDeviceCommandFactory.setDateTime(String dsn, LocalDateTime)` in the decompiled app:

    format pattern  "M-d-yyyy_HH:mm:ss"   -- NO leading zeros on month/day, 24h clock
    param key       "dateTimeValue"
    example         {"dateTimeValue": "8-10-2026_10:04:44"}

Confirmed on real hardware 2026-08-10: the softener's clock was ~2.7 years behind
(`last_power_up_time` reading `2023-11-06`). After sending `timeDate.set` and power-cycling,
the device stamped the new boot as `2026-08-10 10:12:00` — correct date and correct local time.

⚠ The clock change is **not observable without a reboot**. No datapoint exposes the device's
current time, and `last_power_up_time` / `last_regen_date_time_*` are historical stamps that do
not retroactively correct. A power cycle is the only way to confirm it took.

`set_device_time.py` in this directory implements it (dry-run by default; prompts for the
password via getpass and never stores it).

#### `regen.set` type mapping — confirmed by controlled test

A scheduled ("overnight") regen was triggered from the app, then an immediate one, and the
telemetry was correlated against both:

    14:46:30  {"type": 2}  ->  last_regen_trigger_tank_1  5 -> 11   (scheduled)
    14:47:02  {"type": 1}  ->  last_regen_trigger_tank_1  11 -> 10  (immediate)
                                time_rem_in_position 72, then 71, 70, 69 ... (cycle running)

    type 1 = IMMEDIATE regeneration   -> trigger code 10, starts the cycle now
    type 2 = SCHEDULED/delayed regen  -> trigger code 11

`time_rem_in_position` is a live minutes-remaining counter during an active cycle and is 0 when
idle — a good progress sensor.

⚠ `next_regen_date_time` did **not** change when the scheduled regen was set, and the date fields
read implausibly:

    next_regen_date_time        = 2024-01-08 02:00:00
    last_regen_date_time_tank_1 = 2023-11-06 03:36:00

…while a regeneration had actually completed minutes earlier, in 2026. Either these fields are
stale placeholders the firmware does not maintain, or the device's RTC is years behind — which
would explain the existence of `timeDate.set`. Do not build scheduling logic on these fields
without confirming against the app UI first.

Note `salt.set` was only ever sent at 25/50/75/100 by the app's UI. Whether intermediate values
are accepted is untested.

The bypass family being three separate verbs rather than one boolean is notable: `bypass.timed.on`
takes a duration, `bypass.permanent.on` does not, and `bypass.off` cancels either. An integration
should model bypass as a switch plus an optional duration rather than a plain toggle.

Related telemetry/UI field names found alongside these, useful for mapping sensors:

    last_regen_date_time_tank_1 / _tank_2      next_regen_date_time
    last_regen_trigger_tank_1 / _tank_2        bypass_schedule_advanced_*
    bypassMode        bypassSchedule           bypassDurationOptions

### Alarm / error datapoints

    salt_alarm_mode            chem_feed_alarm_capacity   external_filter_alarm_capacity
    days_in_error              system_error_bit_flags
    errors                     <- device-side error LOG, array of {num, date}

`errors` is the on-device fault history (10 entries retained on the unit under test), distinct
from `/device/state`'s `errors[]`, which is the server's live view and is normally empty. Good
material for a diagnostics sensor.

⚠ `alarm.silence` produced **no observable change** in any of these when sent with no active
alarm — `salt_alarm_mode` stayed 1 throughout. There is no `silence_until` or equivalent
datapoint, so whether a silence window is active cannot be read back. Combined with the absence
of an un-silence verb, this command is effectively **write-only and unverifiable**; avoid it in
an integration.

The app polls `telemetry.get` roughly every 10–20s while a device screen is open, which is a
reasonable cue for integration poll intervals.

### Other writes

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/api/v1/device/registry` | Device settings (e.g. rename) |
| PATCH | `/api/v1/user/account` | Account settings |
| POST/PUT/DELETE | `/api/v1/notifications` | Notification rules |
| POST | `/api/v1/notifications/channel/mobile` | Register push channel |

## This device

    serialNumber   GBX1-0000AA000W000000000
    model          GBX1 family  (app class: CulliganGbxDevice)
    hub            iot-eastus2-hub-main-production-us.azure-devices.net

The `GBX1` prefix matches `CulliganGbxDevice`. Sibling classes in the app — `CulliganGbx2Device`,
`CulliganAdvantageDevice`, `CulliganMonDevice`, `CulliganSroDevice`, `CulliganNovaDevice` — imply
the same API serves the whole product line, so an integration built here should generalise.

## Building on this

`/device/registry` polled on an interval gives every sensor in one call. `POST /device/command`
gives control. Auth is bearer + refresh. That is everything a Home Assistant integration needs, and
it is materially better than the existing community integration, which targets Ayla and never got
writes working.

Untested and worth confirming before relying on it: whether `expiresIn` is short enough to need
active refresh handling, whether the API rate-limits polling, and what `regen.set` takes as params.

## ⚠ Privacy note on the raw capture

`mitm/capture/flows.jsonl` contains live `accessToken` / `refreshToken` values and, from
`/device/registry`, the installation address, contact name, email, phone, dealer ID, account
number, and lat/lon. Treat it as a secrets file. `api-summary.md` and this document are redacted.
