# Culligan Connect cloud API

Recovered from the Android app (`com.culligan.connect` 3.7.17, versionCode 264) by TLS
interception on an emulator with the mitmproxy CA in the system trust store; 398 flows in the
first capture.

Base URL: `https://uniapi.culliganiot.com`
App config: `https://static.culliganiot.com/appconfig/culligan-connect/appconfig.json`

The app does not pin certificates (OkHttp is bundled but `CertificatePinner` is never
configured) and declares no `networkSecurityConfig`, so a system-store CA is enough to intercept.

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

### Token lifetime

Measured across 900+ flows:

    14:17:27  POST /auth/login    -> 200, expiresIn 3600
    14:44:28  POST /device/command -> 401 {"success":false,"error":{"message":"INVALID_TOKEN"}}
    14:44:29  POST /auth/login    -> 200, resumes normally

- The API rejects a token after about 27 minutes, against the advertised 3600 s.
- The app never calls a refresh endpoint and never uses `refreshToken`. On 401 it re-POSTs
  `/auth/login` with the stored credentials.

The integration does the same: it holds the credentials, ignores `expiresIn`, and
re-authenticates on `401 INVALID_TOKEN`.

## Read endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/device/registry` | Device list including full telemetry; the one call an integration needs. No query params. |
| GET | `/api/v1/device/data?serialNumber=<dsn>` | Telemetry datapoints only. `serialNumber` is required. |
| GET | `/api/v1/device/state?serialNumber=<dsn>` | Connection and health: `connected`, heartbeat and event timestamps, `errors[]`, `alerts[]`. `serialNumber` is required. |
| GET | `/api/v1/metadata/device` | Device schema and metadata |
| GET | `/api/v1/metadata/user` | User metadata; the app polls it often |
| GET | `/api/v1/user/profile` | Account profile |
| GET | `/api/v1/notifications`, `/notifications/channels` | Notification config |

`/device/registry` returns each device with `serialNumber`, `name`, `model`, `generation`,
`swVersion`, `status.connection.online`, and a `properties` object identical to `/device/data`'s
`datapoints`. One request yields device identity and every sensor.

### Telemetry datapoints

    current_flow_rate                          gallons/min
    total_water_usage_today_tank_1 / _tank_2
    total_water_usage_since_install_tank_1 / _tank_2
    daily_usage_day_01 .. daily_usage_day_30   rolling 30-day history
    away_mode_water_use
    time_rem_in_position                       regeneration position timer
    flow_profile_r2_minutes .. r5_minutes
    rssi                                       device wifi signal

### Accessory datapoints, and detecting what is fitted

The controller reports the same ~182 datapoints whatever hardware is attached. Absent
accessories read 0, which is indistinguishable from a real zero until you know the group. On a
GBX1 (`GBX V3.08`) with none of these accessories, every group below reads zero:

    aquasensor_z_ratio_current_tank_1 / _tank_2    Aqua-Sensor conductivity ratio
    aquasensor_z_min_tank_1 / _tank_2              its running minimum
    aquasensor_auto_rinse_enabled                  Aqua-Sensor auto-rinse setting
    total_capacity_volume_tank_1 / _tank_2         capacity DERIVED from the sensor

    unit_status_tank_2, capacity_remaining_tank_2,
    total_water_usage_since_install_tank_2,
    days_since_last_regen_tank_2                   second tank (twin units)

    chem_feed_mode, chem_feed_capacity_remaining,
    chem_feed_alarm_capacity                       chemical feed

    external_filter_mode, external_filter_capacity_remaining,
    external_filter_alarm_capacity,
    filter_media_life, media_life_remaining        external filter

With no Aqua-Sensor the derived `total_capacity_volume_tank_1` is 0 and
`capacity_remaining_tank_1` reads negative (-515 on that unit). Anything built on that field is
gated on the sensor being present.

Not an accessory flag: `hardness_type` (0 on that unit) and `hardness_value` (10) are the
programmed influent-hardness path the controller uses instead of an Aqua-Sensor.
`accessories_enable_bit_flags` reads 0; its bit layout is not decoded.

`capabilities.py` implements the detection: a group is present when any of its datapoints is
present and non-zero, so hardware that reports real values is never hidden. The options flow can
force any group on or off.

## Control: the write path

    POST /api/v1/device/command
    {
      "command":         "<verb>",
      "params":          { ... },
      "protocolVersion": 1,
      "requestId":       "CC-<ISO8601 with microseconds>-<8 hex chars>",
      "serialNumber":    "GBX1-0000AA000W000000000"
    }

    200 -> {"success": true, "data": {"requestId": str}}

The response acknowledges the request and does not carry the result. Confirm by polling
`/device/registry` or `/device/data` afterwards.

`requestId` is client-generated: `CC-` + ISO-8601 timestamp + `-` + 8 hex chars. The integration
sends the same format.

### Command vocabulary

Extracted from the APK. The verbs are multi-segment (`bypass.timed.on`, not `bypass.set`); match
on `name(.segment){1,3}` when re-deriving them. Every param shape is read from
`AzureDeviceCommandFactory` in the decompiled app. Effects are as observed on a GBX1;
`salt.slm.set`'s is its name in the app.

| Command | Params | Effect |
|---|---|---|
| `telemetry.get` | `{}` | Forces a device poll |
| `salt.set` | `{"level": 25\|50\|75\|100}` | Sets the salt level the unit counts down from |
| `awayMode.set` | `{"active": 0\|1}` | Away mode off or on |
| `bypass.timed.on` | `{"duration": 30\|60\|90\|120\|180}` | Bypass for that many minutes |
| `bypass.permanent.on` | `{}` | Bypass until cancelled |
| `bypass.off` | `{}` | Cancels either bypass mode |
| `regen.set` | `{"type": 1\|2}` | Regeneration; types below |
| `timeDate.set` | `{"dateTimeValue": "M-d-yyyy_HH:mm:ss"}` | Sets the controller clock |
| `alarm.silence` | `{"days": N}` | Accepted; no datapoint shows the effect |
| `awayMode.alert.clear` | `{}` | Accepted; no datapoint shows the effect |
| `salt.slm.set` | `{}` | Salt level monitor trigger |
| `property.set` | `{"<property_name>": <value>}` | Accepted by the cloud; a gbx1 does not apply it |

`alarm.silence` hardcodes `days: 7`. `silenceAlert()` builds `{"days": 7}` from a literal
(`const/4 v0, #int 7`) and the app offers no choice, so sending it suppresses alerts, real ones
included, for a week.

`awayMode.alert.clear` and `salt.slm.set` construct the command with Kotlin's default-argument
constructor and a null map, so they send no params.

`property.set` is called only by `setBypassSchedule(dsn, property, DeviceBypassSchedule)` on
`CulliganGbx2Device`, a different model from the gbx1. Its property name comes from the caller
and is not resolvable statically, so the writable property namespace is not recoverable from the
app.

#### `property.set` on a gbx1

Writing the capacity datapoint, which read 0:

    POST /api/v1/device/command
    {"command": "property.set",
     "params": {"total_capacity_volume_tank_1": 2000},
     "protocolVersion": 1, "requestId": "CC-...", "serialNumber": "GBX1-..."}

    200 -> {"success": true, "data": {"requestId": "CC-..."}}

The endpoint rejects neither `property.set` for a gbx1 nor an unrecognised property name, and
the device does not apply the write. The datapoint still read 0 after 25 seconds, and at the next
regeneration the controller reset `capacity_remaining_tank_1` to -500 rather than the +1500 a
stored 2000-gallon capacity would give. That reset is computed by the controller, so it is where a
stored capacity would show.

The request mirrored the app's transport byte for byte: `User-Agent: okhttp/4.12.0`, the same
envelope and the same `requestId` format. The command is ignored, not malformed.

A 200 from `property.set` therefore carries no information; a write path on it needs the
datapoint to move. On this model `total_capacity_volume_tank_1` is derived, not stored: all four
`aquasensor_z_*` datapoints read 0, and on a Smart HE the Aqua-Sensor determines working
capacity.

#### `timeDate.set`

The app exposes no UI for this command. Shape from
`AzureDeviceCommandFactory.setDateTime(String dsn, LocalDateTime)`:

    format pattern  "M-d-yyyy_HH:mm:ss"   -- NO leading zeros on month/day, 24h clock
    param key       "dateTimeValue"
    example         {"dateTimeValue": "8-10-2026_10:04:44"}

On a GBX1 whose clock was about 2.7 years behind (`last_power_up_time` 2023-11-06), the device
stamped the next boot after `timeDate.set` and a power cycle with the correct local date and time.

No datapoint exposes the device's current time, and `last_power_up_time` and
`last_regen_date_time_*` are historical stamps that do not retroactively correct, so a clock
change shows only after a power cycle. The integration's `set_clock` action, *Sync controller
clock* button and clock repair send this command.

#### `regen.set` types

A scheduled ("overnight") regeneration was triggered from the app, then an immediate one, and the
telemetry correlated against both:

    14:46:30  {"type": 2}  ->  last_regen_trigger_tank_1  5 -> 11   (scheduled)
    14:47:02  {"type": 1}  ->  last_regen_trigger_tank_1  11 -> 10  (immediate)
                                time_rem_in_position 72, then 71, 70, 69 ... (cycle running)

    type 1 = IMMEDIATE regeneration   -> trigger code 10, starts the cycle now
    type 2 = SCHEDULED/delayed regen  -> trigger code 11

`time_rem_in_position` counts minutes remaining during a cycle and is 0 when idle.

`next_regen_date_time` did not change when the scheduled regeneration was set, and the date
fields read years in the past while a regeneration had completed minutes earlier:

    next_regen_date_time        = 2024-01-08 02:00:00
    last_regen_date_time_tank_1 = 2023-11-06 03:36:00

These fields are stamped by the controller clock, which on that unit was 2.7 years behind (see
`timeDate.set`). Scheduling logic built on them needs the clock set first.

The app's UI sends `salt.set` only at 25/50/75/100.

The bypass family is three verbs rather than one boolean: `bypass.timed.on` takes a duration,
`bypass.permanent.on` does not, and `bypass.off` cancels either. The integration models bypass as
a switch plus a timed action.

Related field names found alongside these:

    last_regen_date_time_tank_1 / _tank_2      next_regen_date_time
    last_regen_trigger_tank_1 / _tank_2        bypass_schedule_advanced_*
    bypassMode        bypassSchedule           bypassDurationOptions

### Alarm and error datapoints

    salt_alarm_mode            chem_feed_alarm_capacity   external_filter_alarm_capacity
    days_in_error              system_error_bit_flags
    errors                     <- device-side error LOG, array of {num, date}

`errors` is the on-device fault history (10 entries retained on a GBX1), distinct from
`/device/state`'s `errors[]`, the server's live view, which is normally empty.

`alarm.silence` sent with no active alarm changed none of these; `salt_alarm_mode` stayed 1.
There is no `silence_until` or equivalent datapoint and no un-silence verb, so a silence window
can be neither read back nor cancelled. The integration does not send it.

The app polls `telemetry.get` roughly every 10-20 s while a device screen is open.

### Other writes

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/api/v1/device/registry` | Device settings (e.g. rename) |
| PATCH | `/api/v1/user/account` | Account settings |
| POST/PUT/DELETE | `/api/v1/notifications` | Notification rules |
| POST | `/api/v1/notifications/channel/mobile` | Register push channel |

## Device identity

    serialNumber   GBX1-0000AA000W000000000   (format)
    model          GBX1 family  (app class: CulliganGbxDevice)
    hub            iot-eastus2-hub-main-production-us.azure-devices.net

The `GBX1` prefix matches `CulliganGbxDevice`. The app, which talks to this one API, also
carries `CulliganGbx2Device`, `CulliganAdvantageDevice`, `CulliganMonDevice`,
`CulliganSroDevice` and `CulliganNovaDevice`.

## Summary

`/device/registry` polled on an interval gives every sensor in one call, and
`POST /device/command` gives control. Auth is the login above, repeated on 401.

Raw captures are not in this repository: they carry live tokens and account details.
