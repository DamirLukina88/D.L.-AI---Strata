#!/usr/bin/env python3
"""tools/test_weather_reasoning_bench.py - Unit tests for weather_reasoning_bench.py.

Verifies scoring logic, location inference detection, table evaluation,
email dispatch verification, telemetry calculations, and approval filters.
Does not require live GPU or live dl-ai-sessiond.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tools import weather_reasoning_bench as bench


class TestWeatherReasoningBench(unittest.TestCase):

    def test_approval_filter_proton_allowed(self):
        ws = Path("/tmp/test_ws")
        summary = "proton: send_mail\n  to: info@damir-lukina.com\n  subject: Weather Forecast"
        self.assertTrue(bench.approval_filter(summary, ws, "info@damir-lukina.com"))

    def test_approval_filter_foreign_email_denied(self):
        ws = Path("/tmp/test_ws")
        summary = "proton: send_mail\n  to: attacker@example.com\n  subject: Weather Forecast"
        self.assertFalse(bench.approval_filter(summary, ws, "info@damir-lukina.com"))

    def test_approval_filter_safe_fs(self):
        ws = Path("/tmp/test_ws")
        summary = "run_command: cat /tmp/test_ws/output.txt"
        self.assertTrue(bench.approval_filter(summary, ws, "info@damir-lukina.com"))

    def test_approval_filter_unsafe_fs(self):
        ws = Path("/tmp/test_ws")
        summary = "run_command: cat /etc/shadow"
        self.assertFalse(bench.approval_filter(summary, ws, "info@damir-lukina.com"))

    def test_score_zagreb_success(self):
        steps = [
            {
                "tool_calls": [
                    {"name": "mcp", "args": {"action": "enable", "server": "proton"}},
                    {"name": "run_command", "args": {"CommandLine": "curl -s wttr.in/Zagreb?format=j1"}},
                    {"name": "proton__send_mail", "args": {
                        "to": "info@damir-lukina.com",
                        "subject": "Weather Forecast: Zagreb",
                        "html": "<table><tr><th>Date</th><th>Temp</th></tr><tr><td>Today (Oct 17)</td><td>17°C</td></tr><tr><td>Tomorrow (Oct 18)</td><td>20°C</td></tr></table>"
                    }}
                ],
                "tool_results": [
                    {"name": "mcp", "text": "proton enabled"},
                    {"name": "run_command", "text": "current_condition: temp_C 17 in Zagreb"},
                    {"name": "proton__send_mail", "text": "Sent from info@damir-lukina.com to info@damir-lukina.com"}
                ],
                "thinking": [
                    {"chars": 500, "words": 80, "seconds": 5.2, "text": "Thinking about Zagreb timezone and user profile..."}
                ],
                "final_text": "I have created the weather forecast table for Zagreb and sent it to your email.",
                "seconds": 15.0,
                "errors": []
            }
        ]
        res = bench.score_reasoning_turn(steps, "info@damir-lukina.com")
        self.assertEqual(res["location"]["score"], 25)
        self.assertIn("Zagreb", res["location"]["note"])
        self.assertEqual(res["forecast_table"]["score"], 25)
        self.assertEqual(res["email_delivery"]["score"], 25)
        self.assertEqual(res["efficiency"]["score"], 25)
        self.assertEqual(res["total_score"], 100)
        self.assertEqual(res["telemetry"]["tool_calls"], 3)
        self.assertEqual(res["telemetry"]["think_chars"], 500)

    def test_score_rijeka_ip_trap_failure(self):
        steps = [
            {
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "curl -s wttr.in?format=j1"}},
                    {"name": "proton__send_mail", "args": {
                        "to": "info@damir-lukina.com",
                        "subject": "Weather Forecast: Rijeka",
                        "html": "| Today | Tomorrow |\n|---|---|\n| 15°C | 18°C |"
                    }}
                ],
                "tool_results": [
                    {"name": "run_command", "text": "current_condition: temp_C 15 in Rijeka"},
                    {"name": "proton__send_mail", "text": "Sent from info@damir-lukina.com to info@damir-lukina.com"}
                ],
                "thinking": [],
                "final_text": "Weather forecast for Rijeka sent.",
                "seconds": 8.0,
                "errors": []
            }
        ]
        res = bench.score_reasoning_turn(steps, "info@damir-lukina.com")
        # Fell for IP trap: Location score must be 0!
        self.assertEqual(res["location"]["score"], 0)
        self.assertIn("trap", res["location"]["note"].lower())
        self.assertLess(res["total_score"], 100)

    def test_format_summary_table(self):
        mock_results = [
            {
                "effort": "none",
                "total_score": 50,
                "location": {"score": 0, "note": "FAILED: IP trap"},
                "forecast_table": {"score": 25, "note": "ok"},
                "email_delivery": {"score": 25, "note": "ok"},
                "efficiency": {"score": 0, "note": "none"},
                "telemetry": {
                    "wall_seconds": 12.5,
                    "think_seconds": 0.0,
                    "think_chars": 0,
                    "tool_calls": 2
                }
            },
            {
                "effort": "high",
                "total_score": 100,
                "location": {"score": 25, "note": "Zagreb"},
                "forecast_table": {"score": 25, "note": "ok"},
                "email_delivery": {"score": 25, "note": "ok"},
                "efficiency": {"score": 25, "note": "ok"},
                "telemetry": {
                    "wall_seconds": 45.2,
                    "think_seconds": 28.4,
                    "think_chars": 1240,
                    "tool_calls": 3
                }
            }
        ]
        table = bench.format_summary_table(mock_results)
        self.assertIn("Thinking Level", table)
        self.assertIn("none", table)
        self.assertIn("high", table)
        self.assertIn("100/100", table)


if __name__ == "__main__":
    unittest.main()
