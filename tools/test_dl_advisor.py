#!/usr/bin/env python3
"""The DeepSeek helper (tools/dl_advisor.py): when it asks, what it sends, the card, the limits and the loop hook.
No network: a fake MCP registry stands in for the deepseek server."""
from __future__ import annotations

import os as _os
_os.environ.setdefault("RAY_MEMORY_DIR", "off")   # the shared memory store stays out of these tests

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_advisor as A  # noqa: E402
import dl_cli as cli  # noqa: E402

FAIL = "FAIL tetris clears 4 rows, +800 x level, level 2\n12 passed, 1 failed\n[Command exited with code 1]"


class FakeRegistry:
    """The parts of dl_mcp.McpRegistry the helper uses."""

    def __init__(self, answer="Root cause: the test adds hard-drop points. Fix the expectation.\n\n[model: deepseek-flash]",
                 ask=True, leak=None):
        self.active, self.catalog, self.on = True, {"deepseek": object()}, False
        self.answer, self.ask, self.leak_text = answer, ask, leak
        self.calls = []

    def owns(self, name):
        return self.on and name == A.TOOL

    def revive(self, name):
        return False

    def enable(self, name, why=""):
        self.on = True
        return "deepseek is on"

    def leak(self, args):
        return self.leak_text

    def approval(self, name, args):
        return ("deepseek: deepseek_reason(...)", "sends this text to DeepSeek's cloud", False) if self.ask else None

    def call(self, name, args, mode="act", cancel=None):
        self.calls.append(args)
        return self.answer


def stuck_advisor(**ctx):
    a = A.Advisor({"effort_auto": True, "effort": "high", "user_text": "build tetris", **ctx})
    for _ in range(3):
        a.note_result("run_command", {"CommandLine": "node tetris.test.js"}, FAIL)
        a.end_round()
    return a


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.dict(os.environ, {"DL_ADVISOR": "1", "DL_ADVISOR_LOG": str(Path(self.tmp.name) / "advisor.jsonl")})
        p.start()
        self.addCleanup(p.stop)
        q = patch.object(A, "LOG", Path(self.tmp.name) / "advisor.jsonl")
        q.start()
        self.addCleanup(q.stop)

    def log(self):
        f = Path(self.tmp.name) / "advisor.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


class WhenItAsks(Env):
    def test_off_unless_switched_on(self):
        with patch.dict(os.environ, {"DL_ADVISOR": "0"}):
            self.assertIsNone(stuck_advisor().stuck())

    def test_same_failure_three_times_asks(self):
        why = stuck_advisor().stuck()
        self.assertIsNotNone(why)
        self.assertIn("same failure came back 3 times", why[0])

    def test_numbers_in_the_failure_do_not_hide_the_repeat(self):
        a = A.Advisor({"effort": "high"})
        for n in (3, 4, 5):
            a.note_result("run_command", {}, f"FAIL row {n} expected {n * 2}\n[Command exited with code 1]")
        self.assertEqual(len(a.sigs), 1)

    def test_thinking_on_high_comes_first(self):
        self.assertIsNone(stuck_advisor(effort="low").stuck())

    def test_fixed_effort_may_ask(self):
        self.assertIsNotNone(stuck_advisor(effort_auto=False, effort="medium").stuck())

    def test_progress_is_not_stuck(self):
        a = A.Advisor({"effort": "high"})
        for out in ("3 failed\nFAIL a\nFAIL b\nFAIL c", "FAIL a\nFAIL b", "FAIL a", "all 40 passed\n[Command exited with code 0]"):
            a.note_result("run_command", {}, out)
            a.end_round()
        self.assertEqual(a.last_progress, 3)
        self.assertIsNone(a.stuck())

    def test_stall_rule(self):
        a = A.Advisor({"effort": "high"})
        for i in range(13):
            a.note_result("run_command", {}, f"Error: case {'abcdefghijklm'[i]} differs" if i % 4 == 0 else "ok")
            a.end_round()
        why = a.stuck()
        self.assertIsNotNone(why)
        self.assertEqual(why[1], "stall")

    def test_two_loops_ask(self):
        a = A.Advisor({"effort": "high"})
        a.note_raise("thinking loop")
        a.note_raise("repeated tool call")
        self.assertEqual(a.stuck()[1], "loops")

    def test_limits(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        why = a.stuck()
        self.assertTrue(a.consult(reg, *why))
        self.assertIsNone(a.stuck())                          # the same failure is asked once
        for _ in range(3):
            a.note_result("run_command", {}, "FAIL another thing\n[Command exited with code 1]")
            a.end_round()
        self.assertIsNone(a.stuck())                          # cooldown: 10 rounds
        for _ in range(10):
            a.end_round()
        self.assertIsNotNone(a.stuck())
        with patch.dict(os.environ, {"DL_ADVISOR_MAX": "1"}):
            self.assertIsNone(a.stuck())


class FlashThenPro(Env):
    def test_first_consult_is_flash_then_pro_once(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        why = a.stuck()
        self.assertEqual(why[2], A.FLASH)
        a.consult(reg, *why)
        self.assertEqual(reg.calls[0]["model"], "auto")
        for _ in range(6):                                    # Flash's advice did not help
            a.note_result("run_command", {}, FAIL)
            a.end_round()
        why = a.stuck()
        self.assertEqual(why[2], A.PRO)
        self.assertIn("after Flash's advice", why[0])
        reg.answer = "Use the board copy.\n\n[model: deepseek-v4-pro]"
        self.assertIn("deepseek-v4-pro", a.consult(reg, *why))
        self.assertEqual(reg.calls[1]["model"], "deepseek-v4-pro")
        for _ in range(12):
            a.note_result("run_command", {}, FAIL)
            a.end_round()
        why = a.stuck()
        self.assertTrue(why is None or why[2] == A.FLASH)     # at most one Pro consult per request

    def test_no_pro_when_flash_helped(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        a.consult(reg, *a.stuck())
        a.note_result("run_command", {}, "all 30 passed\n[Command exited with code 0]")
        for _ in range(7):
            a.end_round()
        self.assertIsNone(a.stuck())


class PlanReview(Env):
    def test_pro_reviews_the_plan(self):
        a, reg = A.Advisor({"user_text": "make tetris", "yolo": True}), FakeRegistry(
            answer="- Step 4 needs a test before step 5\n\n[model: deepseek-v4-pro]")
        note = a.review_plan(reg, "1. write the file\n2. test it")
        sent = reg.calls[0]
        self.assertEqual(sent["model"], "deepseek-v4-pro")
        self.assertIn("1. write the file", sent["prompt"])
        self.assertIn("make tetris", sent["prompt"])
        self.assertEqual(sent["system"], A.PLAN_SYSTEM)
        self.assertTrue(note.startswith("[D.L. CLI] Before the user approves it"))
        self.assertIn("Step 4 needs a test", note)

    def test_plan_review_can_be_off(self):
        with patch.dict(os.environ, {"DL_ADVISOR_PLAN_REVIEW": "0"}):
            self.assertIsNone(A.Advisor({"yolo": True}).review_plan(FakeRegistry(), "1. x"))

    def test_plan_review_card_outside_yolo(self):
        cards = []
        self.assertIsNone(A.Advisor({}).review_plan(FakeRegistry(), "1. x", approve=lambda k, s, r: cards.append(s) or False))
        self.assertTrue(cards)


class WhatItSends(Env):
    def test_brief_and_note(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        note = a.consult(reg, *a.stuck(), diff="--- a/tetris.html\n+++ b/tetris.html\n-x\n+y")
        sent = reg.calls[0]
        self.assertIn("build tetris", sent["prompt"])
        self.assertIn("FAIL tetris clears 4 rows", sent["prompt"])
        self.assertIn("+++ b/tetris.html", sent["prompt"])
        self.assertIn("node tetris.test.js", sent["prompt"])
        self.assertFalse(sent["include_thinking"])
        self.assertFalse(sent["web"])
        self.assertLessEqual(len(sent["prompt"]), A.BRIEF_MAX)
        self.assertTrue(note.startswith("[D.L. CLI] You were stuck"))
        self.assertIn("Root cause: the test adds hard-drop points", note)
        self.assertIn("deepseek-flash", note)
        self.assertNotIn("[model:", note)
        self.assertEqual(self.log()[0]["result"], "ok")

    def test_card_outside_yolo(self):
        a, reg, cards = stuck_advisor(), FakeRegistry(), []
        note = a.consult(reg, *a.stuck(), approve=lambda k, s, r: cards.append(r) or False)
        self.assertIsNone(note)
        self.assertEqual(reg.calls, [])
        self.assertIn("DeepSeek helper", cards[0])
        self.assertEqual(self.log()[0]["result"], "denied by the user")

    def test_yolo_needs_no_card(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        self.assertTrue(a.consult(reg, *a.stuck(), approve=lambda *x: self.fail("no card in YOLO")))

    def test_credential_blocked(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry(leak="error: BLOCKED")
        self.assertIsNone(a.consult(reg, *a.stuck()))
        self.assertEqual(reg.calls, [])

    def test_api_error_is_reported_not_injected(self):
        a, reg, notes = stuck_advisor(yolo=True), FakeRegistry(answer="DeepSeek API Error: every model failed"), []
        self.assertIsNone(a.consult(reg, *a.stuck(), emit=notes.append))
        self.assertTrue(any("failed" in n["text"] for n in notes))

    def test_empty_balance_pauses_the_helper(self):
        A._PAUSE.update(until=0.0, why="")
        self.addCleanup(A._PAUSE.update, until=0.0, why="")
        a, notes = stuck_advisor(yolo=True), []
        reg = FakeRegistry(answer="error: DeepSeek API Error: Error code: 402 - {'error': {'message': 'Insufficient Balance'}}")
        self.assertIsNone(a.consult(reg, *a.stuck(), emit=notes.append))
        self.assertIn("paused for 60 min", notes[-1]["text"])
        self.assertTrue(A.paused())
        b = stuck_advisor(yolo=True)                              # a new request in the same daemon
        self.assertIsNone(b.stuck())
        self.assertIsNone(b.review_plan(reg, "1. x"))
        self.assertEqual(len(reg.calls), 1)                       # no second failing call
        A._PAUSE["until"] = 0.0                                   # an hour later
        self.assertIsNotNone(stuck_advisor(yolo=True).stuck())

    def test_an_outage_does_not_pause(self):
        A._PAUSE.update(until=0.0, why="")
        a = stuck_advisor(yolo=True)
        a.consult(FakeRegistry(answer="error: DeepSeek API Error: every model failed: deepseek-flash (503)"), *a.stuck())
        self.assertIsNone(A.paused())

    def test_no_deepseek_server(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        reg.catalog = {}
        self.assertIsNone(a.consult(reg, *a.stuck()))


def reply(content="", calls=None):
    return {"content": content, "reasoning": "", "tokens": 10, "prompt_tokens": 100,
            "finish_reason": "tool_calls" if calls else "stop", "tool_calls": calls or []}


def call(i, name, args):
    return [{"id": f"t{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]


class InTheLoop(Env):
    """Ray keeps hitting the same failing test: thinking goes to high first, then DeepSeek is asked once and its
    advice is in the messages for the next model call."""

    def test_stuck_agent_gets_advice(self):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir()
        n = 0
        seen_advice = []

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            if any(str(m.get("content", "")).startswith("[D.L. CLI] You were stuck") for m in messages):
                seen_advice.append(n)
                return reply("Fixed the expectation as advised.")
            return reply("", call(n, "run_command", {"CommandLine": f"node tetris.test.js # try {n}"}))

        reg = FakeRegistry()
        reg.route = lambda *a, **k: []
        reg.tick = lambda: None
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\nfinish tetris"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "low", "effort_auto": True,
               "reasoning_budget_tokens": 1024, "user_text": "finish tetris", "mcp": reg}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "tool_run_command", return_value=FAIL), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=12, session_context=ctx)
        self.assertEqual(len(reg.calls), 1)
        self.assertEqual(ctx["effort"], "high")
        self.assertTrue(seen_advice)
        log = self.log()
        self.assertEqual(log[0]["result"], "ok")
        self.assertIn("outcome_of", log[-1])


if __name__ == "__main__":
    unittest.main()
