"""Shared entity base for Culligan devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import CulliganCoordinator


class CulliganEntity(CoordinatorEntity[CulliganCoordinator]):
    """Base entity bound to one softener."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CulliganCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial

    @property
    def _entry(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._serial, {})

    @property
    def datapoints(self) -> dict[str, Any]:
        return self._entry.get("datapoints", {})

    @property
    def health(self) -> dict[str, Any]:
        return self._entry.get("health", {})

    @property
    def available(self) -> bool:
        return super().available and self._serial in (self.coordinator.data or {})

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._entry.get("device", {})
        dp = self.datapoints
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            manufacturer=MANUFACTURER,
            name=dev.get("name") or f"Culligan {self._serial}",
            model=dev.get("model") or dp.get("unit_type"),
            sw_version=dp.get("gbx_firmware_version"),
            hw_version=dp.get("wifi_module_fw_version"),
            serial_number=self._serial,
        )
