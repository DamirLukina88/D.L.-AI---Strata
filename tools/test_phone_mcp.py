#!/usr/bin/env python3
"""tools/test_phone_mcp.py - Unit tests for tools/phone_mcp.py.

Verifies:
1. Schema Integrity: all 12 tools match the MCP tool schema.
2. Tool Dispatch & Payload: JSON-RPC formats and argument handling.
3. Offline Phone Fallback: graceful, non-crashing responses when unreachable.
"""
import json
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import phone_mcp as M


class TestPhoneMcpServer(unittest.TestCase):
    def setUp(self):
        # Setup server instance with simulated offline environment
        self.server = M.PhoneMcpServer(base_url="http://127.0.0.1:9999", adb_enabled=False)

    def test_schema_integrity(self):
        """Test 1: Schema Integrity - all 12 tools match the MCP specification."""
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        res = self.server.handle(req)
        self.assertIn("result", res)
        tools = res["result"].get("tools", [])

        expected_tools = {
            "phone_toggle_torch",
            "phone_get_battery",
            "phone_set_volume",
            "phone_set_alarm",
            "phone_launch_app",
            "phone_get_recent_notifications",
            "phone_get_2fa_code",
            "phone_get_now_playing",
            "phone_control_media",
            "phone_camera_snap",
            "phone_get_last_photo",
            "phone_get_gallery_image",
            "phone_get_screen",
            "phone_play_music",
        }

        found_names = {t["name"] for t in tools}
        self.assertEqual(len(tools), 14, f"Expected 14 tools, got {len(tools)}: {found_names}")
        self.assertEqual(found_names, expected_tools, f"Missing tool declarations: {expected_tools - found_names}")

        for tool in tools:
            name = tool.get("name")
            self.assertTrue(name.startswith("phone_"), f"Tool name must start with 'phone_': {name}")
            self.assertTrue(bool(tool.get("description")), f"Tool {name} must have a description")
            schema = tool.get("inputSchema", {})
            self.assertEqual(schema.get("type"), "object", f"Tool {name} inputSchema must be type 'object'")
            self.assertIsInstance(schema.get("properties"), dict, f"Tool {name} inputSchema must have properties dict")

            # Check specific required fields
            if name == "phone_toggle_torch":
                self.assertIn("enabled", schema.get("required", []))
                self.assertEqual(schema["properties"]["enabled"]["type"], "boolean")
            elif name == "phone_set_volume":
                self.assertIn("stream", schema.get("required", []))
                self.assertIn("level", schema.get("required", []))
            elif name == "phone_set_alarm":
                self.assertIn("hour", schema.get("required", []))
                self.assertIn("minute", schema.get("required", []))
            elif name == "phone_launch_app":
                self.assertIn("package_or_name", schema.get("required", []))
            elif name == "phone_control_media":
                self.assertIn("action", schema.get("required", []))

    def test_tool_dispatch_and_payload(self):
        """Test 2: Tool Dispatch & Payload - verify JSON-RPC format and routing."""
        # Create a mock server that simulates active companion replies
        mock_server = M.PhoneMcpServer(base_url="http://127.0.0.1:9999", adb_enabled=False)
        mock_server.is_companion_connected = lambda: True
        mock_server._call_companion_api = lambda tool, args, timeout=6.0: f"MockExecuted: {tool} with {json.dumps(args)}"

        test_cases = [
            ("phone_toggle_torch", {"enabled": True}),
            ("phone_get_battery", {}),
            ("phone_set_volume", {"stream": "media", "level": 12}),
            ("phone_set_alarm", {"hour": 7, "minute": 30, "label": "Morning Workout"}),
            ("phone_launch_app", {"package_or_name": "spotify"}),
            ("phone_control_media", {"action": "play"}),
            ("phone_camera_snap", {"prompt": "inspect desk"}),
            ("phone_get_screen", {}),
        ]

        for i, (tool_name, args) in enumerate(test_cases, start=10):
            req = {
                "jsonrpc": "2.0",
                "id": i,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args
                }
            }
            res = mock_server.handle(req)
            self.assertEqual(res.get("id"), i)
            self.assertIn("result", res)
            content = res["result"].get("content", [])
            self.assertTrue(len(content) > 0)
            text = content[0].get("text", "")
            self.assertIn(f"MockExecuted: {tool_name}", text)
            self.assertFalse(res["result"].get("isError", False))

    def test_offline_phone_fallback(self):
        """Test 3: Offline Phone Fallback - returns graceful message when unreachable."""
        # With adb_enabled=False and unreachable base_url
        req = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "phone_toggle_torch",
                "arguments": {"enabled": True}
            }
        }
        res = self.server.handle(req)
        self.assertEqual(res.get("id"), 99)
        self.assertIn("result", res)
        self.assertTrue(res["result"].get("isError", False), "Result should indicate error state when offline")
        text = res["result"]["content"][0]["text"]
        self.assertIn("unreachable", text.lower())
        self.assertIn("companion app", text.lower())

    def test_adb_off_flag(self):
        """While the helmet test's flag file exists, adb is never tried; without it, it is."""
        import tempfile
        from unittest import mock
        server = M.PhoneMcpServer(base_url="http://127.0.0.1:9999", adb_enabled=True)
        with tempfile.TemporaryDirectory() as d:
            flag = Path(d) / "phone-adb-off"
            with mock.patch.object(M, "ADB_OFF_FLAG", flag), mock.patch.object(M.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="device\n")
                flag.touch()
                self.assertFalse(server._is_adb_connected())
                self.assertIsNone(server._run_adb_cmd(["shell", "true"]))
                run.assert_not_called()
                flag.unlink()
                self.assertTrue(server._is_adb_connected())
                run.assert_called()

    def test_multilingual_otp_extraction(self):
        """Verify regex extraction for Croatian and English 2FA / OTP codes."""
        cases = [
            ("Your verification code is 849201", "849201"),
            ("Google: 492019 is your verification code", "492019"),
            ("PBZ: jednokratna lozinka 382910 za prijavu", "382910"),
            ("e-Gradjani: Vasa jednokratna zaporka za prijavu je 849201. Vrijedi 5 minuta.", "849201"),
            ("Zagrebacka banka: vas jednokratni kod je 719204", "719204"),
            ("Erste: vas aktivacijski kod: 582103", "582103"),
            ("Vas sigurnosni kod za prijavu je 940182", "940182"),
        ]
        for text, expected in cases:
            code = M.extract_otp_code(text)
            self.assertEqual(code, expected, f"Failed to extract '{expected}' from: '{text}'")

    def test_server_relay_dispatch_and_headers(self):
        """Test 5: Headers include Authorization and x-api-key when api_key is configured."""
        server = M.PhoneMcpServer(base_url="http://127.0.0.1:8080", adb_enabled=False, api_key="secret-key-123")
        headers = server._headers(json_type=True)
        self.assertEqual(headers.get("Authorization"), "Bearer secret-key-123")
        self.assertEqual(headers.get("x-api-key"), "secret-key-123")
        self.assertEqual(headers.get("Content-Type"), "application/json")

        headers_no_json = server._headers(json_type=False)
        self.assertNotIn("Content-Type", headers_no_json)
        self.assertEqual(headers_no_json.get("Authorization"), "Bearer secret-key-123")

    def test_companion_relay_execution(self):
        """Test 6: Companion API relay successfully dispatches tool and parses result."""
        import io
        from unittest.mock import patch, MagicMock

        server = M.PhoneMcpServer(base_url="http://127.0.0.1:8080", adb_enabled=False, api_key="test-key")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": "Battery: 99%\nCharging: Yes\nHealth: Good"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = server._call_companion_api("phone_get_battery", {})
            self.assertIsNotNone(res)
            self.assertIn("Battery: 99%", res)
            self.assertEqual(mock_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
