"""Tests for the coordinator's optimistic watering state machine."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.gardena_aquaprecise_ble.ble import AquaPreciseBleError
from custom_components.gardena_aquaprecise_ble.coordinator import AquaPreciseCoordinator


def _mock_device() -> MagicMock:
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.async_start_watering = AsyncMock()
    device.async_stop_watering = AsyncMock()
    device.async_read_status = AsyncMock(return_value=(None, None))
    return device


def _coordinator(hass, device) -> AquaPreciseCoordinator:
    return AquaPreciseCoordinator(
        hass,
        MagicMock(),
        device,
        duration_seconds=300,
        scan_interval=timedelta(minutes=10),
    )


async def test_start_marks_on_and_auto_off_flips_it_back(hass):
    device = _mock_device()
    coord = _coordinator(hass, device)

    await coord.async_start_watering(2)
    assert coord.is_watering is True
    device.async_start_watering.assert_awaited_once_with(2)

    # Auto-off fires after the run time plus the 5s grace period.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=12))
    await hass.async_block_till_done()
    assert coord.is_watering is False


async def test_stop_marks_off_and_cancels_timer(hass):
    device = _mock_device()
    coord = _coordinator(hass, device)

    await coord.async_start_watering(60)
    await coord.async_stop_watering()
    assert coord.is_watering is False
    device.async_stop_watering.assert_awaited_once()


async def test_update_raises_update_failed_when_unreachable(hass):
    device = _mock_device()
    device.async_read_status = AsyncMock(side_effect=AquaPreciseBleError("offline"))
    coord = _coordinator(hass, device)

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_update_stores_battery_level(hass):
    device = _mock_device()
    device.async_read_status = AsyncMock(return_value=(None, 73))
    coord = _coordinator(hass, device)

    await coord._async_update_data()
    assert coord.battery_level == 73


async def test_confirmed_power_read_is_ignored_during_auto_off_window(hass):
    device = _mock_device()
    # Device momentarily reports off while our optimistic timer is still armed.
    device.async_read_status = AsyncMock(return_value=(False, None))
    coord = _coordinator(hass, device)

    await coord.async_start_watering(600)
    await coord._async_update_data()
    # The optimistic timer is authoritative until it elapses.
    assert coord.is_watering is True
