"""tools/test_homeassistant_mcp.py - unit tests for tools/homeassistant_mcp.py.

    python3 -m unittest tools/test_homeassistant_mcp.py -v
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import homeassistant_mcp as M


class MockHomeAssistantHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress HTTP logging in tests

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-valid-token":
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"401: Unauthorized")
            return

        if self.path == "/api/states":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            mock_states = [
                {
                    "entity_id": "light.desk_lamp",
                    "state": "on",
                    "attributes": {"friendly_name": "Desk Lamp", "brightness": 255},
                },
                {
                    "entity_id": "sensor.bambu_a1_print_status",
                    "state": "RUNNING",
                    "attributes": {"friendly_name": "Bambu A1 Print Status", "progress": 82},
                },
                {
                    "entity_id": "camera.xiaomi_camera_1",
                    "state": "idle",
                    "attributes": {"friendly_name": "Xiaomi Printer Cam 1"},
                },
            ]
            self.wfile.write(json.dumps(mock_states).encode("utf-8"))
            return

        if self.path.startswith("/api/states/light.desk_lamp"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "entity_id": "light.desk_lamp",
                    "state": "on",
                    "attributes": {"friendly_name": "Desk Lamp", "brightness": 255},
                }).encode("utf-8")
            )
            return

        if self.path.startswith("/api/camera_proxy/camera.xiaomi_camera_1"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(b"\xff\xd8\xff\xe0mock_jpeg_bytes\xff\xd9")
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer test-valid-token":
            self.send_response(401)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        if self.path == "/api/services/light/turn_on" or self.path == "/api/services/light/toggle":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([{"entity_id": body.get("entity_id")}]).encode("utf-8"))
            return

        if self.path == "/api/template":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            tpl = body.get("template", "")
            self.wfile.write(f"evaluated: {tpl}".encode())
            return

        self.send_response(404)
        self.end_headers()


class TestHomeAssistantMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), MockHomeAssistantHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_handshake_and_tools_list(self):
        client = M.HomeAssistantClient(base_url=f"http://127.0.0.1:{self.port}", token="")
        out = io.BytesIO()
        server = M.HomeAssistantMcpServer(client, out)

        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
        res = server.handle(init_msg)
        self.assertEqual(res["id"], 1)
        self.assertEqual(res["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(res["result"]["serverInfo"]["name"], "homeassistant-mcp")

        ping_res = server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(ping_res["id"], 2)
        self.assertEqual(ping_res["result"], {})

        list_res = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
        self.assertEqual(list_res["id"], 3)
        tools = list_res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("list_entities", tool_names)
        self.assertIn("get_state", tool_names)
        self.assertIn("call_service", tool_names)
        self.assertIn("toggle", tool_names)
        self.assertIn("render_template", tool_names)
        self.assertIn("get_history", tool_names)
        self.assertIn("get_camera_snapshot", tool_names)

    def test_missing_token_returns_error_block(self):
        client = M.HomeAssistantClient(base_url=f"http://127.0.0.1:{self.port}", token="")
        out = io.BytesIO()
        server = M.HomeAssistantMcpServer(client, out)

        res = server.handle({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "list_entities", "arguments": {}},
        })
        self.assertTrue(res["result"]["isError"])
        self.assertTrue(res["result"]["content"][0]["text"].startswith("error: Home Assistant Long-Lived Access Token is not configured"))

    def test_tool_calls_with_valid_token(self):
        client = M.HomeAssistantClient(
            base_url=f"http://127.0.0.1:{self.port}", token="test-valid-token"
        )
        out = io.BytesIO()
        server = M.HomeAssistantMcpServer(client, out)

        # 1. list_entities
        res = server.handle({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "list_entities", "arguments": {"domain": "sensor"}},
        })
        self.assertFalse(res["result"]["isError"])
        data = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["entities"][0]["entity_id"], "sensor.bambu_a1_print_status")

        # 2. get_state
        res = server.handle({
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "get_state", "arguments": {"entity_id": "light.desk_lamp"}},
        })
        self.assertFalse(res["result"]["isError"])
        state = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(state["entity_id"], "light.desk_lamp")
        self.assertEqual(state["state"], "on")

        # 3. toggle
        res = server.handle({
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "toggle", "arguments": {"entity_id": "light.desk_lamp"}},
        })
        self.assertFalse(res["result"]["isError"])
        toggle_data = json.loads(res["result"]["content"][0]["text"])
        self.assertTrue(toggle_data["success"])

        # 4. render_template
        res = server.handle({
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {"name": "render_template", "arguments": {"template": "Hello {{ 1 + 1 }}"}},
        })
        self.assertFalse(res["result"]["isError"])
        self.assertIn("evaluated: Hello {{ 1 + 1 }}", res["result"]["content"][0]["text"])

        # 5. get_camera_snapshot
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tmp_path = tf.name
        try:
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {
                    "name": "get_camera_snapshot",
                    "arguments": {
                        "entity_id": "camera.xiaomi_camera_1",
                        "save_path": tmp_path,
                    },
                },
            })
            self.assertFalse(res["result"]["isError"])
            cam_data = json.loads(res["result"]["content"][0]["text"])
            self.assertTrue(cam_data["success"])
            self.assertEqual(Path(tmp_path).read_bytes(), b"\xff\xd8\xff\xe0mock_jpeg_bytes\xff\xd9")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

    def test_load_config_file(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
            json.dump({"url": "http://192.168.1.100:8123", "token": "custom-token-123"}, tf)
            tmp_cfg = tf.name
        try:
            cfg = M.load_config(Path(tmp_cfg))
            self.assertEqual(cfg["url"], "http://192.168.1.100:8123")
            self.assertEqual(cfg["token"], "custom-token-123")
        finally:
            Path(tmp_cfg).unlink()

    def test_area_registry_and_filtering(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir)
            (storage_path / "core.area_registry").write_text(
                json.dumps({
                    "data": {
                        "areas": [
                            {"id": "living_room", "name": "Living Room"},
                            {"id": "office", "name": "Office"},
                        ]
                    }
                }),
                encoding="utf-8",
            )
            (storage_path / "core.device_registry").write_text(
                json.dumps({
                    "data": {
                        "devices": [
                            {"id": "dev1", "name": "Desk Lamp Device", "area_id": "office"},
                            {"id": "dev2", "name": "Living Room Cam", "area_id": "living_room"},
                        ]
                    }
                }),
                encoding="utf-8",
            )
            (storage_path / "core.entity_registry").write_text(
                json.dumps({
                    "data": {
                        "entities": [
                            {"entity_id": "light.desk_lamp", "device_id": "dev1", "area_id": None},
                            {"entity_id": "camera.xiaomi_camera_1", "device_id": "dev2", "area_id": None},
                            {"entity_id": "sensor.bambu_a1_print_status", "device_id": None, "area_id": "office"},
                        ]
                    }
                }),
                encoding="utf-8",
            )

            client = M.HomeAssistantClient(
                base_url=f"http://127.0.0.1:{self.port}",
                token="test-valid-token",
                storage_dir=storage_path,
            )
            out = io.BytesIO()
            server = M.HomeAssistantMcpServer(client, out)

            # Test 1: Filter by area="Office"
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {"name": "list_entities", "arguments": {"area": "Office"}},
            })
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["count"], 2)
            eids = [e["entity_id"] for e in data["entities"]]
            self.assertIn("light.desk_lamp", eids)
            self.assertIn("sensor.bambu_a1_print_status", eids)
            self.assertEqual(data["entities"][0]["area"], "Office")

            # Test 2: Filter by area="living_room" (slug format)
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 21,
                "method": "tools/call",
                "params": {"name": "list_entities", "arguments": {"area": "living_room"}},
            })
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["entities"][0]["entity_id"], "camera.xiaomi_camera_1")
            self.assertEqual(data["entities"][0]["area"], "Living Room")
            self.assertEqual(data["entities"][0]["device_name"], "Living Room Cam")

            # Test 3: Search by device_name
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 22,
                "method": "tools/call",
                "params": {"name": "list_entities", "arguments": {"search": "Living Room Cam"}},
            })
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["entities"][0]["entity_id"], "camera.xiaomi_camera_1")

            # Test 4: get_state enriches area and device_name
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 23,
                "method": "tools/call",
                "params": {"name": "get_state", "arguments": {"entity_id": "light.desk_lamp"}},
            })
            self.assertFalse(res["result"]["isError"])
            state = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(state["area"], "Office")
            self.assertEqual(state["device_name"], "Desk Lamp Device")

    def test_outlet_power_enrichment_and_units(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir)
            (storage_path / "core.area_registry").write_text(
                json.dumps({"data": {"areas": [{"id": "office", "name": "Office"}]}}),
                encoding="utf-8",
            )
            (storage_path / "core.device_registry").write_text(
                json.dumps({
                    "data": {
                        "devices": [
                            {"id": "plug_dev", "name": "Printer Smart Plug", "area_id": "office"}
                        ]
                    }
                }),
                encoding="utf-8",
            )
            (storage_path / "core.entity_registry").write_text(
                json.dumps({
                    "data": {
                        "entities": [
                            {"entity_id": "switch.printer_socket", "device_id": "plug_dev", "area_id": None},
                            {"entity_id": "sensor.printer_power", "device_id": "plug_dev", "area_id": None},
                            {"entity_id": "sensor.printer_total_energy", "device_id": "plug_dev", "area_id": None},
                        ]
                    }
                }),
                encoding="utf-8",
            )

            client = M.HomeAssistantClient(
                base_url=f"http://127.0.0.1:{self.port}",
                token="test-valid-token",
                storage_dir=storage_path,
            )

            # Mock states directly on client
            client.get_states = lambda: [
                {
                    "entity_id": "switch.printer_socket",
                    "state": "on",
                    "attributes": {"friendly_name": "Printer Socket", "device_class": "outlet"},
                },
                {
                    "entity_id": "sensor.printer_power",
                    "state": "0.150",
                    "attributes": {"friendly_name": "Printer Power", "unit_of_measurement": "kW", "device_class": "power"},
                },
                {
                    "entity_id": "sensor.printer_total_energy",
                    "state": "4.21",
                    "attributes": {"friendly_name": "Printer Energy", "unit_of_measurement": "kWh", "device_class": "energy"},
                },
            ]

            out = io.BytesIO()
            server = M.HomeAssistantMcpServer(client, out)

            # Test list_entities on switch domain enriches outlet with power
            res = server.handle({
                "jsonrpc": "2.0",
                "id": 30,
                "method": "tools/call",
                "params": {"name": "list_entities", "arguments": {"domain": "switch"}},
            })
            self.assertFalse(res["result"]["isError"])
            data = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(data["count"], 1)
            plug_item = data["entities"][0]
            self.assertEqual(plug_item["entity_id"], "switch.printer_socket")
            self.assertEqual(plug_item["device_class"], "outlet")
            self.assertEqual(plug_item["power"], "0.150 kW")

            # Test get_state on switch enriches with power and total_energy
            client.get_state = lambda eid: {
                "entity_id": "switch.printer_socket",
                "state": "on",
                "attributes": {"friendly_name": "Printer Socket", "device_class": "outlet"},
            } if eid == "switch.printer_socket" else {
                "entity_id": eid,
                "state": "0.150" if "power" in eid else "4.21",
                "attributes": {"unit_of_measurement": "kW" if "power" in eid else "kWh"},
            }

            res = server.handle({
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "get_state", "arguments": {"entity_id": "switch.printer_socket"}},
            })
            self.assertFalse(res["result"]["isError"])
            plug_state = json.loads(res["result"]["content"][0]["text"])
            self.assertEqual(plug_state["power"], "0.150 kW")
            self.assertEqual(plug_state["total_energy"], "4.21 kWh")


if __name__ == "__main__":
    unittest.main()
