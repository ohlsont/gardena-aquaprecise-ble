"""Sensor platform for the Gardena AquaPrecise BLE integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AquaPreciseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the battery sensor."""
    coordinator: AquaPreciseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AquaPreciseBatterySensor(entry, coordinator)])


class AquaPreciseBatterySensor(CoordinatorEntity[AquaPreciseCoordinator], SensorEntity):
    """Battery level reported by the AquaPrecise."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, coordinator: AquaPreciseCoordinator) -> None:
        """Initialise the battery sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Gardena",
            model="AquaPrecise",
        )

    @property
    def native_value(self) -> int | None:
        """Return the last known battery percentage."""
        return self.coordinator.battery_level

    @property
    def available(self) -> bool:
        """Available once we've ever read a battery value."""
        return self.coordinator.battery_level is not None
