"""Diagnostics for the Gardena AquaPrecise BLE integration.

Download from Settings -> Devices & services -> Gardena AquaPrecise BLE ->
(device) -> Download diagnostics. Captures the current watering/battery state
plus a snapshot of which Bluetooth scanners can see the device and at what
RSSI — the data you need to tell a coverage problem from a real fault.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS, DOMAIN
from .coordinator import AquaPreciseCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: AquaPreciseCoordinator = hass.data[DOMAIN][entry.entry_id]
    address: str = entry.data[CONF_ADDRESS]

    scanners: list[dict[str, Any]] = []
    try:
        for dev in bluetooth.async_scanner_devices_by_address(hass, address, connectable=False):
            scanner = dev.scanner
            scanners.append(
                {
                    "source": getattr(scanner, "name", None) or getattr(scanner, "source", None),
                    "connectable": getattr(scanner, "connectable", None),
                    "rssi": getattr(dev.advertisement, "rssi", None),
                }
            )
    except Exception as err:  # diagnostics must never raise
        scanners = [{"error": str(err)}]

    return {
        "address": address,
        "state": {
            "is_watering": coordinator.is_watering,
            "battery_level": coordinator.battery_level,
            "default_duration_seconds": coordinator.duration_seconds,
            "last_update_success": coordinator.last_update_success,
        },
        "bluetooth": {
            "connectable_scanner_count": bluetooth.async_scanner_count(hass, connectable=True),
            "scanners_seeing_device": scanners,
        },
    }
