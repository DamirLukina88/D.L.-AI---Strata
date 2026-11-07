---
title: "Xiaomi 17 Ultra Live Sensor Streaming and Explorer"
type: decision
description: "Architecture for live streaming all 108 Xiaomi 17 Ultra sensors, flexible durations, and web UI explorer."
status: active
tags: [android, sensors, streaming, ray-web-ui, xiaomi]
created: 2026-11-07
updated: 2026-11-07
last_verified: 2026-11-07
---

# Xiaomi 17 Ultra Live Sensor Streaming and Explorer

## Context & Problem Statement

The user requested real-time inspection and streaming for all hardware and virtual sensors on their Xiaomi 17 Ultra (`2512BPNDAG`). Rather than a single-purpose activity metric (like jump tracking), the user required a comprehensive, live telemetry explorer across both the Ray Android companion app and the Ray Web UI. Specific requirements included:
- A general screen listing and streaming all sensors.
- Dual streaming modes: user-defined duration ($N$ seconds) or indefinite streaming running continuously until explicitly stopped.
- A prominent blue `(i)` button in a circle on the sensors panel header that opens an informative modal guide detailing the phone's sensor hardware suite and their functions.

## Architecture & Implementation

### 1. Android Sensor Engine (`PhoneSensorManager.kt`)
- **108 Sensor Handles:** Enumerates all hardware and composite sensors registered under Android `SensorManager`.
- **Streaming Modes:**
  - When `durationSec <= 0`, sets `streamEndWallMs = Long.MAX_VALUE` for indefinite background streaming.
  - When `durationSec > 0`, runs for the specified duration before unregistering listeners.
- **Zero Idle Drain:** Sensor listeners are completely unregistered when streaming stops.
- **Payload Structure:** Each sample packet pushed to `/v1/ray/phone/sensors/stream` contains:
  - Spirit level 2D orientation ($\pm 0.01^\circ$ pitch and roll).
  - 6-axis IMU acceleration ($a_x, a_y, a_z$) and g-force vector magnitude.
  - Live environmental sensors (barometer pressure in hPa, ambient light in lx).
  - Full `sensorsArr` array containing all 108 sensor objects (name, vendor, string type, wakeup flag, reporting mode, active status, and float values).

### 2. Ray Web UI & Mobile WebView (`serve/web/index.html` & `app.js`)
- **Sensors Panel Dialog (`#sensors-dialog`):** Accessible via `#code-sensors-btn` and `#monitor-open-sensors-btn`.
- **Info Button & Hardware Guide:**
  - `#sensor-info-btn`: Blue circle `(i)` button in dialog header.
  - `#sensor-info-modal`: Comprehensive modal explaining:
    - 6-Axis Motion & IMU (STMicro lsm6dsv).
    - 3-Axis Magnetometer (AKM ak0991x).
    - Barometric Altimeter (Bosch bmp5).
    - Spectral & Ambient Light (ams-OSRAM tcs3760).
    - Laser Distance / ToF (STMicro L8).
    - Xiaomi Context & Activity ASICs (pickup, motion detect, tilt, step detector).
- **Live Visualizations:**
  - 2D Spirit Level bubble canvas.
  - 6-Axis Motion oscilloscope with history trace.
  - Search filter and category chips (`all`, `active`, `motion`, `environment`, `heading`, `xiaomi`).
  - Live 108-sensor telemetry table updating at 5–10 Hz via `/v1/ray/phone/sensors/live`.

## Verification & Parity
- Verified custom-duration (4s) and indefinite streaming via test harness and live phone telemetry.
- Tested parity between phone native bridge (`RayNativeBridge.kt`) and HTTP REST endpoints.
- Confirmed dialog display, search filtering, and modal interaction on both desktop and mobile viewports.

## Sources

1. User, chat, 2026-11-07.
2. `tools/test_phone_tool_parity.py` and `tools/test_phone_mcp.py`.
