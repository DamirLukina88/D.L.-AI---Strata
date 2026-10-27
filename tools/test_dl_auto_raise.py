"""tools/test_dl_auto_raise.py - Unit tests for mid-turn thinking level escalation in dl_cli.execute_agent_loop.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli


class TestDlAutoRaise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_command_exit_nonzero_raises_to_high_and_posts_one_notice(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "Running command",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "bad_cmd"})}
                    }]
                }
            if call_count == 2:
                # Second round also runs a failing command to check that only ONE notice is posted
                return {
                    "content": "Trying again",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 80,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "bad_cmd_2"})}
                    }]
                }
            return {
                "content": "Done after failure",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 120,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []

        def mock_emit(event):
            if event.get("type") == "notice":
                notices.append(event.get("text", ""))

        def mock_dispatch(fn, args, ws, **kw):
            return "Command failed\n[Command exited with code 1]"

        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=mock_dispatch):
            messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "run cmd"}]
            ctx = {
                "workspace": self.ws,
                "messages": messages,
                "mode": "act",
                "effort": "low",
                "effort_auto": True,
                "emit": mock_emit,
            }
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        # Round 1 was sent with low; Round 2 and 3 with high
        self.assertEqual(efforts_seen, ["low", "high", "high"])
        self.assertEqual(ctx["effort"], "high")

        # Exactly one raise notice was posted
        raise_notices = [n for n in notices if "Thinking raised to high" in n]
        self.assertEqual(len(raise_notices), 1)
        self.assertIn("because a command ended with an error code", raise_notices[0])

    def test_without_effort_auto_level_never_changes(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "Running command",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "bad_cmd"})}
                    }]
                }
            return {
                "content": "Done",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 80,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []

        def mock_emit(event):
            if event.get("type") == "notice":
                notices.append(event.get("text", ""))

        def mock_dispatch(fn, args, ws, **kw):
            return "Command failed\n[Command exited with code 1]"

        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=mock_dispatch):
            messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "run cmd"}]
            ctx = {
                "workspace": self.ws,
                "messages": messages,
                "mode": "act",
                "effort": "low",
                # effort_auto unset
                "emit": mock_emit,
            }
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        # Effort never changed
        self.assertEqual(efforts_seen, ["low", "low"])
        self.assertEqual(ctx["effort"], "low")
        self.assertFalse(any("Thinking raised to high" in n for n in notices))

    def test_already_high_turn_posts_no_notice(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "Running command",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "bad_cmd"})}
                    }]
                }
            return {
                "content": "Done",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 80,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []

        def mock_emit(event):
            if event.get("type") == "notice":
                notices.append(event.get("text", ""))

        def mock_dispatch(fn, args, ws, **kw):
            return "Command failed\n[Command exited with code 1]"

        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=mock_dispatch):
            messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "run cmd"}]
            ctx = {
                "workspace": self.ws,
                "messages": messages,
                "mode": "act",
                "effort": "high",
                "effort_auto": True,
                "emit": mock_emit,
            }
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        self.assertEqual(efforts_seen, ["high", "high"])
        self.assertEqual(ctx["effort"], "high")
        self.assertFalse(any("Thinking raised to high" in n for n in notices))

    def test_loop_guard_raises_to_high(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "repeating thought",
                    "reasoning": "thought thought",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "loop",
                    "loop_sentence": "repeating sentence",
                    "tool_calls": []
                }
            return {
                "content": "Done",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 80,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
        ctx = {
            "workspace": self.ws,
            "messages": messages,
            "mode": "act",
            "effort": "low",
            "effort_auto": True,
            "emit": lambda ev: notices.append(ev.get("text", "")) if ev.get("type") == "notice" else None,
        }
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn):
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        self.assertEqual(efforts_seen, ["low", "high"])
        self.assertEqual(ctx["effort"], "high")
        self.assertTrue(any("because the thinking was going in circles" in n for n in notices))

    def test_text_call_retry_raises_to_high(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "<tool_call>\n<function=run_command>\n",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "stop",
                    "tool_calls": []
                }
            return {
                "content": "Done",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 80,
                "finish_reason": "stop",
                "tool_calls": []
            }

        notices = []
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
        ctx = {
            "workspace": self.ws,
            "messages": messages,
            "mode": "act",
            "effort": "low",
            "effort_auto": True,
            "emit": lambda ev: notices.append(ev.get("text", "")) if ev.get("type") == "notice" else None,
        }
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn):
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        self.assertEqual(efforts_seen, ["low", "high"])
        self.assertEqual(ctx["effort"], "high")
        self.assertTrue(any("because a tool call came back as plain text" in n for n in notices))

    def test_finish_checks_raise_to_high(self):
        call_count = 0
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            efforts_seen.append(kwargs.get("effort"))
            return {
                "content": f"Turn {call_count}",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 50,
                "finish_reason": "stop",
                "tool_calls": []
            }

        check_calls = 0

        def mock_finish_checks(*a, **kw):
            nonlocal check_calls
            check_calls += 1
            return "Please check the failing items" if check_calls == 1 else None

        notices = []
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
        ctx = {
            "workspace": self.ws,
            "messages": messages,
            "mode": "act",
            "effort": "low",
            "effort_auto": True,
            "emit": lambda ev: notices.append(ev.get("text", "")) if ev.get("type") == "notice" else None,
        }
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "finish_checks", side_effect=mock_finish_checks):
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        self.assertEqual(efforts_seen, ["low", "high"])
        self.assertEqual(ctx["effort"], "high")
        self.assertTrue(any("because the finish checks sent the work back" in n for n in notices))

    def test_auto_raise_updates_reasoning_budget_tokens_and_payload(self):
        call_count = 0
        budgets_seen = []
        efforts_seen = []

        def mock_chat_turn(messages, url, api_key, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            budgets_seen.append(kwargs.get("budget"))
            efforts_seen.append(kwargs.get("effort"))
            if call_count == 1:
                return {
                    "content": "Running command",
                    "reasoning": "",
                    "tokens": 10,
                    "prompt_tokens": 50,
                    "finish_reason": "tool_calls",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "bad_cmd"})}
                    }]
                }
            return {
                "content": "Done",
                "reasoning": "",
                "tokens": 10,
                "prompt_tokens": 80,
                "finish_reason": "stop",
                "tool_calls": []
            }

        def mock_dispatch(fn, args, ws, **kw):
            return "Command failed\n[Command exited with code 1]"

        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "run cmd"}]
        ctx = {
            "workspace": self.ws,
            "messages": messages,
            "mode": "act",
            "effort": "low",
            "effort_auto": True,
            "reasoning_budget_tokens": 1024,
            "emit": lambda ev: None,
        }
        with patch.object(cli, "chat_turn_in_context", side_effect=mock_chat_turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=mock_dispatch):
            cli.execute_agent_loop(messages, "http://127.0.0.1:8080", "key", self.ws, max_turns=5, session_context=ctx)

        self.assertEqual(efforts_seen, ["low", "high"])
        self.assertEqual(budgets_seen, [1024, 4096])
        self.assertEqual(ctx["effort"], "high")
        self.assertEqual(ctx["reasoning_budget_tokens"], 4096)

    def test_stream_chat_turn_payload_includes_reasoning_budget_tokens(self):
        payloads = []

        class DummyResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def __iter__(self):
                return iter([b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\n', b'data: [DONE]\n\n'])

        def mock_urlopen(req, timeout=None):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return DummyResponse()

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            cli.stream_chat_turn([{"role": "user", "content": "hi"}], "http://127.0.0.1:8080", "key", tools=[], effort="low", budget=1024, emit=lambda ev: None)
            cli.stream_chat_turn([{"role": "user", "content": "hi"}], "http://127.0.0.1:8080", "key", tools=[], effort="none", budget=0, emit=lambda ev: None)

        self.assertEqual(payloads[0]["reasoning_effort"], "low")
        self.assertEqual(payloads[0]["reasoning_budget_tokens"], 1024)
        self.assertEqual(payloads[1]["reasoning_effort"], "none")
        self.assertNotIn("reasoning_budget_tokens", payloads[1])


if __name__ == "__main__":
    unittest.main()
