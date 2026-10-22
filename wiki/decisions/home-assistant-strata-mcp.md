---
title: "Home Assistant Core Deployment and Strata MCP Integration"
type: decision
description: "Home Assistant Core on D disk (/mnt/data), systemd boot service, and Strata stdio MCP server for smart home control"
status: active
tags: [homeassistant, mcp, iot, systemd, strata]
created: 2026-10-17
updated: 2026-10-22
last_verified: 2026-10-17
---

# Home Assistant Core Deployment and Strata MCP Integration

## Summary

Home Assistant Core is installed on dedicated storage (`/mnt/data/homeassistant`), configured as an enabled systemd service starting on system boot, and integrated with Strata via an MCP server (`tools/homeassistant_mcp.py`).

## Context & Choices

1. **Storage & Runtime**:
   - Deployed to `/mnt/data/homeassistant/venv` using a standalone Python 3.13 environment managed by `uv`.
   - Configuration files stored in `/mnt/data/homeassistant/config`.
   - Service runs under user `damirl`.

2. **System Startup**:
   - Managed by `/etc/systemd/system/homeassistant.service` enabled on boot (`systemctl is-enabled homeassistant` -> `enabled`).
   - Listens on local port `8123`.

3. **IoT Integrations & Custom Components**:
   - `custom_components/hacs`: Home Assistant Community Store.
   - `custom_components/xiaomi_miot`: For the two Xiaomi Wi-Fi cameras monitoring 3D printers.
   - `custom_components/bambu_lab`: For Bambu Lab A1 3D printer telemetry and control.
   - Built-in `tuya` integration for Wi-Fi + Zigbee gateway and sensors.

4. **Strata MCP Server**:
   - Script: `tools/homeassistant_mcp.py` implementing stdio JSON-RPC 2.0 (protocol `2025-06-18`).
   - Registered in `~/.config/dl-ai/mcp.json` with `"surfaces": ["code"]` for on-demand use by D.L. CLI and the Code tab, leaving the General Chat tab completely isolated without tools. Documented in `tools/dl_sessiond.py` and `tools/dl_cli.py` (`/mcp`, `/help`).
   - Provides 7 tools: `list_entities`, `get_state`, `call_service`, `toggle`, `render_template`, `get_history`, `get_camera_snapshot`.
   - Credentials configured in `/mnt/data/homeassistant/mcp_config.json` (mode 600) and `wiki/private/.env` (`HASS_TOKEN`).
   - Tool calling is fully autonomous: Strata reads the dynamic MCP JSON schemas and executes calls in conversation context without requiring manual invocations.

5. **Smart Outlet Lighting & Area Intelligence (Options 2 & 3)**:
   - Problem: Tuya imported smart plugs powering room lights as `switch.*` with `device_class: "outlet"`, causing AI queries like "turn off living room lights" to miss them.
   - Solution (Option 2): Native `light.switch` wrappers configured in `/mnt/data/homeassistant/config/configuration.yaml`:
     * Living Room: `light.kitchen_lights`, `light.corner_light`, `light.metal_shelf_light`, `light.monitor_light`, `light.work_table_light` (moved from Office on 2026-10-22; its outlet device "Lantern", `switch.lantern_socket`, stays in Office)
     * Office: `light.printer_light_and_air_filtration_system`
   - WebSocket Entity Registry Area Assignment: Assigned `area_id` (`living_room` and `office`) to all wrapper lights via HA WebSocket API (`config/entity_registry/update`).
   - MCP Area Awareness (Option 3): Enhanced `tools/homeassistant_mcp.py`:
     * Added `AreaDeviceRegistry` caching HA `core.area_registry`, `core.device_registry`, and `core.entity_registry`.
     * Added `area` parameter to `list_entities` (matching room name or slug, e.g., `"Living Room"` or `"living_room"`).
     * Enriched all returned entities in `list_entities` and `get_state` with `"area"` and `"device_name"`.
     * Extended `search` query matching to check `area` and `device_name`.

6. **Gree Air Conditioner Integration (`climate.living_room_ac`)**:
   - Hardware: Gree AC on local Wi-Fi network at `192.168.3.17:7000` (MAC `50:2c:c6:6c:b6:25`, hardware ID `362001061665+U-W05TV2.06.bin`, catalog `gree`, firmware `V1.2.1`).
   - Protocol: Local encrypted UDP polling on port 7000 (`greeclimate` library).
   - Entities: `climate.living_room_ac`, `switch.c66cb625_panel_light`, `switch.c66cb625_quiet_mode`, `switch.c66cb625_fresh_air`, `switch.c66cb625_xtra_fan`.
   - Assigned to area: `Living Room`.

## Gotchas

1. **Xiaomi Camera Streaming (`chuangmi.camera.039c04`)**:
   - Xiaomi C200/C300 cameras transmit video exclusively through encrypted TUTK/Miss P2P tunnels directly to the Mi Home app. The camera firmware does not expose an unencrypted local RTSP/ONVIF server, and the MIoT spec has no continuous HLS feed.
   - `xiaomi_miot` camera entities check the Xiaomi Cloud for recorded motion alarm event clips (`get_alarm_eventlist`). If no motion events have been recorded in the past 7 days, Home Assistant reports the entity as `unavailable`.
   - PTZ rotation, 180° image rollover, indicator LED, and night vision modes are standard MIoT properties and work 100%.
   - In contrast, Bambu Lab A1 built-in cameras (`camera.a1_*_camera`) support native live video streaming inside Home Assistant out-of-the-box.

2. **Home Assistant YAML `light.switch` Platforms**:
   - `unique_id` is not supported on `light.switch` YAML entries; Home Assistant core generates entity registry entries without unique_id from the friendly name. Area assignment must be done either through UI, entity registry WebSocket API, or MCP metadata fallback.

3. **Wi-Fi Broadcast Drop on Gree AC Discovery**:
   - Standard Home Assistant Gree discovery broadcasts UDP packets to `192.168.3.255:7000`. Wi-Fi access points and routers commonly drop directed UDP broadcast packets to wireless clients.
   - Solution: Deployed `custom_components/gree` configured with direct unicast discovery target `192.168.3.17`, allowing instant discovery and persistent polling without relying on router broadcast forwarding.

4. **Trigger words loaded the server during code work (fixed 2026-10-21)**:
   - D.L. CLI's router turns this MCP on when a message matches one of its `triggers` (regexes in `~/.config/dl-ai/mcp.json`, case-insensitive `search`). The old list had bare words that hit everyday code: `ams` in "params" and "streams", `light` in "highlight" and "flight", `plug` in "plugin", `socket` in "websocket", `temperat` in the model's sampling temperature, `printer` in "pretty printer", `camera` in a game's camera (the CONTRA run). It had already stopped being on by default on 2026-10-20.
   - Now 34 patterns. Unambiguous words stay as whole words (Home Assistant, hass, Bambu, 3D print, filament, AMS unit/slot/tray/spool, Zigbee, Xiaomi, purifier, humidity, Gree, the Croatian words). Lights, cameras, plugs, sockets, printers, temperature and the air conditioners need context: a switching verb, on/off, a room, a snapshot or stream, a print word, or a room or sensor temperature. Game-camera and UI words (`camera position`, `light mode`) are excluded.
   - Backup of the old file: `mcp.json.bak-20261021-ha-triggers`. Test: class `HomeAssistantTriggers` in `tools/test_dl_mcp.py`, which reads this machine's config: 16 code phrases must not match and 19 smart-home requests must. It fails on the old config.

## Verification

- Automated test suite: `python3 -m unittest tools/test_homeassistant_mcp.py -v` (5 tests passing: handshake, error handling, tool dispatch, area registry & filtering, mock REST endpoints).
- Live HA MCP execution: Verified `list_entities(domain='light', area='Living Room')` returns all 4 living room lights, and `list_entities(domain='light', area='Office')` returns all 6 office lights.
- Live Climate query: `list_entities(domain='climate', area='Living Room')` returns `climate.living_room_ac` (`state: auto`, `current_temperature: 23°C`, `target_temperature: 25°C`).
- Non-light smart outlets preserved: `switch.pc_socket`, `switch.v11_charger_socket_1`, `switch.v13_charger_socket_1`, `switch.a1_a_socket_1`, and `switch.a1_b_socket_1` remain classified as outlets under `Office`.
- Syntax & config validation: Passed `/mnt/data/homeassistant/venv/bin/hass --script check_config -c /mnt/data/homeassistant/config`.

## Related

- [Home Assistant Core and Strata MCP Integration Plan](../artifacts/homeassistant-strata-core-plan.md)
- [Home Assistant Server and Session Tools Walkthrough](../artifacts/homeassistant-and-session-tools-walkthrough.md)
- [D.L. CLI On-Demand MCP Loading Plan](../artifacts/dl-cli-on-demand-mcp-plan.md)

## Sources

1. User, chat, 2026-10-17.
2. Strata MCP client: `serve/mcp.py`.
3. Configuration: `/mnt/data/homeassistant/config/configuration.yaml`.
4. Walkthrough artifact: `walkthrough.md`.
5. User, chat, 2026-10-21 ("Fix home assistant trigger").
6. User, chat, 2026-10-22 (move the work table light to the living room).
