# Changelog

All notable changes to this integration are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), newest first, and the
version numbers match `manifest.json`.

## [0.3.0] - 2026-09-04

Home Assistant **2026.3.0** is now the minimum. That is the first release which
serves an integration's own brand images, and this integration's icon and logo
ship in-repo; on anything older the icon was a placeholder.

### Added

- A repair for a wrong controller clock, one per softener, with a **Fix**
  button that sets the clock to Home Assistant's local time. It clears itself
  on the poll that shows the clock right or the softener gone, and stays open
  if the command is refused. Deleting the entry closes any repairs it raised.
- Device classes on the readings that had none: duration on the day and minute
  sensors, stored volume on the gallon readings. A household set to metric now
  sees these converted rather than raw gallons and days. *Average daily use*
  deliberately keeps none — it is gallons per day, and no volume device class
  means that.
- Manual device deletion. A softener the account no longer lists can be removed
  from the integration page; one the account still returns is refused, so a
  live device cannot be deleted from under its own entities.
- Every action, option and config-flow field, removal instructions, example
  automations, use cases and troubleshooting in the README.
- An offline validator (`tools/validate_local.py`) that checks the manifest,
  translations, icons, actions, exceptions and the quality scale against the
  pinned rule list, and refuses a rule filed `done` whose mechanism is not in
  the tree.

### Changed

- A softener that leaves the account is now removed on the poll that loses it.
  Previously that check ran once at setup, so a sold or re-registered unit kept
  its device and entities until the next restart. A failed poll still removes
  nothing: an empty result is a failed read, not an emptied account.
- Passwords are entered through a password field in every flow. Reconfigure no
  longer prefills the stored password; leave the field blank to keep it.
- Setup and poll failures are translated. `ConfigEntryAuthFailed`,
  `UpdateFailed` and every action error now carry a translation key instead of
  an English message assembled in code.
- The `/device/data` fallback for firmware that omits telemetry logs once when
  it starts failing and once when it recovers, instead of on every poll.
- The valve controller's firmware is reported as the device's software version,
  and the Wi-Fi module's firmware moved to diagnostics. It was previously
  reported as a hardware version, which it is not.
- Diagnostics now carry the connection state, model, both firmware versions,
  the capability verdicts with the readings behind each one and the derived
  health values, still with no credentials and no serial numbers.
- Commands go out one at a time per softener (`PARALLEL_UPDATES = 1` on the
  button, number and switch platforms); previously any number could be in
  flight at once.
- Entities take their icon from their device class where one fits; icons are
  kept only where several entities on a device page would otherwise look alike.

### Fixed

- The bypass switch read the raw datapoint for truthiness, so a telemetry value
  of `"0"` — this API returns numbers as strings on some fields — reported the
  house as bypassed. It now reads the number.
- *Regenerating* reported off when the softener had not sent its position timer
  at all. It reports unknown until the timer arrives.
- *Resin replacement due* no longer fires on a low-confidence trend, which is
  what the README always described.
- The reconfigure flow accepted credentials for a different account in one
  branch; it now aborts and asks you to add that account as its own entry.
- The second README inside the component folder, which shipped to every install
  and pointed at a protocol document that does not exist, is gone. The one at
  the repository root is the only one.

### Development

- The GitHub `Tests` workflow runs the Home Assistant suite, `mypy --strict`
  with Home Assistant installed, the offline validator and `ruff` on every
  push, and **fails under 95% test coverage**.
- `api.py` is covered against a local HTTP server, including the reactive
  re-authentication on 401 and its one-retry limit.
- `mypy` runs strict with nothing switched back off; the run is scoped to the
  integration by `pyproject.toml` rather than by a per-module relaxation.

Earlier in this version, before the work above: the integration was rebuilt to
the Integration Quality Scale — coordinator state moved onto `entry.runtime_data`,
actions registered once at component setup so an automation calling one while
the entry is unloaded gets a translated refusal, a reconfigure flow, and
accessory detection so a unit without an Aqua-Sensor, a second tank, a chemical
feed or an external filter no longer gets entities reporting zero (or, for
*Capacity remaining*, a confident negative number).

## [0.1.0] - 2026-08-12

First working version: cloud polling of `uniapi.culliganiot.com`, one device
per softener, the derived health metrics, the resin-life estimate, and the
controls and actions the Culligan Connect app exposes.
