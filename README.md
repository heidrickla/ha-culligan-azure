# Culligan (Azure) — Home Assistant integration

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

## What you get

**Sensors** — current flow rate, water used today and lifetime, average daily
use, capacity remaining, salt level and days remaining, regeneration progress
and history, hardness setting, Wi-Fi signal, fault-log summary.

**Controls** — away-mode and bypass switches, salt-level number, and buttons for
regenerate now, schedule regeneration, refresh telemetry and sync the controller
clock.

**Services** — `culligan_azure.bypass_timed` (bypass for N minutes) and
`culligan_azure.set_clock`.

### Health metrics

The raw telemetry never says anything is wrong. The *relationships* between
values do, and those are what this integration surfaces:

| Entity | What it tells you |
|---|---|
| Regeneration interval (actual) | How often it really cycles |
| Regeneration interval (expected) | How often its capacity and usage imply it should |
| Regeneration efficiency | actual ÷ expected, as a percentage |
| Excess regenerations per year | Cycles beyond what is needed |
| Resin cycle age | Years of *normal* cycling the resin has actually experienced |
| **Over-regenerating** | Fires when it cycles more than 2× more often than justified |
| **Controller clock wrong** | The valve controller's clock is separate from the Wi-Fi module's NTP clock, and nothing syncs it |
| **Service overdue** | Past 365 days since last service |
| **Fault present** | Active error flags, with the most frequent code as an attribute |

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
to 60% of the observed baseline.

**It needs history** — roughly three weeks before it reports anything, and it
keeps narrowing for months. Until then the sensors are unavailable and a `status`
attribute explains why. It will not invent a number: a flat trend reports
`no_degradation_detected` rather than claiming infinite life, and counter resets
from a firmware reflash are detected and skipped.

## Install

**HACS** — add this repository as a custom repository (category: Integration),
install, restart Home Assistant.

**Manual** — copy `custom_components/culligan_azure/` into your
`config/custom_components/`, restart.

Then **Settings → Devices & Services → Add Integration → Culligan (Azure)** and
sign in with your Culligan Connect account.

## Notes and caveats

**Token handling.** The API returns `expiresIn: 3600` and then rejects the token
after roughly 27 minutes. This integration ignores `expiresIn` and
re-authenticates reactively on `401 INVALID_TOKEN`, which is what the app itself
does — it never uses the refresh token at all.

**Polling.** One `GET /device/registry` per cycle returns the device list *and*
all telemetry, so an update costs a single request. Default interval is 120s.

**Commands acknowledge, they do not confirm.** A `200` from `/device/command`
means the cloud queued the request, not that the device acted. Every control
refreshes afterwards so entities reflect reality rather than intent.

**Bypass is three commands, not a boolean** — permanent-on, timed-on with a
duration, and off. The switch models permanent on/off; timed bypass is a service,
because a duration cannot be expressed through a switch.

**Tested against one `GBX1` (Smart HE 9").** Sibling device classes in the app
(`Gbx2`, `Advantage`, `Mon`, `Sro`, `Nova`) suggest the API generalises, but that
is untested. Reports from other models are welcome.

**`total_capacity` is assumed to be gallons per cycle.** That fits the observed
values but is not confirmed against Culligan documentation. If it is actually
grains, the expected-interval figure scales, though the actual-vs-expected
comparison keeps its shape.

## Disclaimer

Not affiliated with, endorsed by, or supported by Culligan. "Culligan" is used
only to identify the hardware this integration works with. The API is
undocumented and may change without notice.

## License

GPL-3.0 — see [LICENSE](LICENSE).
