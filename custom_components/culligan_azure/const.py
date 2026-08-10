"""Constants for the Culligan (Azure) integration."""

DOMAIN = "culligan_azure"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

# The app polls telemetry every ~10-20s while a device screen is open. That is
# far more aggressive than a background integration needs, and this API is
# undocumented and unmetered -- be a good citizen. A softener's state changes on
# the order of minutes at most.
DEFAULT_SCAN_INTERVAL = 120
MIN_SCAN_INTERVAL = 30

MANUFACTURER = "Culligan"

# Bypass durations the app itself offers, in minutes.
BYPASS_DURATIONS = [30, 60, 90, 120, 180]
DEFAULT_BYPASS_MINUTES = 30
