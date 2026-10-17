"""tools/test_dl_yolo_continue.py - Unit test for YOLO mode pure infinite auto-continue past DL_MAX_TURNS.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli


class TestYoloAutoContinue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_yolo_auto_continue_loops_past_max_turns(self):
        # A mock that returns tool calls for 5 turns, then a final text answer on turn 6
        call_count = 0

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 6:
                return {
                    "content": f"Round {call_count}",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": f"call_{call_count}",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": '{"CommandLine": "echo test"}'}
                    }]
                }
            return {
                "content": "Final answer after 6 turns",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 50,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []

        def mock_emit(event):
            if event.get("type") == "notice":
                notices.append(event.get("text"))

        # Run with max_turns=3 and yolo=True
        # It should hit max_turns (3), emit YOLO auto-continue notice, reset turn=0, and keep going through turn 6!
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", return_value="test output"):
            messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "do task"}]
            ctx = {"workspace": self.ws, "messages": messages, "mode": "act", "yolo": True, "emit": mock_emit}
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=3, session_context=ctx)

        self.assertEqual(call_count, 6)
        self.assertTrue(any("Auto-continuing" in n for n in notices), f"Notices: {notices}")
        self.assertEqual(messages[-1]["content"], "Final answer after 6 turns")

    def test_non_yolo_stops_at_max_turns(self):
        call_count = 0

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": f"Round {call_count}",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 50,
                "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": f"call_{call_count}",
                    "type": "function",
                    "function": {"name": "run_command", "arguments": '{"CommandLine": "echo test"}'}
                }]
            }

        notices = []

        def mock_emit(event):
            if event.get("type") == "notice":
                notices.append(event.get("text"))

        # Run with max_turns=3 and yolo=False
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", return_value="test output"), \
             patch.object(cli, "turn_cap_wrap_up", return_value="wrap up"):
            messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "do task"}]
            ctx = {"workspace": self.ws, "messages": messages, "mode": "act", "yolo": False, "emit": mock_emit}
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=3, session_context=ctx)

        # In non-yolo mode, it must stop at 3 tool calls
        self.assertEqual(call_count, 3)
        self.assertFalse(any("Auto-continuing" in n for n in notices))


if __name__ == "__main__":
    unittest.main()
