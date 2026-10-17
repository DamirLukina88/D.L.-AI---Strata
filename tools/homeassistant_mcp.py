#!/usr/bin/env python3
"""tools/homeassistant_mcp.py - MCP server for Strata to control and query Home Assistant.

Speaks the Model Context Protocol (MCP, JSON-RPC 2.0 over stdin/stdout) following
protocol revisions 2025-06-18 / 2025-03-26 / 2024-11-05.

Tools provided to Strata:
- list_entities: List all devices/entities or filter by domain and search term.
- get_state: Inspect state, attributes, and last updated time for entity/entities.
- call_service: Call any Home Assistant service (turn on/off, set temperatures, etc.).
- toggle: Fast toggle for switches, lights, and plugs.
- render_template: Evaluate Jinja2 template against Home Assistant state.
- get_history: Retrieve state change history for an entity over recent hours.
- get_camera_snapshot: Grab a fresh snapshot image from a camera (Xiaomi, Bambu Lab, etc.).

Authentication:
Reads token and URL from:
1. --config / path /mnt/data/homeassistant/mcp_config.json
2. HASS_TOKEN and HASS_URL environment variables
3. --token and --url CLI arguments
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROTOCOL = "2025-06-18"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
VERSION = "1.0.0"
DEFAULT_CONFIG_PATH = Path("/mnt/data/homeassistant/mcp_config.json")
DEFAULT_HASS_URL = "http://127.0.0.1:8123"


def log(msg: str) -> None:
    """Print to stderr so stdout remains exclusively JSON-RPC."""
    print(f"[homeassistant-mcp] {msg}", file=sys.stderr, flush=True)


class HomeAssistantClient:
    """Direct HTTP REST client for Home Assistant."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        timeout: float = 15.0,
        raw_response: bool = False,
    ) -> Any:
        if not self.token:
            raise RuntimeError(
                "Home Assistant Long-Lived Access Token is not configured. "
                "Please generate a token in Home Assistant (Profile -> Security -> Long-Lived Access Tokens) "
                f"and save it to {DEFAULT_CONFIG_PATH} or set the HASS_TOKEN environment variable."
            )

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode("utf-8") if data is not None else None

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if raw_response:
                    return raw
                if not raw:
                    return {}
                text = raw.decode("utf-8", "replace")
                try:
                    return json.loads(text)
                except ValueError:
                    return text
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace") if e.fp else ""
            if e.code == 401:
                raise RuntimeError(
                    f"Home Assistant authentication failed (401 Unauthorized). "
                    f"Check that your Long-Lived Access Token in {DEFAULT_CONFIG_PATH} is valid."
                ) from None
            raise RuntimeError(f"Home Assistant API error {e.code} ({e.reason}): {err_body}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot connect to Home Assistant at {self.base_url}: {e.reason}. "
                "Ensure Home Assistant is running (systemctl status homeassistant)."
            ) from None

    def get_states(self) -> list[dict[str, Any]]:
        return self._request("/api/states")

    def get_state(self, entity_id: str) -> dict[str, Any]:
        return self._request(f"/api/states/{urllib.parse.quote(entity_id)}")

    def call_service(
        self, domain: str, service: str, service_data: dict[str, Any] | None = None
    ) -> Any:
        return self._request(
            f"/api/services/{urllib.parse.quote(domain)}/{urllib.parse.quote(service)}",
            method="POST",
            data=service_data or {},
        )

    def render_template(self, template: str) -> str:
        res = self._request("/api/template", method="POST", data={"template": template})
        if isinstance(res, str):
            return res
        return json.dumps(res, ensure_ascii=False)

    def get_history(self, entity_id: str, hours: float = 1.0) -> Any:
        start_time = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)
        ).isoformat()
        endpoint = f"/api/history/period/{urllib.parse.quote(start_time)}?filter_entity_id={urllib.parse.quote(entity_id)}"
        return self._request(endpoint)

    def get_camera_snapshot(self, entity_id: str) -> bytes:
        return self._request(
            f"/api/camera_proxy/{urllib.parse.quote(entity_id)}",
            raw_response=True,
            timeout=20.0,
        )


TOOLS_DEFINITIONS = [
    {
        "name": "list_entities",
        "description": (
            "List devices and entities from Home Assistant. "
            "Filter by domain (e.g. 'light', 'switch', 'sensor', 'camera', 'climate', 'fan', 'binary_sensor') "
            "or search query matching name or entity ID."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (e.g. 'light', 'switch', 'sensor', 'camera', 'climate').",
                },
                "search": {
                    "type": "string",
                    "description": "Optional search term to filter entity_id or friendly_name.",
                },
                "include_attributes": {
                    "type": "boolean",
                    "description": "Whether to include full attributes for each entity (default: false for compact summary).",
                },
            },
        },
    },
    {
        "name": "get_state",
        "description": "Get the detailed state, attributes, and last updated time for one or more entity IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Entity ID (e.g. 'light.living_room', 'sensor.bambu_a1_print_status', 'switch.relay_1').",
                }
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "call_service",
        "description": (
            "Call a Home Assistant service to control devices. "
            "Examples: domain='light', service='turn_on', service_data={'entity_id': 'light.desk', 'brightness': 200}; "
            "or domain='climate', service='set_temperature', service_data={'entity_id': 'climate.ac', 'temperature': 22}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Home Assistant service domain (e.g. 'light', 'switch', 'climate', 'media_player', 'cover', 'homeassistant').",
                },
                "service": {
                    "type": "string",
                    "description": "Service name to call (e.g. 'turn_on', 'turn_off', 'toggle', 'set_temperature', 'play_media').",
                },
                "service_data": {
                    "type": "object",
                    "description": "Parameters for the service call, typically including 'entity_id' and specific target values.",
                },
            },
            "required": ["domain", "service"],
        },
    },
    {
        "name": "toggle",
        "description": "Quickly toggle an entity (switch, light, fan, relay, plug).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Entity ID to toggle (e.g. 'switch.3d_printer_plug', 'light.office').",
                }
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "render_template",
        "description": "Evaluate a Jinja2 template against Home Assistant state (useful for complex queries and calculations).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "Jinja2 template string, e.g. \"{{ states('sensor.temperature') }}\" or \"{{ states.light | selectattr('state','eq','on') | list | count }}\".",
                }
            },
            "required": ["template"],
        },
    },
    {
        "name": "get_history",
        "description": "Retrieve state change history for an entity over the past N hours.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Entity ID to inspect history for.",
                },
                "hours": {
                    "type": "number",
                    "description": "Number of hours of history to query (default: 1.0, maximum: 24.0).",
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_camera_snapshot",
        "description": "Grab a fresh camera snapshot from a camera entity (e.g. Bambu Lab camera, Xiaomi printer monitoring camera).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Camera entity ID (e.g. 'camera.bambu_a1_camera', 'camera.xiaomi_camera_1').",
                },
                "save_path": {
                    "type": "string",
                    "description": "Optional local file path to save the JPEG snapshot to. If omitted, saves to a temporary snapshot file.",
                },
            },
            "required": ["entity_id"],
        },
    },
]


class HomeAssistantMcpServer:
    def __init__(self, client: HomeAssistantClient, out_stream):
        self.client = client
        self.out = out_stream
        self.write_lock = threading.Lock()

    def send(self, msg: dict[str, Any]) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self.write_lock:
            self.out.write(data)
            self.out.flush()

    def error(self, rid: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        rid = msg.get("id")

        if method == "initialize":
            req_proto = (msg.get("params") or {}).get("protocolVersion")
            chosen_proto = req_proto if req_proto in PROTOCOLS else PROTOCOL
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": chosen_proto,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "homeassistant-mcp",
                        "title": "Home Assistant MCP Server",
                        "version": VERSION,
                    },
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"tools": TOOLS_DEFINITIONS},
            }

        if method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            return self.dispatch_tool(rid, name, args)

        if rid is not None:
            return self.error(rid, -32601, f"Method not supported: {method}")
        return None

    def dispatch_tool(self, rid: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "list_entities":
                result_text = self.tool_list_entities(
                    domain=args.get("domain"),
                    search=args.get("search"),
                    include_attributes=bool(args.get("include_attributes", False)),
                )
            elif name == "get_state":
                result_text = self.tool_get_state(entity_id=str(args.get("entity_id", "")))
            elif name == "call_service":
                result_text = self.tool_call_service(
                    domain=str(args.get("domain", "")),
                    service=str(args.get("service", "")),
                    service_data=args.get("service_data") or {},
                )
            elif name == "toggle":
                result_text = self.tool_toggle(entity_id=str(args.get("entity_id", "")))
            elif name == "render_template":
                result_text = self.tool_render_template(template=str(args.get("template", "")))
            elif name == "get_history":
                result_text = self.tool_get_history(
                    entity_id=str(args.get("entity_id", "")),
                    hours=float(args.get("hours", 1.0)),
                )
            elif name == "get_camera_snapshot":
                result_text = self.tool_get_camera_snapshot(
                    entity_id=str(args.get("entity_id", "")),
                    save_path=args.get("save_path"),
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [{"type": "text", "text": f"error: unknown tool '{name}'"}],
                        "isError": True,
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                    "isError": False,
                },
            }
        except Exception as e:  # noqa: BLE001
            log(f"Tool {name} error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [{"type": "text", "text": f"error: {e!s}"}],
                    "isError": True,
                },
            }

    # ------------------ Tool Implementations ------------------

    def tool_list_entities(
        self, domain: str | None = None, search: str | None = None, include_attributes: bool = False
    ) -> str:
        states = self.client.get_states()
        filtered = []

        domain_lower = domain.lower().strip() if domain else None
        search_lower = search.lower().strip() if search else None

        for s in states:
            eid = s.get("entity_id", "")
            attrs = s.get("attributes") or {}
            friendly_name = attrs.get("friendly_name", "")

            if domain_lower:
                ent_domain = eid.split(".")[0].lower()
                if ent_domain != domain_lower:
                    continue

            if search_lower and (search_lower not in eid.lower()) and (search_lower not in friendly_name.lower()):
                continue

            if include_attributes:
                filtered.append(s)
            else:
                item = {
                    "entity_id": eid,
                    "state": s.get("state"),
                    "name": friendly_name,
                }
                if "unit_of_measurement" in attrs:
                    item["unit"] = attrs["unit_of_measurement"]
                if "device_class" in attrs:
                    item["device_class"] = attrs["device_class"]
                filtered.append(item)

        total_matching = len(filtered)
        log(f"list_entities: found {total_matching} matching entities")
        return json.dumps(
            {"count": total_matching, "entities": filtered},
            indent=2,
            ensure_ascii=False,
        )

    def tool_get_state(self, entity_id: str) -> str:
        if not entity_id:
            raise ValueError("entity_id is required")
        state = self.client.get_state(entity_id)
        return json.dumps(state, indent=2, ensure_ascii=False)

    def tool_call_service(
        self, domain: str, service: str, service_data: dict[str, Any]
    ) -> str:
        if not domain or not service:
            raise ValueError("domain and service are required")
        res = self.client.call_service(domain, service, service_data)
        return json.dumps(
            {
                "success": True,
                "message": f"Called {domain}.{service}",
                "result": res,
            },
            indent=2,
            ensure_ascii=False,
        )

    def tool_toggle(self, entity_id: str) -> str:
        if not entity_id:
            raise ValueError("entity_id is required")
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        res = self.client.call_service(domain, "toggle", {"entity_id": entity_id})
        return json.dumps(
            {
                "success": True,
                "message": f"Toggled {entity_id}",
                "result": res,
            },
            indent=2,
            ensure_ascii=False,
        )

    def tool_render_template(self, template: str) -> str:
        if not template:
            raise ValueError("template is required")
        return self.client.render_template(template)

    def tool_get_history(self, entity_id: str, hours: float = 1.0) -> str:
        if not entity_id:
            raise ValueError("entity_id is required")
        hours = max(0.1, min(24.0, hours))
        history = self.client.get_history(entity_id, hours=hours)
        return json.dumps(history, indent=2, ensure_ascii=False)

    def tool_get_camera_snapshot(self, entity_id: str, save_path: str | None = None) -> str:
        if not entity_id:
            raise ValueError("entity_id is required")
        image_bytes = self.client.get_camera_snapshot(entity_id)
        if not save_path:
            save_dir = Path("/mnt/data/homeassistant/snapshots")
            save_dir.mkdir(parents=True, exist_ok=True)
            clean_eid = entity_id.replace(".", "_")
            ts = int(time.time())
            save_path = str(save_dir / f"{clean_eid}_{ts}.jpg")

        target = Path(save_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)

        return json.dumps(
            {
                "success": True,
                "entity_id": entity_id,
                "saved_to": str(target),
                "bytes": len(image_bytes),
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            },
            indent=2,
        )

    def serve(self, in_stream) -> None:
        for raw in in_stream:
            line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send(self.error(None, -32700, "parse error"))
                continue

            if isinstance(msg, list):
                out = [r for r in (self.handle(m) for m in msg) if r is not None]
                if out:
                    data = (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8")
                    with self.write_lock:
                        self.out.write(data)
                        self.out.flush()
            else:
                resp = self.handle(msg)
                if resp is not None:
                    self.send(resp)


def load_config(config_file: Path | None = None) -> dict[str, str]:
    cfg: dict[str, str] = {
        "url": os.environ.get("HASS_URL", DEFAULT_HASS_URL),
        "token": os.environ.get("HASS_TOKEN", ""),
    }
    path = config_file or DEFAULT_CONFIG_PATH
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("url"):
                cfg["url"] = data["url"]
            if data.get("token"):
                cfg["token"] = data["token"]
        except (OSError, json.JSONDecodeError) as e:
            log(f"Warning: could not read config from {path}: {e}")
    return cfg


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Home Assistant MCP Server for Strata")
    parser.add_argument("--url", help="Home Assistant base URL (default: http://127.0.0.1:8123)")
    parser.add_argument("--token", help="Home Assistant Long-Lived Access Token")
    parser.add_argument("--config", help=f"Path to JSON config (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--test", action="store_true", help="Run self-test on tools/list and exit")
    args = parser.parse_args(argv)

    cfg_file = Path(args.config).resolve() if args.config else DEFAULT_CONFIG_PATH
    config = load_config(cfg_file)
    if args.url:
        config["url"] = args.url
    if args.token:
        config["token"] = args.token

    client = HomeAssistantClient(base_url=config["url"], token=config["token"])

    if args.test:
        print("[TEST] Initializing HomeAssistantMcpServer self-test...")
        print(f"[TEST] Target URL: {config['url']}")
        print(f"[TEST] Token configured: {'Yes (Length: ' + str(len(config['token'])) + ')' if config['token'] else 'No'}")
        print(f"[TEST] Tools registered: {len(TOOLS_DEFINITIONS)}")
        for t in TOOLS_DEFINITIONS:
            print(f"  - {t['name']}: {t['description'][:60]}...")
        return 0

    out_stream = sys.stdout.buffer
    sys.stdout = sys.stderr  # isolate JSON-RPC stream
    server = HomeAssistantMcpServer(client, out_stream)
    log(f"Server ready. Connecting to Home Assistant at {config['url']}")
    try:
        server.serve(sys.stdin.buffer)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
