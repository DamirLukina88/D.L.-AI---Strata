#!/usr/bin/env python3
"""Unit tests for tools/dl_effort.py and mid-turn escalation in tools/dl_cli.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dl_cli
import dl_effort


class ResolveTurnTests(unittest.TestCase):
    def test_greetings_and_wake_words_map_to_none(self):
        cases = [
            "hi",
            "Hello!",
            "Hey Ray",
            "hi rey",
            "Good morning Rae",
            "wray?",
            "Ring, are you there?",
            "how are you doing today?",
            "thanks a lot!",
            "okay got it",
            "stop",
            "never mind",
        ]
        for text in cases:
            level, reason = dl_effort.resolve_turn(text)
            self.assertEqual(level, "none", f"Expected 'none' for {text!r}, got {level!r} ({reason})")

    def test_smart_home_and_clock_commands_map_to_none(self):
        cases = [
            "Turn off the living room lights",
            "turn on bedroom lamp",
            "set the temperature to 22 degrees",
            "dim the lights in the kitchen",
            "what time is it?",
            "what is today's date?",
            "set a timer for 10 minutes",
            "pause the music",
        ]
        for text in cases:
            level, reason = dl_effort.resolve_turn(text)
            self.assertEqual(level, "none", f"Expected 'none' for {text!r}, got {level!r} ({reason})")

    def test_short_factual_queries_map_to_low(self):
        cases = [
            "What is the capital of Australia?",
            "Who wrote Crime and Punishment?",
            "How many bytes are in a mebibyte?",
            "Convert 100 kilometers to miles",
            "Where is MountKilimanjaro located?",
        ]
        for text in cases:
            level, reason = dl_effort.resolve_turn(text)
            self.assertEqual(level, "low", f"Expected 'low' for {text!r}, got {level!r} ({reason})")

    def test_conceptual_explanations_map_to_medium(self):
        cases = [
            "Explain how speculative decoding works in transformer inference",
            "What is the difference between TCP and UDP?",
            "Compare radix sort and quicksort pros and cons",
            "Summarize the trade-offs between Q4_0 and INT8 KV caches",
        ]
        for text in cases:
            level, reason = dl_effort.resolve_turn(text)
            self.assertEqual(level, "medium", f"Expected 'medium' for {text!r}, got {level!r} ({reason})")

    def test_code_files_errors_and_engineering_tasks_map_to_high(self):
        cases = [
            "Check serve/server.py and fix the timeout bug",
            "Look at @tools/dl_cli.py and refactor execute_agent_loop",
            "```python\ndef foo():\n    return 1/0\n```\nWhy does this fail?",
            "Traceback (most recent call last):\n  File \"test.py\", line 1\nValueError: bad value",
            "Implement automatic thinking level selection and write unit tests",
            "Run git status and check the repo for uncommitted changes",
            "Benchmark the new kernel on RX 7600 XT",
            "analize the wiki, the repo, and the code to understand the project",
        ]
        for text in cases:
            level, reason = dl_effort.resolve_turn(text)
            self.assertEqual(level, "high", f"Expected 'high' for {text!r}, got {level!r} ({reason})")

    def test_plan_mode_and_plan_file_always_map_to_high(self):
        level, reason = dl_effort.resolve_turn("hi", mode="plan")
        self.assertEqual((level, reason), ("high", "plan mode"))
        level, reason = dl_effort.resolve_turn("what is 2+2?", plan_file="PLAN.md")
        self.assertEqual((level, reason), ("high", "plan mode"))

    def test_explicit_cues_override_heuristics(self):
        level, _ = dl_effort.resolve_turn("What is the capital of France? Think step by step.")
        self.assertEqual(level, "high")
        level, _ = dl_effort.resolve_turn("Explain quantum computing /no_think")
        self.assertEqual(level, "none")

    def test_followup_complaints_escalate_to_high_when_prior_turn_exists(self):
        prior = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "Done."},
        ]
        for complaint in ("Why?", "try again", "still broken", "that didn't work", "no, that's wrong"):
            level, reason = dl_effort.resolve_turn(complaint, messages=prior)
            self.assertEqual(level, "high", f"Expected 'high' for follow-up {complaint!r}, got {level!r}")
            self.assertEqual(reason, "follow-up correction")


class MidTurnEscalationTests(unittest.TestCase):
    def test_check_tool_result_failure_detects_all_failure_signals(self):
        seen: set[tuple[str, str]] = set()
        # Clean first call -> None
        r1 = dl_effort.check_tool_result_failure("view_file", {"Path": "a.py"}, '{"Path": "a.py"}', "line 1", seen)
        self.assertIsNone(r1)
        # Repeated identical call -> escalates
        r2 = dl_effort.check_tool_result_failure("view_file", {"Path": "a.py"}, '{"Path": "a.py"}', "line 1", seen)
        self.assertEqual(r2, "repeated identical tool call")
        # Malformed JSON args -> escalates
        r3 = dl_effort.check_tool_result_failure("view_file", {"_raw": "{bad"}, "{bad", "ok", set())
        self.assertEqual(r3, "malformed tool arguments")
        # Tool Error prefix -> escalates
        r4 = dl_effort.check_tool_result_failure("view_file", {"Path": "b.py"}, '{"Path": "b.py"}', "Error: File not found", set())
        self.assertEqual(r4, "tool execution error")
        # Non-zero exit code -> escalates
        r5 = dl_effort.check_tool_result_failure(
            "run_command", {"CommandLine": "false"}, '{"CommandLine": "false"}', "out\n[Command exited with code 1]", set()
        )
        self.assertEqual(r5, "non-zero command exit")
        # Zero exit code -> None
        r6 = dl_effort.check_tool_result_failure(
            "run_command", {"CommandLine": "true"}, '{"CommandLine": "true"}', "out\n[Command exited with code 0]", set()
        )
        self.assertIsNone(r6)

    def test_execute_agent_loop_escalates_to_high_on_tool_failure_when_auto_effort(self):
        efforts_sent = []
        replies = [
            {
                "content": "",
                "reasoning": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "view_file", "arguments": json.dumps({"TargetFile": "missing_file.py"})},
                    }
                ],
                "finish_reason": "tool_calls",
                "tokens": 10,
                "prompt_tokens": 50,
            },
            {
                "content": "I checked and the file does not exist.",
                "reasoning": "Now thinking at high effort.",
                "tool_calls": [],
                "finish_reason": "stop",
                "tokens": 15,
                "prompt_tokens": 80,
            },
        ]

        def fake_chat_turn(messages, url, api_key, tools, emit=None, cancel=None, measured=None, effort=None, on_compact=None):
            efforts_sent.append(effort)
            return replies.pop(0)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "What is in missing_file?"}]
            ctx = {
                "workspace": ws,
                "messages": msgs,
                "mode": "act",
                "effort": "low",
                "auto_effort": True,
                "emit": events.append,
                "user_text": "What is in missing_file?",
            }
            with mock.patch.object(dl_cli, "chat_turn_in_context", side_effect=fake_chat_turn):
                dl_cli.execute_agent_loop(msgs, "http://127.0.0.1:8080", "", ws, session_context=ctx)

        self.assertEqual(efforts_sent, ["low", "high"])
        self.assertEqual(ctx["effort"], "high")
        self.assertTrue(any(e.get("type") == "notice" and "escalated to high" in e.get("text", "") for e in events))


if __name__ == "__main__":
    unittest.main()
