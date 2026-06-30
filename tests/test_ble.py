"""Tests for the on-demand BLE helper.

These exercise the command sequencing and retry logic without any real
Bluetooth by patching the connection step with a mock GATT client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.gardena_aquaprecise_ble.ble import (
    AquaPreciseBleDevice,
    AquaPreciseBleError,
)
from custom_components.gardena_aquaprecise_ble.const import (
    CHAR_DURATION_UUID,
    CHAR_POWER_UUID,
    CHAR_TRIGGER_UUID,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    client.write_gatt_char = AsyncMock()
    client.read_gatt_char = AsyncMock()
    client.disconnect = AsyncMock()
    client.pair = AsyncMock(return_value=True)
    return client


@pytest.fixture
def device() -> AquaPreciseBleDevice:
    return AquaPreciseBleDevice(MagicMock(), address=ADDRESS, name="Test")


async def test_start_sequence_writes_duration_trigger_then_power(device):
    client = _mock_client()
    with patch.object(device, "_connect", AsyncMock(return_value=client)):
        await device.async_start_watering(60)

    written = [(c.args[0], c.args[1]) for c in client.write_gatt_char.await_args_list]
    assert written == [
        (CHAR_DURATION_UUID, (60).to_bytes(4, "little")),
        (CHAR_TRIGGER_UUID, b"\x01"),
        (CHAR_POWER_UUID, b"\x01"),
    ]
    # The connection must always be released afterwards.
    client.disconnect.assert_awaited()


async def test_stop_writes_power_off(device):
    client = _mock_client()
    with patch.object(device, "_connect", AsyncMock(return_value=client)):
        await device.async_stop_watering()

    first = client.write_gatt_char.await_args_list[0]
    assert (first.args[0], first.args[1]) == (CHAR_POWER_UUID, b"\x00")


async def test_write_retries_after_a_transient_failure(device):
    client = _mock_client()
    # Fail the very first write, then let the retry attempt succeed.
    client.write_gatt_char.side_effect = [BleakError("boom"), None, None, None]
    with (
        patch.object(device, "_connect", AsyncMock(return_value=client)),
        patch(
            "custom_components.gardena_aquaprecise_ble.ble.asyncio.sleep",
            AsyncMock(),
        ),
    ):
        await device.async_start_watering(30)

    # 1 failed write + 3 writes on the successful retry.
    assert client.write_gatt_char.await_count == 4


async def test_write_raises_after_exhausting_retries(device):
    client = _mock_client()
    client.write_gatt_char.side_effect = BleakError("nope")
    with (
        patch.object(device, "_connect", AsyncMock(return_value=client)),
        patch(
            "custom_components.gardena_aquaprecise_ble.ble.asyncio.sleep",
            AsyncMock(),
        ),
        pytest.raises(AquaPreciseBleError),
    ):
        await device.async_stop_watering()


async def test_read_status_parses_power_and_battery(device):
    client = _mock_client()
    client.read_gatt_char.side_effect = [b"\x01", bytes([87])]
    with patch.object(device, "_connect", AsyncMock(return_value=client)):
        power, battery = await device.async_read_status()

    assert power is True
    assert battery == 87


async def test_read_status_tolerates_partial_failures(device):
    client = _mock_client()
    # Power read fails; battery still returns a value.
    client.read_gatt_char.side_effect = [BleakError("no power char"), bytes([42])]
    with patch.object(device, "_connect", AsyncMock(return_value=client)):
        power, battery = await device.async_read_status()

    assert power is None
    assert battery == 42
