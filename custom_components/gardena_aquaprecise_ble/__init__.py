"""The Gardena AquaPrecise BLE integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .ble import AquaPreciseBleDevice
from .const import (
    CONF_ADDRESS,
    CONF_DURATION_MINUTES,
    CONF_NAME,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_DURATION_MINUTES,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_DURATION_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    PLATFORMS,
)
from .coordinator import AquaPreciseCoordinator

_LOGGER = logging.getLogger(__name__)


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp an int into [low, high]."""
    return max(low, min(high, value))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gardena AquaPrecise BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # The only legitimate reason to defer setup: no Bluetooth transport yet.
    # This resolves automatically once the ESPHome proxy (or local adapter)
    # comes online, and never hangs.
    if bluetooth.async_scanner_count(hass, connectable=True) == 0:
        raise ConfigEntryNotReady(
            "No connectable Bluetooth scanner available yet (waiting for adapter or proxy)."
        )

    address: str = entry.data[CONF_ADDRESS]
    name: str | None = entry.data.get(CONF_NAME)

    duration_minutes = _clamp(
        int(entry.options.get(CONF_DURATION_MINUTES, DEFAULT_DURATION_MINUTES)),
        MIN_DURATION_MINUTES,
        MAX_DURATION_MINUTES,
    )
    scan_minutes = _clamp(
        int(entry.options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)),
        MIN_SCAN_INTERVAL_MINUTES,
        MAX_SCAN_INTERVAL_MINUTES,
    )

    device = AquaPreciseBleDevice(hass, address=address, name=name)
    coordinator = AquaPreciseCoordinator(
        hass,
        entry,
        device,
        duration_seconds=duration_minutes * 60,
        scan_interval=timedelta(minutes=scan_minutes),
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Kick off the first read in the background so setup completes immediately
    # even if the device is momentarily unreachable.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), name=f"{DOMAIN}_first_refresh_{address}"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: AquaPreciseCoordinator | None = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.async_shutdown_timers()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Allow the device to be rediscovered after removal."""
    address = entry.data.get(CONF_ADDRESS)
    if address:
        bluetooth.async_rediscover_address(hass, address)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
