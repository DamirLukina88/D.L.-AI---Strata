---
title: "Home Assistant Server and Session Tools Walkthrough"
type: artifact
description: "Walkthrough of Home Assistant Core deployment, IoT device integration, MCP server, autonomous session tools, and YOLO auto-continue"
status: active
tags: [walkthrough, homeassistant, mcp, cli, session]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Walkthrough: Home Assistant Core Server & Strata MCP Integration

Home Assistant Core has been deployed on dedicated D disk storage (`/mnt/data/homeassistant`), configured as an enabled systemd service that starts automatically on boot, bundled with custom integrations for IoT devices (HACS, Xiaomi Miot Auto, Bambu Lab), and fully integrated with Strata via a native Model Context Protocol (MCP) server. Autonomous session control tools and infinite YOLO auto-continue were added to the CLI and Web Code tab.

---

## What Was Done

```mermaid
flowchart TD
    subgraph Host["Linux Host (CachyOS)"]
        subgraph DataDrive["D Disk: /mnt/data/homeassistant"]
            VENV["Python 3.13 Virtual Environment<br/>(/mnt/data/homeassistant/venv)"]
            CONFIG["Home Assistant Core Config<br/>(/mnt/data/homeassistant/config)"]
            HACS_DIR["custom_components/<br/>• hacs<br/>• xiaomi_miot (Xiaomi Cameras)<br/>• bambu_lab (Bambu A1 Printers)"]
            MCP_CONF["mcp_config.json<br/>(URL & Token)"]
        end

        SYSTEMD["systemd Service<br/>(homeassistant.service)<br/>• Status: active (running)<br/>• Auto-start: enabled"] -->|Controls| VENV
        VENV --> CONFIG
        CONFIG --> HACS_DIR

        subgraph StrataApp["Strata AI Engine"]
            CONF["~/.config/dl-ai/mcp.json"]
            HUB["McpHub (tools/dl_mcp.py)"]
            MCP_SERVER["tools/homeassistant_mcp.py<br/>(7 Tools)"]
            CONF --> HUB
            HUB <-->|JSON-RPC 2.0 stdio| MCP_SERVER
        end

        MCP_SERVER <-->|REST API (:8123)| CONFIG
    end
```

### 1. Dedicated Home Assistant Core Installation
- Installed isolated Python 3.13 runtime via `uv` on `/mnt/data/homeassistant/venv`.
- Installed `homeassistant` (2026.2.3), `ffmpeg`, and `libjpeg-turbo`.
- Configuration storage resides on `/mnt/data/homeassistant/config`.

### 2. Auto-Start on System Boot
- Created systemd unit: `/etc/systemd/system/homeassistant.service`.
- Executed `systemctl enable --now homeassistant`.
- Verified status: `active (running)` and `enabled` to start automatically on boot.

### 3. IoT Components & HACS Installed
Downloaded and prepared in `/mnt/data/homeassistant/config/custom_components`:
- **HACS (Home Assistant Community Store)**: Installed via official release package.
- **Xiaomi Miot Auto (`xiaomi_miot`)**: For monitoring the 2 Xiaomi Wi-Fi cameras overlooking 3D printers.
- **Bambu Lab (`bambu_lab`)**: For real-time monitoring and control of Bambu Lab A1 3D printer(s).
- **Tuya (Built-in)**: Native Tuya integration for Wi-Fi Zigbee hub and sub-devices.

### 4. Strata Home Assistant MCP Server
Created `tools/homeassistant_mcp.py` implementing MCP protocol `2025-06-18` (standard stdio JSON-RPC 2.0).

**Exposed Tools**:
1. `list_entities`: Query all devices or filter by domain (`light`, `switch`, `sensor`, `camera`, `climate`, etc.) and search term.
2. `get_state`: Query live state, attributes, and last updated time for an entity.
3. `call_service`: Control any device via Home Assistant services (`turn_on`, `turn_off`, `set_temperature`, etc.).
4. `toggle`: Quick toggle for any switch, light, or plug.
5. `render_template`: Execute Jinja2 expressions dynamically against Home Assistant state.
6. `get_history`: Query state change history over recent hours.
7. `get_camera_snapshot`: Grab and save real-time JPEG snapshots from Xiaomi / Bambu Lab cameras.

### 5. Strata Configuration & General Chat Isolation
- Configured in `~/.config/dl-ai/mcp.json` with `"surfaces": ["code"]`.
- Removed `"mcp_servers"` block from `strata-coder-iq1_m.json` so the core inference server (`serve/server.py`) has 0 MCP servers.
- Modified `serve/web/app.js` to set `mcp: false` in `DEFAULTS` and force `body.strata_mcp = false` for the Chat tab.
- Tools remain exclusively available on-demand in the Code tab and D.L. CLI via `tools/dl_mcp.py`.

### 6. Autonomous Session Control Tools & YOLO Auto-Continue
- Added 4 session tools to `DL_TOOLS` & `DL_PLAN_TOOLS` in `tools/dl_cli.py`:
  - `save_chat` (saves session as Markdown to workspace),
  - `get_system_health` (returns live hardware health card with stripped ANSI),
  - `get_engine_status` (returns Strata engine and context status),
  - `clear_conversation` (resets session messages and context immediately).
- Dispatched in `tools/dl_cli.py` and `tools/dl_sessiond.py`.
- Conversational continuation (`"continue"`, `"keep going"`, `"go on"`, `"proceed"`) auto-translates to `/continue` in both CLI and Session Daemon.
- YOLO mode loops indefinitely past `DL_MAX_TURNS` without prompting the user.

---

## Verification & Test Results

### 1. Service & Networking Verification
- **Command**: `systemctl is-active homeassistant && systemctl is-enabled homeassistant`
- **Result**: `active` and `enabled`.
- **Port Check**: TCP port `8123` is actively listening and answering HTTP requests.

### 2. Automated Unit Tests
- `tools/test_homeassistant_mcp.py`: 4 tests passed.
- `tools/test_dl_session_tools.py`: 6 tests passed.
- `tools/test_dl_yolo_continue.py`: 2 tests passed.

### 3. Live Token Verification & Discovered Devices
- Long-Lived Access Token saved to `/mnt/data/homeassistant/mcp_config.json` (mode 600) and `wiki/private/.env` (`HASS_TOKEN`).
- Live discovery confirmed: 236 entities across 27 devices recognized.

---

## Operational Notes & Gotchas

1. **Xiaomi Camera Video Stream Protocol**:
   - Xiaomi cameras (`chuangmi.camera.039c04` C200/C300) use encrypted TUTK P2P UDP tunnels directly to the Xiaomi Home app, without native RTSP or open MIoT HLS streams. Home Assistant `camera.*_camera_control` entities only display recorded cloud motion clips, showing `unavailable` when no events occurred in 7 days. Controls (PTZ, night vision, 180° rollover) work 100%. Bambu Lab A1 cameras have native live RTSP/WebRTC streams operating in HA.
2. **Tool Calling vs Manual Typing**:
   - Model calls MCP and session tools autonomously based on JSON schemas; manual CLI commands are strictly optional for debugging.

---

## Related

- [Home Assistant Core Deployment and Strata MCP Integration](../decisions/home-assistant-strata-mcp.md)
- [Shared CLI Session Daemon for Web and Terminal](../decisions/shared-cli-session-daemon.md)
- [Home Assistant Core and Strata MCP Integration Plan](homeassistant-strata-core-plan.md)
- [Session Commands and Tools Implementation Plan](session-commands-and-tools-plan.md)

## Sources

1. Antigravity, conversation 47cce368-ea13-4d3f-901b-2a9f88797c15, 2026-10-17.
