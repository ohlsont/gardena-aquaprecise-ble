# Gardena AquaPrecise BLE — Home Assistant custom integration

A self-contained Home Assistant integration to control a **Gardena AquaPrecise**
solar-powered irrigation controller over **Bluetooth LE**, designed to work
through an **ESPHome Bluetooth proxy** (or a local adapter).

It exists because the built-in **Gardena Bluetooth** integration currently
**stalls during setup on the AquaPrecise**. The official integration connects,
then tries to read/write an "Aqua Contour" timestamp characteristic during its
first coordinator refresh; that read hangs over a proxy connection and Home
Assistant cancels the setup (`asyncio.CancelledError` → *"Setup of config entry
… cancelled"* / *"Unknown error occurred"*). See
[home-assistant/core#173562](https://github.com/home-assistant/core/issues/173562).

This integration takes a deliberately simpler, more robust approach:

- **On-demand connections only.** It connects, sends the command (or reads
  state), and disconnects. Nothing holds a proxy connection slot open, and it
  never fights the Gardena phone app for the device's single connection.
- **It never blocks setup on a device read.** State is reconciled in the
  background, so the entry always finishes setting up.
- **No timestamp characteristic is touched** — the exact thing that breaks the
  official integration.

> Control only. Watering **schedules/contours are configured in the Gardena
> app**, as the hardware requires. This integration gives you manual + automated
> start/stop, a default duration, and battery level — enough to drive watering
> from Home Assistant automations (weather, soil moisture, "mow → water", etc.).

---

## Supported devices

| Model | Article | Status |
|-------|---------|--------|
| Aqua Precise Overground | 16000-20 | Supported |
| Aqua Precise Underground | 16001-20 | Expected to work (same BLE protocol) |

Verified against AquaPrecise firmware around **1.1.5.0**. If your firmware
exposes different characteristic UUIDs, see *Troubleshooting → wrong/missing
characteristics*.

---

## Requirements

- Home Assistant **2024.8** or newer.
- The **Bluetooth** integration enabled.
- A **connectable** Bluetooth source within range of the AquaPrecise — an ESP32
  running the ESPHome Bluetooth proxy is ideal.

### ESPHome proxy config

Make sure your proxy uses **active** scanning and allows **connections**:

```yaml
esp32_ble_tracker:
  scan_parameters:
    active: true

bluetooth_proxy:
  active: true
```

Place the ESP32 close enough that the AquaPrecise shows an RSSI of roughly
**-75 dBm or better** in *Settings → Devices & services → Bluetooth → device
diagnostics*. A weak link is the most common cause of flaky writes.

---

## Installation

Because the original community repo is archived (and HACS refuses to add
archived repos), the most reliable path is a direct file copy. A HACS option is
included if you'd rather have managed updates.

### Option A — copy files (works with or without HACS, recommended)

1. Copy the folder
   `custom_components/gardena_aquaprecise_ble/`
   into your Home Assistant config directory so you end up with:
   `…/config/custom_components/gardena_aquaprecise_ble/`
   (use the Samba, File editor, or SSH add-on).
2. **Restart Home Assistant.**
3. Continue with **Pairing & adding** below.

### Option B — HACS custom repository (managed updates)

HACS custom repositories must point at a non-archived GitHub repo, so publish
this folder to your own GitHub first:

1. Create a new (public) GitHub repo, e.g. `gardena-aquaprecise-ble`, and push
   the contents of this folder to it.
2. *(optional)* edit `documentation` and `issue_tracker` in
   `custom_components/gardena_aquaprecise_ble/manifest.json` to point at your repo.
3. In Home Assistant: **HACS → ⋮ → Custom repositories**, paste your repo URL,
   category **Integration**, **Add**.
4. Install **Gardena AquaPrecise BLE** from HACS, then **restart Home Assistant**.

---

## Pairing & adding

Gardena devices only accept connections from Bluetooth adapters they've been
paired with, and they allow essentially **one active connection at a time**. Get
this right and setup is quick:

1. **Disconnect the phone app** — close the Gardena app and turn the phone's
   **Bluetooth off** (otherwise it holds the device's one connection).
2. **Put the AquaPrecise in pairing mode** — press/hold its button until the
   LED blinks.
3. In Home Assistant, the device is usually **auto-discovered** — look for a
   *Gardena AquaPrecise BLE* discovery card and click **Configure**.
   Otherwise: **Settings → Devices & services → Add integration → Gardena
   AquaPrecise BLE**, then pick the device from the list.
4. On the **Pair** step, submit. If it fails, re-enter pairing mode and submit
   again (the button just retries).

After it's added you'll get a `switch.<name>_watering` and a battery sensor.

---

## Entities

| Entity | Description |
|--------|-------------|
| `switch.<name>_watering` | Turn on = start watering for the default duration; turn off = stop. |
| `sensor.<name>_battery` | Battery level (%), if the device reports it. |

## Services

`gardena_aquaprecise_ble.start_watering` — start watering. Optional `minutes`
(1–120); omit to use the default duration.

```yaml
service: gardena_aquaprecise_ble.start_watering
target:
  entity_id: switch.aquaprecise_watering
data:
  minutes: 8
```

`gardena_aquaprecise_ble.stop_watering` — stop watering.

```yaml
service: gardena_aquaprecise_ble.stop_watering
target:
  entity_id: switch.aquaprecise_watering
```

### Example: water at sunrise unless it rained

```yaml
automation:
  - alias: Morning watering
    trigger:
      - platform: sun
        event: sunrise
    condition:
      - condition: numeric_state
        entity_id: sensor.rain_last_24h_mm
        below: 2
    action:
      - service: gardena_aquaprecise_ble.start_watering
        target:
          entity_id: switch.aquaprecise_watering
        data:
          minutes: 10
```

## Options

**Settings → Devices & services → Gardena AquaPrecise BLE → Configure**

- **Default watering duration (minutes)** — used when the switch is turned on or
  the service is called without `minutes`.
- **State refresh interval (minutes)** — how often the integration briefly
  connects to read battery + confirm watering state (default 10). Larger =
  fewer BLE connections.

---

## How it works (GATT protocol)

All UUIDs share the Gardena base `…-0b0e-421a-84e5-ddbf75dc6de4`.

| Purpose | UUID | Notes |
|---------|------|-------|
| Discovery service | `98bd0001-…` | Advertised; used to match the device. |
| Power | `98bd0d11-…` | Write `01` start, `00` stop. Read → current on/off. |
| Duration | `98bd0d13-…` | `uint32` little-endian **seconds** (e.g. 60 s → `3c 00 00 00`). |
| Trigger | `98bd0a17-…` | Write `01` to arm before starting. |
| Battery | `00002a19-…` | Standard Battery Level (service `0x180F`). |

**Start sequence:** write duration → write trigger (`01`) → write power (`01`).
**Stop:** write power (`00`). The device auto-stops when the duration elapses;
the integration mirrors that with a local timer so the switch flips back off.

---

## Troubleshooting

Enable debug logging (`configuration.yaml`, then restart):

```yaml
logger:
  default: info
  logs:
    custom_components.gardena_aquaprecise_ble: debug
```

- **"No AquaPrecise was found" / not discovered.** The phone app is probably
  holding the connection — turn the phone's Bluetooth off — and make sure the
  device is in pairing mode and not *ignored* in *Settings → Devices & services*
  (check the "Ignored"/"Discovered" filter).
- **Pairing fails / times out.** Re-enter pairing mode, confirm the phone is
  disconnected, and check RSSI. The ESP32 may need to be closer the first time
  it bonds.
- **Writes fail intermittently.** Almost always signal: move the proxy nearer,
  or add a second proxy. Each ESP32 proxy keeps up to ~3 connections; don't
  point many devices at one proxy.
- **Wrong/missing characteristics** (older/newer firmware). With debug logging
  on, the log lists which required UUIDs are missing. Compare against your
  device using *nRF Connect* (phone app) and adjust `CHAR_*` in
  `custom_components/gardena_aquaprecise_ble/const.py`.

---

## Credits

GATT protocol and discovery approach are based on the (now archived)
[`jonilala796/Gardena-AquaPrecise-BLE`](https://github.com/jonilala796/Gardena-AquaPrecise-BLE)
community integration, rebuilt here with on-demand connections and non-blocking
setup. Not affiliated with or endorsed by GARDENA / Husqvarna.
