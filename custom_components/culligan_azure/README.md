# Culligan (Azure) — Home Assistant integration

For Culligan softeners on the **Azure IoT / `culliganiot.com`** backend — the newer hardware that
the existing community integration (which targets Ayla) cannot talk to.

Protocol reverse-engineered from the Culligan Connect Android app; see `../../API.md`.

## What it gives you

**Sensors** — current flow rate, water used today and lifetime, average daily use, capacity
remaining, salt level and days remaining, regeneration progress and history, hardness setting,
Wi-Fi signal, fault-log summary.

**Health metrics** — the reason this exists. Raw telemetry looks fine in isolation; the ratios
between values are what reveal a misconfigured unit.

| Entity | What it tells you |
|---|---|
| Regeneration interval (actual) | How often it really cycles |
| Regeneration interval (expected) | How often its capacity and usage imply it should |
| Regeneration efficiency | actual ÷ expected, as a percentage |
| Excess regenerations per year | Cycles beyond what's needed — multiply by your salt dose |
| **Over-regenerating** (problem) | Fires when it cycles >2× more often than justified |
| **Controller clock wrong** (problem) | The controller clock is separate from the Wi-Fi module's NTP clock and nothing syncs it |
| **Service overdue** (problem) | Past 365 days since last service |
| **Fault present** (problem) | Active error flags, with the most frequent code as an attribute |

**Resin condition** — measured, not assumed.

| Entity | What it tells you |
|---|---|
| Capacity per regeneration | Gallons treated per cycle, right now |
| Resin capacity fade | Percent drop since tracking began |
| Resin life remaining | Years, extrapolated from the measured decline |
| **Resin replacement due** (problem) | Fires under one year remaining, on a confident trend only |

The device exposes no resin-life datapoint, so this is derived. Every poll records cumulative
treated volume and regeneration count; the difference between samples gives working capacity at
that moment:

    capacity_per_cycle = Δgallons / Δregenerations

A least-squares fit of that series against time gives the fade rate, extrapolated down to 60% of
the observed baseline. **This needs history** — roughly three weeks before it reports anything, and
it keeps narrowing for months. Until then the sensors are unavailable and the `status` attribute
says why (`insufficient_data`, `collecting`, `no_degradation_detected`, `low_confidence`).

It will not invent a number. A flat trend reports `no_degradation_detected` rather than claiming
infinite life, and counter resets from a firmware reflash are detected and skipped rather than
producing a nonsense negative.

History is persisted across restarts and thinned to one sample per day, capped at 400, dropping
from the middle so the oldest baseline and newest reading always survive.

**Controls** — away mode switch, bypass switch, salt level number, and buttons for regenerate now,
schedule regeneration, refresh telemetry, and sync controller clock.

**Services** — `culligan_azure.bypass_timed` (bypass for N minutes) and
`culligan_azure.set_clock`.

## Install

Copy `custom_components/culligan_azure/` into your Home Assistant `config/custom_components/`,
restart, then **Settings → Devices & Services → Add Integration → Culligan (Azure)** and sign in
with your Culligan Connect account.

## Design notes

**Auth.** The API returns `expiresIn: 3600` and then rejects the token after roughly 27 minutes.
Do not refresh on a timer. This integration re-authenticates reactively on `401 INVALID_TOKEN`,
which is what the app itself does — it never uses the refresh token at all.

**Polling.** One `GET /device/registry` per cycle returns the device list *and* all 182
telemetry datapoints, so a poll costs a single request. Default interval is 120s; the API is
undocumented and unmetered, so there is nothing to gain from hammering it.

**Commands acknowledge, they do not confirm.** A `200` from `/device/command` means the cloud
queued the request. It says nothing about whether the device acted. Every control here refreshes
afterwards so the entity reflects reality rather than intent.

**Bypass is three commands, not a boolean** — `bypass.permanent.on`, `bypass.timed.on` with a
duration, and `bypass.off`. The switch models permanent on/off; timed bypass is a service because
a duration cannot be expressed through a switch.

**The clock is write-only.** No datapoint reports the controller's current time, so a clock change
is invisible until the device next powers up. `last_power_up_time` is stamped at boot and is the
only way to verify it took.

## Caveats

- `total_capacity` is assumed to be gallons of treated water per cycle. That fits the observed
  values but is not confirmed against Culligan documentation. If it is actually grains, the
  expected-interval figure scales, but the actual-vs-expected comparison keeps its shape.
- The bypass switch reads `actual_state_dealer_bypass`, which was 0 throughout testing; no active
  bypass state was ever captured, so its state feedback is unproven.
- Tested against one `GBX1` (Smart HE 9"). Sibling device classes in the app
  (`Gbx2`, `Advantage`, `Mon`, `Sro`, `Nova`) suggest the API generalises, but that is untested.
