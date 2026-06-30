"""Coordinator for the Gardena AquaPrecise BLE integration.

The coordinator owns the watering state. State is driven optimistically by the
commands we send (the device auto-stops after the requested duration, so we run
a local timer to flip the switch back off) and is periodically reconciled with
an on-demand read of the power + battery characteristics.

Crucially, polling never raises during setup: if the device can't be reached we
keep the last known state and simply report the update as failed. That is what
prevents the "setup stalls / unknown error" behaviour seen with the built-in
integration on this model.
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ble import AquaPreciseBleDevice, AquaPreciseBleError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AquaPreciseCoordinator(DataUpdateCoordinator[None]):
    """Manage state and BLE access for a single AquaPrecise."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: AquaPreciseBleDevice,
        duration_seconds: int,
        scan_interval: timedelta,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device.address}",
            update_interval=scan_interval,
        )
        self.entry = entry
        self.device = device
        self.duration_seconds = duration_seconds
        self.is_watering = False
        self.battery_level: int | None = None
        self._auto_off: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> None:
        """Reconcile state with the device on a schedule (best-effort)."""
        try:
            power, battery = await self.device.async_read_status()
        except AquaPreciseBleError as err:
            # Don't blow up setup or spam errors; just mark this poll failed.
            raise UpdateFailed(str(err)) from err

        if battery is not None:
            self.battery_level = battery
        # Only trust a confirmed power read when we're not mid auto-off window;
        # otherwise the optimistic timer is authoritative.
        if power is not None and self._auto_off is None:
            self.is_watering = power

    async def async_start_watering(self, seconds: int) -> None:
        """Send the start sequence and optimistically mark watering on."""
        await self.device.async_start_watering(seconds)
        self.duration_seconds = seconds
        self.is_watering = True
        self._schedule_auto_off(seconds)
        self.async_update_listeners()

    async def async_stop_watering(self) -> None:
        """Send the stop command and mark watering off."""
        await self.device.async_stop_watering()
        self.is_watering = False
        self._cancel_auto_off()
        self.async_update_listeners()

    @callback
    def _schedule_auto_off(self, seconds: int) -> None:
        """Flip the switch back off once the device's run time elapses."""
        self._cancel_auto_off()

        @callback
        def _auto_off(_now) -> None:
            self._auto_off = None
            if self.is_watering:
                _LOGGER.debug("Auto-off timer elapsed for %s", self.device.address)
                self.is_watering = False
                self.async_update_listeners()

        # Small grace period so we don't pre-empt the hardware.
        self._auto_off = async_call_later(self.hass, seconds + 5, _auto_off)

    @callback
    def _cancel_auto_off(self) -> None:
        """Cancel a pending auto-off timer."""
        if self._auto_off is not None:
            self._auto_off()
            self._auto_off = None

    @callback
    def async_shutdown_timers(self) -> None:
        """Cancel timers on unload."""
        self._cancel_auto_off()
