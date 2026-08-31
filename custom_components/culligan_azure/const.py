"""Constants for the Culligan (Azure) integration."""

DOMAIN = "culligan_azure"


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
