# Culligan (Azure) — Home Assistant integration

[![Tests](https://github.com/heidrickla/ha-culligan-azure/actions/workflows/tests.yml/badge.svg)](https://github.com/heidrickla/ha-culligan-azure/actions/workflows/tests.yml)
[![Validate](https://github.com/heidrickla/ha-culligan-azure/actions/workflows/validate.yml/badge.svg)](https://github.com/heidrickla/ha-culligan-azure/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

Home Assistant integration for Culligan water softeners on the **Azure IoT /
`culliganiot.com`** backend — the newer hardware that the existing community
integration cannot reach.

## Why this exists

Culligan moved newer softeners off Ayla Networks and onto an Azure IoT Hub. The
established community integration targets Ayla, so on this hardware it simply
does not work — and Culligan publishes no API documentation for the replacement.

This integration talks to `uniapi.culliganiot.com`, the same REST API the
Culligan Connect app uses. The protocol was reverse-engineered from the Android
app; see [`docs/culligan_azure_api.md`](docs/culligan_azure_api.md) for the full
write-up.

**No local option exists.** The softener itself speaks MQTT over TLS directly to
an Azure IoT Hub and validates its certificate chain properly, so it cannot be
intercepted or redirected. It also exposes no open ports. Cloud polling is the
only integration point — that is a property of the hardware, not a shortcut
taken here.

## Supported devices

Any softener that appears in the Culligan Connect app and is served by
`uniapi.culliganiot.com`. Every device on the account becomes one Home
Assistant device; a softener added to the account later appears on the next
poll without a reload.

Tested against one **`GBX1` (Smart HE 9")**. Sibling device classes in the app
(`Gbx2`, `Advantage`, `Mon`, `Sro`, `Nova`) suggest the API generalises, but
that is untested. Reports from other models are welcome.

Accessories are detected from the telemetry. A unit reports the same datapoints
whether or not it has an Aqua-Sensor, a second tank, a chemical feed or an
external filter; the ones for absent hardware read zero. Entities that only mean
something with the hardware fitted are created only when it is detected, and
the [options](#options) can force a group on or off.

## What you get

### Sensors

| Entity | Unit | Notes |
|---|---|---|
| Current flow rate | gal/min | |
| Water used today | gal | |
| Water used lifetime | gal | Diagnostic |
| Average daily use | gal | |
| Capacity remaining | gal | Aqua-Sensor units only; see [known limitations](#known-limitations) |
| Working capacity | gal | Aqua-Sensor units only |
| Salt level | % | What you last told the unit; it has no salt sensor |
| Salt days remaining | d | |
| Regeneration time remaining | min | Counts down during a cycle |
| Days since last regeneration | d | |
| Last regeneration | timestamp | Stamped by the controller clock |
| Next regeneration | timestamp | Stamped by the controller clock |
| Regeneration interval (actual) | d | How often it really cycles |
| Regeneration interval (expected) | d | How often capacity and usage imply it should |
| Regeneration efficiency | % | actual ÷ expected |
| Excess regenerations per year | | Cycles beyond what is needed |
| Resin life remaining | years | Measured from capacity fade; see below |
| Resin capacity fade | % | Drop in gallons per cycle since tracking began |
| Capacity per regeneration | gal | Gallons treated per cycle, currently |
| Resin cycle age | years | Years of normal cycling the resin has experienced |
| Fault log entries | | Diagnostic |
| Days since service | d | Diagnostic |
| Hardness setting | gpg | Diagnostic |
| Wi-Fi signal | dBm | Diagnostic, **disabled by default** |
| Last power up | timestamp | Diagnostic, **disabled by default** |
| Regenerations lifetime | | Diagnostic, **disabled by default** |
| Capacity per regeneration (lifetime avg) | gal | Diagnostic, **disabled by default** |
| Aqua-Sensor ratio, Aqua-Sensor minimum | | Aqua-Sensor units only, diagnostic, **disabled by default** |

Disabled entities are still registered. Enable one from its entity settings
(Settings → Devices & services → the softener → the entity → the cog → Enabled).

### Binary sensors

| Entity | Class | Notes |
|---|---|---|
| Connected | connectivity | Diagnostic |
| Away mode | | |
| Regenerating | | On while the position timer runs; unknown until the unit reports it |
| Regeneration pending tonight | | |
| Aqua-Sensor auto rinse | | Aqua-Sensor units only, diagnostic |
| **Over-regenerating** | problem | Cycles more than twice as often as capacity and usage justify |
| **Fault present** | problem | Active error flags; most frequent code as an attribute |
| **Resin replacement due** | problem | Under one year of resin life on a confident trend |
| **Service overdue** | problem | Past 365 days since last service |
| **Controller clock wrong** | problem | The controller's clock is years out; see [troubleshooting](#troubleshooting) |

### Controls

| Entity | Type | What it does |
|---|---|---|
| Away mode | switch | Vacation mode on or off |
| Bypass | switch | Permanent bypass on or off. **While bypassed the house receives unsoftened water** |
| Salt level | number | Tell the unit how full the tank is after a refill: 0, 25, 50, 75 or 100 % |
| Regenerate now | button | Starts a cycle immediately. Uses salt and backwash water |
| Schedule regeneration | button | Regenerates at the next scheduled time |
| Refresh telemetry | button | Asks the unit to push fresh readings, then polls |
| Sync controller clock | button | Sets the controller clock to Home Assistant's local time |

Commands are acknowledged, not confirmed: a success from the cloud means it
queued the request, not that the device acted. Every control refreshes
afterwards so entities reflect what the device reports, not what was asked.

### Actions

Both actions name the softener by serial number. The serial is on the device
page in Home Assistant and in the Culligan Connect app.

**`culligan_azure.bypass_timed`** — bypass for a fixed number of minutes, after
which the unit returns to softening on its own. While bypassed the house
receives unsoftened water.

| Field | Required | Description |
|---|---|---|
| `serial_number` | yes | The softener's serial, e.g. `GBX1-0000AA000W000000000` |
| `duration` | yes | Minutes, 1 to 1440; default 30. The app offers 30, 60, 90, 120 or 180; other values are accepted by the API but unverified on hardware |

**`culligan_azure.set_clock`** — set the valve controller's clock to Home
Assistant's current local time. The controller keeps its own clock, separate
from the Wi-Fi module's NTP-synced one, and nothing else syncs it. The change is
not visible until the device next powers up.

| Field | Required | Description |
|---|---|---|
| `serial_number` | yes | The softener's serial |

## Health metrics

The raw telemetry never says anything is wrong. The *relationships* between
values do, and those are what this integration surfaces.

- **Regeneration efficiency** is the actual interval between regenerations
  divided by the interval capacity and usage imply. 100 % means the unit
  regenerates exactly as often as its capacity implies; below 100 % means it
  regenerates more often than needed and is wasting salt and backwash water.
- **Excess regenerations per year** counts the cycles beyond what capacity and
  usage imply. Multiply by your salt dose and backwash volume per cycle for the
  annual waste.
- **Over-regenerating** fires when the efficiency falls under 50 %. That is
  usually a hardness, resin-capacity or flow-meter configuration problem.
- **Resin cycle age** is the years of *normal* cycling the resin has
  experienced, from the regeneration count alone. Compare it with the
  `calendar_age_years` attribute: a higher value means the resin is being
  cycled harder than it should be. It covers osmotic shock and backwash
  attrition only; oxidation by chlorine scales with treated volume, which
  regeneration frequency does not change, so this is an upper bound on
  accelerated ageing, not a total.

A misconfigured softener regenerating five times more often than necessary looks
completely normal in the vendor app. It shows up here immediately.

### Resin life — measured, not assumed

The device exposes no resin-life datapoint, so this is derived from observed
capacity fade. Each poll records cumulative treated volume and regeneration
count; the difference between samples gives working capacity at that moment:

```
capacity_per_cycle = Δgallons / Δregenerations
```

A least-squares fit of that series against time gives the fade rate, extrapolated
to 60 % of the observed baseline.

**It needs history** — roughly three weeks before it reports anything, and it
keeps narrowing for months. Until then the resin sensors are unavailable and the
`status` attribute on *Resin life remaining* says why:

| `status` | Meaning |
|---|---|
| `insufficient_data` | Fewer samples than a fit needs |
| `collecting` | Samples exist but the span is too short to extrapolate |
| `invalid_baseline` | The earliest samples show zero or negative capacity; the history is unusable until it is reset |
| `no_trend` | The samples do not fit a line; keeps collecting |
| `no_degradation_detected` | A flat trend; the sensor stays unavailable rather than claiming infinite life |
| `low_confidence` | A trend, but a noisy one; *Resin replacement due* reads off on it, never on |
| `ok` | A confident measured trend |
| `at_end_of_life` | The measured capacity has reached the 60 % floor |

Counter resets from a firmware reflash are detected and skipped. History is
stored per config entry, thinned to one sample per day and capped at 400,
dropping from the middle so the oldest baseline and newest reading always
survive.

## Installation

**HACS** — add this repository as a custom repository (category: Integration),
install, restart Home Assistant.

**Manual** — copy `custom_components/culligan_azure/` into your
`config/custom_components/`, restart.

Then **Settings → Devices & services → Add integration → Culligan (Azure)**.

### Installation parameters

| Field | Description |
|---|---|
| Email | The email address of your Culligan Connect app account |
| Password | The password for that account |

The flow signs in and lists the account's devices before creating the entry, so
a wrong password, an unreachable API or an account with no softeners is reported
on the form. One entry per account; adding the same email twice is refused.

## Options

**Settings → Devices & services → Culligan (Azure) → Configure.**

| Option | Default | Description |
|---|---|---|
| Polling interval (seconds) | 120 | How often to poll the Culligan cloud, 30 to 3600. A softener changes slowly and the API is undocumented, so the default is deliberately gentle |
| Always show | none | Hardware groups to treat as fitted even when nothing in the telemetry says so: Aqua-Sensor, Second tank, Chemical feed, External filter |
| Never show | none | Hardware groups to hide even if detected. Takes precedence over Always show |

Detection reads a group as present as soon as any of its datapoints reports a
non-zero value, so the overrides are only for a unit the rule gets wrong.
Changing any option reloads the entry.

## Reconfiguring and re-authentication

**Reconfigure** (the entry's menu → Reconfigure) changes the password, or
corrects the email address, of the same account. Leave the password blank to
keep the stored one. Credentials for a different account are refused; add that
account as a new entry instead.

When Culligan rejects the stored credentials — after a password change, say —
the entry asks for the new password and reloads once it is accepted. Nothing
else needs to be done.

## Removing the integration

1. **Settings → Devices & services → Culligan (Azure)**, open the entry's menu
   and choose **Delete**. This removes the devices and entities and deletes
   the entry's resin-history store from `.storage`, so the measured resin
   trend is gone with it.
2. If you no longer want the code: in HACS, open Culligan (Azure) and choose
   **Remove**, or delete `config/custom_components/culligan_azure/` by hand.
   Restart Home Assistant.

Nothing is changed on the softener or in the Culligan account.

## How it updates

The integration polls. One `GET /device/registry` per cycle returns the device
list and all telemetry, so an update costs a single request; the default
interval is 120 seconds and the [options](#options) change it. Every control and
action triggers an extra poll after the command so the entity shows the device's
response.

Sign-in tokens are re-obtained when the API rejects one (it does so after
roughly 27 minutes despite advertising an hour), which is what the app itself
does. A rejected password stops polling and starts re-authentication.

## Examples

Salt is low:

```yaml
alias: Softener salt low
triggers:
  - trigger: numeric_state
    entity_id: sensor.softener_salt_days_remaining
    below: 7
actions:
  - action: notify.notify
    data:
      message: >
        The softener has {{ states('sensor.softener_salt_days_remaining') }}
        days of salt left.
```

Over-regenerating, which the vendor app never mentions:

```yaml
alias: Softener over-regenerating
triggers:
  - trigger: state
    entity_id: binary_sensor.softener_over_regenerating
    to: "on"
    for: "24:00:00"
actions:
  - action: persistent_notification.create
    data:
      title: Softener is over-regenerating
      message: >
        Regenerating every
        {{ states('sensor.softener_regeneration_interval_actual') }} days
        against an expected
        {{ states('sensor.softener_regeneration_interval_expected') }}.
        Check the hardness and capacity settings.
```

Bypass while the irrigation runs, using the action:

```yaml
alias: Bypass softener for irrigation
triggers:
  - trigger: state
    entity_id: switch.irrigation
    to: "on"
actions:
  - action: culligan_azure.bypass_timed
    data:
      serial_number: GBX1-0000AA000W000000000
      duration: 90
```

Entity ids follow the device name; these assume a softener named "Softener".

## Use cases

- Know when to buy salt from the days-remaining figure rather than by lifting
  the lid.
- Catch a unit that a dealer left over-regenerating, which costs salt and water
  every day and is invisible in the app.
- Bypass automatically for irrigation or pool filling so softened water is not
  wasted on the garden.
- Track resin condition over months and plan a resin change before hardness
  breakthrough.
- Keep the controller clock right, so regeneration happens at the programmed
  hour rather than whenever the drifted clock thinks 2 a.m. is.

## Known limitations

- **Cloud only.** The hardware offers no local interface; if Culligan's API is
  down or changes, so is this.
- **`total_capacity` is assumed to be gallons per cycle.** That fits the
  observed values but is not confirmed against Culligan documentation. If it is
  grains, the expected-interval figure scales, though the actual-vs-expected
  comparison keeps its shape.
- **Bypass state feedback is unproven.** The switch reads
  `actual_state_dealer_bypass`, which was 0 throughout testing; no active
  bypass was captured, so the reported state may lag or not change.
- **Capacity remaining needs an Aqua-Sensor.** Without one the controller's
  derived capacity is 0 and the datapoint reads negative (-515 gal on the test
  unit), so the entity is not created on such a unit.
- **The clock is write-only.** No datapoint reports the controller's current
  time; a clock change is invisible until the device next powers up.
- **Timestamps are the controller's.** Last and next regeneration are stamped by
  the controller clock, so they are only as right as that clock is.
- **Commands acknowledge, they do not confirm**, and durations other than the
  app's 30/60/90/120/180 minutes are unverified on hardware.
- **Salt level is an input.** The unit counts down from whatever you tell it;
  it has no salt sensor.
- **Tested against one model**; see [supported devices](#supported-devices).

## Troubleshooting

**"Invalid email or password."** The Culligan cloud rejected the sign-in. Try
the same credentials in the Culligan Connect app; if they work there, the API
returned an unexpected status. Enable debug logging and open an issue.

**"Could not reach the Culligan API."** Network or a Culligan outage. The
integration keeps retrying on its own; nothing to do unless it persists.

**"Sign-in worked but no devices are registered to this account."** The account
has no softener paired. Pair it in the Culligan Connect app first.

**The entry shows "Polling the Culligan cloud failed".** A poll failed and the
entry is retrying. If it lasts, check the app still works.

**Re-authentication keeps being requested.** The password changed, or Culligan
invalidated the session. Enter the current app password once.

**Capacity remaining, Working capacity or the Aqua-Sensor entities are missing.**
The unit reported no Aqua-Sensor readings, so those entities were not created.
If the hardware is fitted, add Aqua-Sensor under *Always show* in the options.

**Controller clock wrong is on.** Press *Sync controller clock* or call
`culligan_azure.set_clock`. The controller has no datapoint for its current
time, so the sensor clears only after the unit next powers up; the
`last_power_up_time` attribute shows the stamp it is judging by.

**Regenerating shows unknown.** The unit has not reported the position timer
yet. It becomes on or off with the next poll that includes it.

**Resin sensors are unavailable.** Expected for the first weeks; the `status`
attribute on *Resin life remaining* says which stage the history is at (see
[resin life](#resin-life--measured-not-assumed)).

**Wi-Fi signal is not there.** It is registered disabled; enable it from the
entity's settings.

**Debug logging.** Add to `configuration.yaml` and restart, or use *Enable debug
logging* on the integration page:

```yaml
logger:
  logs:
    custom_components.culligan_azure: debug
```

Download diagnostics from the integration page when opening an issue; they
contain no credentials or serial numbers.

## Development

```
python -m pytest tests/test_health.py tests/test_resin.py tests/test_capabilities.py -q
python -m pytest tests/ha -q      # needs pytest-homeassistant-custom-component, Linux
python -m mypy custom_components/culligan_azure
python tools/validate_local.py
```

The GitHub `Tests` workflow runs all four on every push, plus `ruff`. The
quality-scale status of every rule is in
[`quality_scale.yaml`](custom_components/culligan_azure/quality_scale.yaml).

## Disclaimer

Not affiliated with, endorsed by, or supported by Culligan. "Culligan" is used
only to identify the hardware this integration works with. The API is
undocumented and may change without notice.

## License

GPL-3.0 — see [LICENSE](LICENSE).
