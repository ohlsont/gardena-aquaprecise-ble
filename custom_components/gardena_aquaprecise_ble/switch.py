"""Switch platform for the Gardena AquaPrecise BLE integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import voluptuous as vol

from .const import (
    DOMAIN,
    MAX_DURATION_MINUTES,
    MIN_DURATION_MINUTES,
    SERVICE_START_WATERING,
    SERVICE_STOP_WATERING,
)
from .coordinator import AquaPreciseCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the watering switch and register entity services."""
    coordinator: AquaPreciseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AquaPreciseWateringSwitch(entry, coordinator)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_START_WATERING,
        {
            vol.Optional("minutes"): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_DURATION_MINUTES, max=MAX_DURATION_MINUTES),
            )
        },
        "async_start_watering_service",
    )
    platform.async_register_entity_service(SERVICE_STOP_WATERING, {}, "async_stop_watering_service")


class AquaPreciseWateringSwitch(CoordinatorEntity[AquaPreciseCoordinator], SwitchEntity):
    """Switch that starts/stops watering on the AquaPrecise."""

    _attr_has_entity_name = True
    _attr_name = "Watering"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, entry: ConfigEntry, coordinator: AquaPreciseCoordinator) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_watering"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Gardena",
            model="AquaPrecise",
        )

    @property
    def is_on(self) -> bool:
        """Return whether watering is currently active."""
        return self.coordinator.is_watering

    @property
    def available(self) -> bool:
        """Keep the control usable even when the last poll failed.

        The device is only reachable intermittently over BLE, but the user
        should always be able to issue a start/stop; failures surface as a
        clear error on the action instead of greying out the entity.
        """
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start watering for the configured default duration."""
        await self.coordinator.async_start_watering(self.coordinator.duration_seconds)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop watering."""
        await self.coordinator.async_stop_watering()

    async def async_start_watering_service(self, minutes: int | None = None) -> None:
        """Entity service: start watering, optionally for a specific duration."""
        seconds = minutes * 60 if minutes is not None else self.coordinator.duration_seconds
        await self.coordinator.async_start_watering(seconds)

    async def async_stop_watering_service(self) -> None:
        """Entity service: stop watering."""
        await self.coordinator.async_stop_watering()
