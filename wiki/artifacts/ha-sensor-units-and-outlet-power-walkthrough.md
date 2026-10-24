---
title: "Home Assistant Sensor Units & Smart Outlet Live Power Walkthrough"
type: artifact
description: "Walkthrough of resolving missing units (kWh, kW) on Home Assistant energy/power sensors and adding live outlet power monitoring to Strata MCP"
status: active
tags: [homeassistant, iot, sensors, power, energy, mcp]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Home Assistant Sensor Units & Smart Outlet Live Power Walkthrough

## Summary

This walkthrough documents the investigation, root causes, and fixes for missing measurement units (`kWh`, `kW`) on Home Assistant energy sensors and smart power outlets. It also details the addition of device-level sibling indexing to Strata's Home Assistant MCP server (`tools/homeassistant_mcp.py`), enabling live real-time power draw reporting on smart outlet switches.

## Root Causes

1. **Tuya Energy Sensors Missing Unit & Device Class**:
   Tuya smart plugs (`v13_charger`, `printer_light`, `monitor_light`, `a1_a`, `a1_b`) reported cumulative energy via data point `add_ele`, but Home Assistant's Tuya integration created entities with `unit_of_measurement: ""` or `null` and `device_class: null`. Without `unit_of_measurement: "kWh"` and `device_class: energy`, values displayed as bare numbers (e.g. `2.21`) and were excluded from Home Assistant's Energy Dashboard.
2. **Disabled Instantaneous Power Sensors**:
   All 7 instantaneous power sensors (`sensor.pc_power`, `sensor.v13_charger_power`, `sensor.printer_light_power`, `sensor.v11_charger_power`, `sensor.monitor_light_power`, `sensor.a1_a_power`, `sensor.a1_b_power`), along with their corresponding current (`sensor.*_current`) and voltage (`sensor.*_voltage`) sensors, were disabled by default by the Tuya integration (`disabled_by: "integration"`). Consequently, no states were recorded or exposed for active wattage.
3. **Power Outlets Missing Attached Power Draw**:
   In Home Assistant's domain model, switch entities (`switch.*_socket`) are binary actors (`on`/`off`) without scalar units. Strata's MCP server reflected only the switch state without correlating the active power sensor residing on the same physical device.

## Changes Implemented

### 1. Home Assistant Core Customization (`/mnt/data/homeassistant/config`)
- **`customize.yaml`**:
  Defined `unit_of_measurement: "kWh"`, `device_class: energy`, and `state_class: total_increasing` for:
  - `sensor.v13_charger_total_energy`
  - `sensor.printer_light_total_energy`
  - `sensor.monitor_light_total_energy`
  - `sensor.a1_a_total_energy`
  - `sensor.a1_b_total_energy`
- **`configuration.yaml`**:
  Included `customize.yaml` under `homeassistant:` (`customize: !include customize.yaml`).

### 2. Entity Registry Enablement Script (`tools/ha_enable_power_sensors.py`)
Automated WebSocket API script (`config/entity_registry/update`) executing against Home Assistant Core:
- Enabled all 7 power sensors (`disabled_by: null`) and configured native display unit conversion to **`kW`** (`options_domain="sensor"`, `options={"unit_of_measurement": "kW", "suggested_display_precision": 3}`).
- Enabled all 7 current sensors (`A`) and 7 voltage sensors (`V`).
- Updated entity registry metadata for the 5 total energy sensors (`unit_of_measurement: "kWh"`, `device_class: "energy"`).

### 3. Strata MCP Server (`tools/homeassistant_mcp.py`)
- **Device Sibling Indexing**: Updated `AreaDeviceRegistry` to build `_device_to_entities: dict[str, list[str]]` mapping each `device_id` to its child entity IDs, and added helper method `get_device_siblings(entity_id)`.
- **Outlet Power Enrichment**:
  - `tool_list_entities`: When listing switch entities with `device_class: "outlet"` or `switch.*_socket`, matches sibling power sensors from the state table and attaches `"power": "<value> kW"`.
  - `tool_get_state`: Querying an outlet switch now enriches the returned payload with its device's active `power` and `total_energy`.
- **Unit Sanitization**: Updated unit extraction logic to ignore empty string units (`unit = attrs.get("unit_of_measurement"); if unit: item["unit"] = unit`).

## Verification Results

### 1. Automated Test Suites
- `tools/test_homeassistant_mcp.py`: 6 tests passing, including `test_outlet_power_enrichment_and_units`.
- `tools/test_dl_mcp.py`: 43 tests passing.
- `/mnt/data/homeassistant/venv/bin/hass --script check_config -c /mnt/data/homeassistant/config`: Clean check (exit code 0).

### 2. Live Home Assistant Entity Verification
Live `/api/states` query confirms active values with units:
- `sensor.a1_a_power`: `0.251 kW` (`device_class: power`)
- `sensor.a1_a_total_energy`: `0 kWh` (`device_class: energy`)
- `sensor.a1_a_current`: `1.621 A` (`device_class: current`)
- `sensor.a1_a_voltage`: `233.1 V` (`device_class: voltage`)
- `sensor.printer_light_power`: `0.0157 kW` (`device_class: power`)
- `sensor.printer_light_total_energy`: `0.008 kWh` (`device_class: energy`)

### 3. Live Strata MCP Outlet Output
`get_state("switch.a1_a_socket_1")` returns:
```json
{
  "entity_id": "switch.a1_a_socket_1",
  "state": "on",
  "attributes": {
    "device_class": "outlet",
    "friendly_name": "Bottom A1 Printer smart outlet Socket 1"
  },
  "area": "Office",
  "device_name": "Bottom A1 Printer smart outlet",
  "power": "0.251 kW",
  "total_energy": "0 kWh"
}
```

## Related

- [Home Assistant Core Deployment and Strata MCP Integration](../decisions/home-assistant-strata-mcp.md)
- [Home Assistant Entity Area Script](ha-entity-area-script.md)

## Sources

1. User, chat, 2026-10-24.
2. Antigravity session d65c2925-6121-4781-be4b-02aad0bc62b3.
3. Home Assistant configuration: `/mnt/data/homeassistant/config/customize.yaml` and `configuration.yaml`.
4. Entity enablement script: `tools/ha_enable_power_sensors.py`.
5. Strata MCP server: `tools/homeassistant_mcp.py` and tests in `tools/test_homeassistant_mcp.py`.
