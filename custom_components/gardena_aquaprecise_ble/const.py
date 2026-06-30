"""Constants for the Gardena AquaPrecise BLE integration."""

from __future__ import annotations

DOMAIN = "gardena_aquaprecise_ble"

PLATFORMS = ["switch", "sensor"]

# Config / option keys
CONF_ADDRESS = "address"
CONF_NAME = "name"
CONF_PAIRED = "paired"
CONF_DURATION_MINUTES = "duration_minutes"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

# Watering duration bounds (minutes)
DEFAULT_DURATION_MINUTES = 5
MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 120

# How often we connect on-demand to read battery / confirm state (minutes)
DEFAULT_SCAN_INTERVAL_MINUTES = 10
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 240

# Entity services
SERVICE_START_WATERING = "start_watering"
SERVICE_STOP_WATERING = "stop_watering"

# --- GATT protocol (Gardena AquaPrecise, art. 16000-20 / 16001-20) ---------
# Advertised primary service used for discovery matching.
SERVICE_UUID_MATCH = "98bd0001-0b0e-421a-84e5-ddbf75dc6de4"

# Control characteristics.
#   Power:    write 0x01 to start, 0x00 to stop. Readable -> current on/off.
#   Duration: uint32 little-endian number of SECONDS (e.g. 60s -> 3c 00 00 00).
#   Trigger:  write 0x01 to arm the start sequence before writing power.
CHAR_POWER_UUID = "98bd0d11-0b0e-421a-84e5-ddbf75dc6de4"
CHAR_DURATION_UUID = "98bd0d13-0b0e-421a-84e5-ddbf75dc6de4"
CHAR_TRIGGER_UUID = "98bd0a17-0b0e-421a-84e5-ddbf75dc6de4"

# Standard Battery Service / Battery Level characteristic (0x180F / 0x2A19).
BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Gardena/Husqvarna BLE manufacturer id used as a soft discovery hint.
GARDENA_MANUFACTURER_ID = 1062

# Timeouts / retries (seconds)
CONNECT_TIMEOUT = 20
PAIRING_TIMEOUT = 30
RW_TIMEOUT = 10
WRITE_RETRIES = 2
