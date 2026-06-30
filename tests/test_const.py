"""Sanity checks on the integration constants."""

from custom_components.gardena_aquaprecise_ble import const


def test_duration_bounds_are_consistent():
    assert (
        const.MIN_DURATION_MINUTES <= const.DEFAULT_DURATION_MINUTES <= const.MAX_DURATION_MINUTES
    )


def test_scan_interval_bounds_are_consistent():
    assert (
        const.MIN_SCAN_INTERVAL_MINUTES
        <= const.DEFAULT_SCAN_INTERVAL_MINUTES
        <= const.MAX_SCAN_INTERVAL_MINUTES
    )


def test_gardena_characteristics_share_the_vendor_base():
    base = "0b0e-421a-84e5-ddbf75dc6de4"
    for uuid in (
        const.SERVICE_UUID_MATCH,
        const.CHAR_POWER_UUID,
        const.CHAR_DURATION_UUID,
        const.CHAR_TRIGGER_UUID,
    ):
        assert len(uuid) == 36
        assert uuid == uuid.lower()
        assert uuid.endswith(base)
