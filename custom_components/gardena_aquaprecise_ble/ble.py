"""Low-level BLE helper for the Gardena AquaPrecise.

All operations are *on-demand*: we connect, do the work, and disconnect again.
This keeps Bluetooth-proxy connection slots free and avoids fighting the
Gardena phone app for the device's single active connection. It also avoids the
long-lived coordinator connection that makes the official integration stall on
this model.
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    BATTERY_LEVEL_CHAR_UUID,
    CHAR_DURATION_UUID,
    CHAR_POWER_UUID,
    CHAR_TRIGGER_UUID,
    CONNECT_TIMEOUT,
    PAIRING_TIMEOUT,
    RW_TIMEOUT,
    WRITE_RETRIES,
)

_LOGGER = logging.getLogger(__name__)


class AquaPreciseBleError(Exception):
    """Base error for AquaPrecise BLE operations."""


class AquaPreciseNotInRange(AquaPreciseBleError):
    """Raised when no connectable BLE device is currently known to HA."""


class AquaPrecisePairingError(AquaPreciseBleError):
    """Raised when the device cannot be paired / its characteristics are missing."""


class AquaPreciseBleDevice:
    """Stateless helper that talks to one AquaPrecise over BLE."""

    def __init__(self, hass: HomeAssistant, address: str, name: str | None = None) -> None:
        """Initialise the helper for a given BLE address."""
        self.hass = hass
        self.address = address
        self.name = name

    def _get_ble_device(self) -> BLEDevice | None:
        """Return a connectable BLEDevice from HA's manager (local or proxy)."""
        return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)

    def signal_report(self) -> str:
        """Summarise which scanners currently see this device, and at what RSSI.

        Attached to connection failures so range/proxy problems are obvious from
        the logs alone — e.g. "seen only by a distant, non-connectable proxy at
        -94 dBm" tells you instantly it's a coverage problem, not a bug.
        """
        try:
            connectable_scanners = bluetooth.async_scanner_count(self.hass, connectable=True)
            # connectable=False so we also report passive-only scanners that can
            # see the device but can't be used to connect to it.
            devices = bluetooth.async_scanner_devices_by_address(
                self.hass, self.address, connectable=False
            )
        except Exception as err:  # diagnostics must never raise
            return f"signal report unavailable ({err})"

        if not devices:
            return (
                f"device not seen by any scanner right now; "
                f"{connectable_scanners} connectable scanner(s) online"
            )

        seen = []
        for dev in devices:
            rssi = getattr(dev.advertisement, "rssi", None)
            scanner = dev.scanner
            source = getattr(scanner, "name", None) or getattr(scanner, "source", "?")
            note = "" if getattr(scanner, "connectable", False) else " (non-connectable)"
            seen.append(f"{source}: {rssi} dBm{note}")
        return f"{connectable_scanners} connectable scanner(s) online; seen by [{'; '.join(seen)}]"

    async def _connect(self) -> BleakClient:
        """Establish a connection through the best available adapter/proxy."""
        ble_device = self._get_ble_device()
        if ble_device is None:
            raise AquaPreciseNotInRange(
                f"No connectable BLE device for {self.address}. "
                f"Is the Bluetooth proxy online and in range? [{self.signal_report()}]"
            )
        return await establish_connection(
            BleakClient,
            ble_device,
            self.name or self.address,
            timeout=CONNECT_TIMEOUT,
        )

    @staticmethod
    def _collect_char_uuids(client: BleakClient) -> set[str]:
        """Return the set of characteristic UUIDs exposed by the device."""
        available: set[str] = set()
        services = client.services
        if services is None:  # pragma: no cover - defensive for old bleak
            return available
        for service in services:
            for char in service.characteristics:
                available.add(char.uuid.lower())
        return available

    def _has_control_chars(self, client: BleakClient) -> bool:
        """Return True if the mandatory watering-control characteristics are present."""
        available = self._collect_char_uuids(client)
        required = {CHAR_DURATION_UUID, CHAR_TRIGGER_UUID, CHAR_POWER_UUID}
        missing = required - available
        if missing:
            _LOGGER.debug(
                "Missing control characteristics on %s: %s", self.address, sorted(missing)
            )
        return not missing

    async def async_pair(self) -> bool:
        """Best-effort pair/bond, used once during the config flow.

        Many setups (especially ESPHome Bluetooth proxies) either bond
        transparently or don't require an explicit OS-level bond at all. So the
        real success test is: *can we see and would we be able to use the
        control characteristics?* If yes, we treat the device as usable even if
        the explicit ``pair()`` call is unsupported or returns falsey.
        """
        client: BleakClient | None = None
        try:
            client = await self._connect()

            # Try an explicit bond, but never fail solely because it's
            # unsupported on this backend/proxy.
            try:
                result = await asyncio.wait_for(client.pair(), timeout=PAIRING_TIMEOUT)
                _LOGGER.debug("pair() on %s returned %r", self.address, result)
            except NotImplementedError:
                _LOGGER.debug(
                    "Explicit pairing not implemented for %s (proxy/backend)", self.address
                )
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug(
                    "Explicit pairing failed for %s: %s (will verify chars)", self.address, err
                )

            if self._has_control_chars(client):
                return True

            raise AquaPrecisePairingError(
                "Connected but the AquaPrecise watering characteristics were not "
                "found. Put the device in pairing mode (hold the button until the "
                "LED blinks) and make sure the Gardena app is disconnected, then "
                "retry."
            )
        except AquaPreciseBleError:
            raise
        except (BleakError, TimeoutError) as err:
            report = self.signal_report()
            _LOGGER.warning("Pairing connect failed for %s: %s [%s]", self.address, err, report)
            raise AquaPrecisePairingError(
                f"Could not connect to {self.address}: {err}. Ensure the device is "
                "in pairing mode, the phone app is disconnected, and the proxy is in "
                f"range. [{report}]"
            ) from err
        finally:
            await self._safe_disconnect(client)

    async def async_start_watering(self, seconds: int) -> None:
        """Run the start sequence: duration -> trigger -> power on."""
        duration = max(1, int(seconds))
        payload = duration.to_bytes(4, byteorder="little", signed=False)
        await self._write_with_retry(
            (
                (CHAR_DURATION_UUID, payload),
                (CHAR_TRIGGER_UUID, b"\x01"),
                (CHAR_POWER_UUID, b"\x01"),
            )
        )

    async def async_stop_watering(self) -> None:
        """Stop watering (power off)."""
        await self._write_with_retry(((CHAR_POWER_UUID, b"\x00"),))

    async def async_read_status(self) -> tuple[bool | None, int | None]:
        """Connect once and read (is_watering, battery_percent).

        Either value may be ``None`` if that read fails or is unsupported; the
        whole call raises only when the device cannot be reached at all.
        """
        client: BleakClient | None = None
        power: bool | None = None
        battery: int | None = None
        try:
            client = await self._connect()
            try:
                raw = await asyncio.wait_for(
                    client.read_gatt_char(CHAR_POWER_UUID), timeout=RW_TIMEOUT
                )
                if raw:
                    power = bytes(raw)[0] == 0x01
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Power read failed for %s: %s", self.address, err)

            try:
                raw = await asyncio.wait_for(
                    client.read_gatt_char(BATTERY_LEVEL_CHAR_UUID), timeout=RW_TIMEOUT
                )
                if raw:
                    battery = max(0, min(100, int(bytes(raw)[0])))
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Battery read failed for %s: %s", self.address, err)

            return power, battery
        finally:
            await self._safe_disconnect(client)

    async def _write_with_retry(self, writes: tuple[tuple[str, bytes], ...]) -> None:
        """Run a write sequence, reconnecting between attempts on failure."""
        attempts = WRITE_RETRIES + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await self._write_sequence(writes)
                return
            except AquaPreciseNotInRange:
                raise
            except (BleakError, TimeoutError) as err:
                last_error = err
                _LOGGER.warning(
                    "BLE write attempt %s/%s failed for %s: %s",
                    attempt,
                    attempts,
                    self.address,
                    err,
                )
                await asyncio.sleep(0.6)
        raise AquaPreciseBleError(
            f"BLE write to {self.address} failed after {attempts} attempts: "
            f"{last_error} [{self.signal_report()}]"
        )

    async def _write_sequence(self, writes: tuple[tuple[str, bytes], ...]) -> None:
        """Connect, perform the ordered writes, then disconnect."""
        client: BleakClient | None = None
        try:
            client = await self._connect()
            for char_uuid, payload in writes:
                _LOGGER.debug("Write %s -> %s on %s", payload.hex(), char_uuid, self.address)
                await asyncio.wait_for(
                    client.write_gatt_char(char_uuid, payload, response=True),
                    timeout=RW_TIMEOUT,
                )
        finally:
            await self._safe_disconnect(client)

    async def _safe_disconnect(self, client: BleakClient | None) -> None:
        """Disconnect without raising."""
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
                _LOGGER.debug("Disconnected from %s", self.address)
        except (BleakError, TimeoutError) as err:  # pragma: no cover
            _LOGGER.debug("Error during disconnect from %s: %s", self.address, err)
