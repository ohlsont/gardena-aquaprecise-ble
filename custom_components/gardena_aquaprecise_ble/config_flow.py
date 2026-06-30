"""Config flow for the Gardena AquaPrecise BLE integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .ble import AquaPreciseBleDevice, AquaPreciseBleError, AquaPrecisePairingError
from .const import (
    CONF_ADDRESS,
    CONF_DURATION_MINUTES,
    CONF_NAME,
    CONF_PAIRED,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    GARDENA_MANUFACTURER_ID,
    MAX_DURATION_MINUTES,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_DURATION_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    SERVICE_UUID_MATCH,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _Candidate:
    """A discovered BLE candidate."""

    address: str
    name: str
    rssi: int | None
    score: int

    def label(self) -> str:
        """Human-friendly dropdown label."""
        rssi = self.rssi if self.rssi is not None else "n/a"
        return f"{self.name} ({self.address}) · RSSI {rssi}"


def _score(info: BluetoothServiceInfoBleak) -> int:
    """Score how likely a discovered device is an AquaPrecise."""
    score = 0
    if info.connectable:
        score += 3
    name = (info.name or "").lower()
    if "aquaprecise" in name or "aqua precise" in name:
        score += 4
    if SERVICE_UUID_MATCH in {u.lower() for u in (info.service_uuids or [])}:
        score += 5
    if GARDENA_MANUFACTURER_ID in (info.manufacturer_data or {}):
        score += 2
    return score


class GardenaAquaPreciseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._candidates: dict[str, _Candidate] = {}
        self._address: str | None = None
        self._name: str | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return AquaPreciseOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle a device discovered by the Bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._upsert(discovery_info)
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "AquaPrecise"
        }
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user pick a discovered device."""
        self._collect()

        if not self._candidates:
            return self.async_abort(reason="no_devices_found")

        options = [
            selector.SelectOptionDict(value=address, label=cand.label())
            for address, cand in sorted(
                self._candidates.items(), key=lambda kv: kv[1].score, reverse=True
            )
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }
        )

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            cand = self._candidates.get(address)
            if cand is None or (
                bluetooth.async_ble_device_from_address(self.hass, address, connectable=True)
                is None
            ):
                return self.async_show_form(
                    step_id="user", data_schema=schema, errors={"base": "not_connectable"}
                )
            self._address = cand.address
            self._name = cand.name
            await self.async_set_unique_id(cand.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_pair()

        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_pair(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pair with the selected device, then create the entry."""
        assert self._address is not None
        errors: dict[str, str] = {}

        # The form is shown first (with instructions); pairing runs on submit
        # and on the automatic call that follows discovery selection.
        device = AquaPreciseBleDevice(self.hass, address=self._address, name=self._name)
        try:
            await device.async_pair()
        except AquaPrecisePairingError as err:
            _LOGGER.warning("Pairing failed for %s: %s", self._address, err)
            errors["base"] = "pairing_failed"
        except AquaPreciseBleError as err:
            _LOGGER.warning("Connection failed for %s: %s", self._address, err)
            errors["base"] = "cannot_connect"
        else:
            return self.async_create_entry(
                title=self._name or f"AquaPrecise {self._address}",
                data={
                    CONF_ADDRESS: self._address,
                    CONF_NAME: self._name or "AquaPrecise",
                    CONF_PAIRED: True,
                },
            )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"device": self._name or self._address},
        )

    def _collect(self) -> None:
        """Pull all currently discovered devices into the candidate map."""
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if isinstance(info, BluetoothServiceInfoBleak):
                self._upsert(info)

    def _upsert(self, info: BluetoothServiceInfoBleak) -> None:
        """Add/update a candidate if it scores as a plausible AquaPrecise."""
        score = _score(info)
        if score <= 0:
            return
        name = info.name or "Unknown BLE device"
        cand = _Candidate(address=info.address, name=name, rssi=info.rssi, score=score)
        existing = self._candidates.get(cand.address)
        if existing is None or cand.score >= existing.score:
            self._candidates[cand.address] = cand


class AquaPreciseOptionsFlow(config_entries.OptionsFlow):
    """Options: default watering duration and reconcile interval."""

    async def async_step_init(
        self, user_input: dict[str, int] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DURATION_MINUTES,
                    default=int(options.get(CONF_DURATION_MINUTES, DEFAULT_DURATION_MINUTES)),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_DURATION_MINUTES, max=MAX_DURATION_MINUTES),
                    cv.positive_int,
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES,
                    default=int(
                        options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=MAX_SCAN_INTERVAL_MINUTES),
                    cv.positive_int,
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
