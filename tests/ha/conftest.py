"""Fixtures for the Home Assistant layer tests.

Kept in its own directory so the autouse fixture does not attach itself to the
pure-logic suites one level up, which need no Home Assistant.
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.culligan_azure.const import DOMAIN

EMAIL = "someone@example.com"
SERIAL = "GBX0001234"

# One device shaped the way /device/registry returns it: the telemetry is
# embedded under `properties` and the connection flag under `status`.
DEVICE = {
    "serialNumber": SERIAL,
    "name": "Softener",
    "model": "GBX",
    "properties": {
        "unit_type": "GBX",
        "current_flow_rate": 0,
        "water_today": 121,
        "water_lifetime": 984210,
        "capacity_remaining": 1450,
        "salt_level": 4,
        "hardness": 25,
        "total_regens": 768,
        "days_since_install": 765,
    },
    "status": {"connection": {"online": True}},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required for Home Assistant to load a custom component in tests."""
    return


@pytest.fixture
def config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "secret"},
    )
