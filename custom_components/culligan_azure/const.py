"""Constants for the Culligan (Azure) integration."""

DOMAIN = "culligan_azure"
# Kept equal to manifest.json's version; tools/validate_local.py checks it.
VERSION = "0.3.0"

SERVICE_BYPASS_TIMED = "bypass_timed"
SERVICE_SET_CLOCK = "set_clock"

# Repair issue translation key. The issue id appends the serial so two
# softeners on one account each raise their own repair.
ISSUE_CLOCK_WRONG = "clock_wrong"


# The app polls telemetry every ~10-20s while a device screen is open. That is
# far more aggressive than a background integration needs, and this API is
# undocumented and unmetered -- be a good citizen. A softener's state changes on
# the order of minutes at most.
DEFAULT_SCAN_INTERVAL = 120
MIN_SCAN_INTERVAL = 30

MANUFACTURER = "Culligan"

# Capability overrides. The detector in capabilities.py decides automatically;
# these let a user whose unit it reads wrong force a group on or off.
CONF_FORCE_ON = "force_capabilities_on"
CONF_FORCE_OFF = "force_capabilities_off"

# Bypass durations the app itself offers, in minutes.
BYPASS_DURATIONS = [30, 60, 90, 120, 180]
DEFAULT_BYPASS_MINUTES = 30
