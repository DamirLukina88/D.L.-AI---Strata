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


if __name__ == "__main__":
    unittest.main()
