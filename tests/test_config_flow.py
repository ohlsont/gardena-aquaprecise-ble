"""Tests for the config flow: candidate scoring, discovery and pairing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.data_entry_flow import FlowResultType

from custom_components.gardena_aquaprecise_ble import config_flow as cf
from custom_components.gardena_aquaprecise_ble.const import (
    DOMAIN,
    GARDENA_MANUFACTURER_ID,
    SERVICE_UUID_MATCH,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


def _info(**overrides) -> SimpleNamespace:
    """Build a lightweight stand-in for a BluetoothServiceInfoBleak."""
    data = {
        "address": ADDRESS,
        "name": "AquaPrecise",
        "rssi": -60,
        "connectable": True,
        "service_uuids": [SERVICE_UUID_MATCH],
        "manufacturer_data": {GARDENA_MANUFACTURER_ID: b"\x00"},
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_score_rewards_a_full_match():
    # connectable(3) + name(4) + service uuid(5) + manufacturer(2)
    assert cf._score(_info()) == 14


def test_score_is_zero_for_an_unrelated_device():
    info = _info(
        connectable=False,
        name="Some Speaker",
        service_uuids=[],
        manufacturer_data={},
    )
    assert cf._score(info) == 0


def test_candidate_label_shows_address_and_rssi():
    cand = cf._Candidate(address=ADDRESS, name="AquaPrecise", rssi=-55, score=14)
    label = cand.label()
    assert ADDRESS in label
    assert "-55" in label


async def test_user_flow_aborts_when_nothing_is_discovered(hass, monkeypatch):
    monkeypatch.setattr(cf.bluetooth, "async_discovered_service_info", lambda *a, **k: [])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_creates_entry_on_successful_pairing(hass, monkeypatch):
    # Allow our lightweight namespace object through the isinstance gate.
    monkeypatch.setattr(cf, "BluetoothServiceInfoBleak", object)
    monkeypatch.setattr(cf.bluetooth, "async_discovered_service_info", lambda *a, **k: [_info()])
    monkeypatch.setattr(cf.bluetooth, "async_ble_device_from_address", lambda *a, **k: MagicMock())
    monkeypatch.setattr(cf.AquaPreciseBleDevice, "async_pair", AsyncMock(return_value=True))

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": ADDRESS})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["address"] == ADDRESS


async def test_user_flow_surfaces_pairing_failure(hass, monkeypatch):
    monkeypatch.setattr(cf, "BluetoothServiceInfoBleak", object)
    monkeypatch.setattr(cf.bluetooth, "async_discovered_service_info", lambda *a, **k: [_info()])
    monkeypatch.setattr(cf.bluetooth, "async_ble_device_from_address", lambda *a, **k: MagicMock())
    monkeypatch.setattr(
        cf.AquaPreciseBleDevice,
        "async_pair",
        AsyncMock(side_effect=cf.AquaPrecisePairingError("no chars")),
    )

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": ADDRESS})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "pairing_failed"}
