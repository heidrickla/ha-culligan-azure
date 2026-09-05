"""Adding entities for softeners, and for hardware, that appear after setup."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CulliganConfigEntry, CulliganCoordinator


@callback
def async_add_new_devices(
    entry: CulliganConfigEntry,
    coordinator: CulliganCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[str], Iterable[Entity]],
) -> None:
    """Add entities for each serial, now and whenever a new one shows up.

    The account is re-read on every poll, so a softener added later appears
    without reloading the entry.
    """
    known: set[str] = set()

    @callback
    def _check() -> None:
        new = [s for s in (coordinator.data or {}) if s not in known]
        if not new:
            return
        known.update(new)
        entities: list[Entity] = []
        for serial in new:
            entities.extend(build(serial))
        if entities:
            async_add_entities(entities)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))


@callback
def async_remove_stale_devices(
    hass: HomeAssistant, entry: CulliganConfigEntry, coordinator: CulliganCoordinator
) -> None:
    """Drop devices for softeners no longer on the account.

    Only entries this integration owns, and only when the poll returned at
    least one device: an empty result is a failed read, not an emptied account.
    """
    serials = set(coordinator.data or {})
    if not serials:
        return
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        owned = {i for d, i in device.identifiers if d == DOMAIN}
        if owned and not owned & serials:
            devices.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


@callback
def async_track_stale_devices(
    hass: HomeAssistant, entry: CulliganConfigEntry, coordinator: CulliganCoordinator
) -> None:
    """Remove stale devices now and after every later poll.

    A softener sold, moved to another account or removed in the app leaves the
    account between polls, not at setup, so checking once at setup left the
    device page showing hardware that is gone until the next restart.
    """

    @callback
    def _check() -> None:
        async_remove_stale_devices(hass, entry, coordinator)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))


@callback
def async_add_capability_entities(
    entry: CulliganConfigEntry,
    coordinator: CulliganCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[str, set[str]], Iterable[Entity]],
) -> None:
    """Add entities per (serial, capability), now and as capabilities appear.

    Capabilities are re-detected on every poll, so a unit whose Aqua-Sensor was
    reading zero at setup - or one where a dealer fits the hardware later -
    gains its entities without the user reloading anything. Each pair is built
    once; nothing is ever added twice.
    """
    known: set[tuple[str, str]] = set()

    @callback
    def _check() -> None:
        entities: list[Entity] = []
        for serial, payload in (coordinator.data or {}).items():
            caps: set[str] = payload.get("capabilities") or set()
            # The empty string stands for "entities that need no capability",
            # so a serial with no accessories still gets its base entities once.
            for cap in {"", *caps}:
                if (serial, cap) in known:
                    continue
                known.add((serial, cap))
                entities.extend(build(serial, {cap} if cap else set()))
        if entities:
            async_add_entities(entities)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))
