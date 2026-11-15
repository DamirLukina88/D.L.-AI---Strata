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

    def test_different_errors_without_a_fail_line_differ(self):
        a = A.failure_signature("Stderr:\nSyntaxError-free but: cannot find marker A\n[Command exited with code 1]")
        b = A.failure_signature("Stderr:\nwrote 0 bytes to out.js\n[Command exited with code 1]")
        self.assertNotEqual(a, b)
        self.assertEqual(A.failure_signature("Stderr:\ncannot find marker at line 12\n[Command exited with code 1]"), A.failure_signature("Stderr:\ncannot find marker at line 40\n[Command exited with code 2]"))
        self.assertIsNone(A.failure_signature("all good\n[Command exited with code 0]"))

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
        a.note_result("run_command", {}, FAIL)
        a.note_raise("thinking loop")
        a.note_raise("repeated tool call")
        self.assertEqual(a.stuck()[1], "loops")

    def test_browser_repeats_are_not_circles(self):
        a = A.Advisor({"effort": "high"})
        a.note_result("run_command", {}, FAIL)
        for t in ("playwright__browser_navigate", "playwright__browser_press_key", "playwright__browser_snapshot"):
            a.note_raise("repeated tool call", t)
        self.assertIsNone(a.stuck())
        a.note_raise("repeated tool call", "run_command")
        a.note_raise("thinking loop")
        self.assertEqual(a.stuck()[1], "loops")

    def test_circles_need_a_recent_failure(self):
        a = A.Advisor({"effort": "high"})
        a.note_raise("repeated tool call", "run_command")
        a.note_raise("thinking loop")
        self.assertIsNone(a.stuck())

    def test_repeats_far_apart_are_not_circles(self):
        a = A.Advisor({"effort": "high"})            # 2026-11-15: repeats 73 rounds apart in a run that edited fine
        a.note_raise("repeated tool call", "run_command")
        for _ in range(40):
            a.end_round()
        a.note_result("run_command", {}, FAIL)
        a.note_raise("repeated tool call", "run_command")
        self.assertIsNone(a.stuck())
        a.end_round()
        a.note_raise("repeated tool call", "run_command")
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

    def test_pro_brief_carries_flashs_advice(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        a.consult(reg, *a.stuck())
        self.assertNotIn("Advice already given", reg.calls[0]["prompt"])
        for _ in range(6):
            a.note_result("run_command", {}, FAIL)
            a.end_round()
        a.consult(reg, *a.stuck())
        pro = reg.calls[1]["prompt"]
        self.assertIn("Advice already given (deepseek-flash", pro)
        self.assertIn("Root cause: the test adds hard-drop points", pro)
        self.assertLessEqual(len(pro), A.BRIEF_MAX)
        self.assertNotIn("advice", self.log()[0])            # the advice text stays out of the log

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


class FinalReview(Env):
    """A plan run that says it is done: Pro reviews it, sends it back until it passes, at most 5 rounds."""

    def run_plan(self, answers, edit_each_time=True, max_turns=30):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir(exist_ok=True)
        plan = ws / "PLAN.md"
        plan.write_text("# Plan\n\n## Progress\n\n- [x] write game.js\n")
        reg = FakeRegistry()
        reg.route = lambda *a, **k: []
        reg.tick = lambda: None
        replies = iter(answers)
        reg.call = lambda name, args, mode="act", cancel=None: reg.calls.append(args) or next(replies)
        n = 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            last = str(messages[-1].get("content", ""))
            if messages[-1].get("role") == "tool" or n > 1 and not edit_each_time:
                return reply("Done: game.js written and tested.")
            if n == 1 or (edit_each_time and last.startswith("[D.L. CLI] A final review")):
                return reply("", call(n, "write_to_file", {"TargetFile": str(ws / "game.js"),
                                                           "CodeContent": f"let v = {n};\n", "Overwrite": True}))
            return reply("Done: game.js written and tested.")

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\nexecute the plan"}]
        notes = []
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high",
               "effort_auto": False, "user_text": "execute the plan", "mcp": reg, "plan_file": str(plan),
               "emit": lambda e: notes.append(e.get("text", "")) if e.get("type") == "notice" else None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=max_turns, session_context=ctx)
        return reg, msgs, notes

    def test_fix_then_pass(self):
        reg, msgs, notes = self.run_plan(["VERDICT: FIX\nMust fix:\n- game.js: v is wrong\n\n[model: deepseek-v4-pro]",
                                          "VERDICT: PASS\n\n[model: deepseek-v4-pro]"])
        self.assertEqual(len(reg.calls), 2)
        self.assertEqual(reg.calls[0]["model"], "deepseek-v4-pro")
        self.assertEqual(reg.calls[0]["system"], A.FINAL_SYSTEM)
        self.assertIn("## File game.js", reg.calls[0]["prompt"])
        self.assertIn("- [x] write game.js", reg.calls[0]["prompt"])
        sent_back = [m for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI] A final review")]
        self.assertEqual(len(sent_back), 1)
        self.assertIn("round 1 of at most 5", sent_back[0]["content"])
        self.assertTrue(any("passed in round 2" in t for t in notes))

    def test_stops_when_nothing_changed(self):
        reg, msgs, notes = self.run_plan(["VERDICT: FIX\nMust fix:\n- a bug\n\n[model: deepseek-v4-pro]"] * 3,
                                         edit_each_time=False)
        self.assertEqual(len(reg.calls), 1)
        self.assertTrue(any("nothing changed since the last review" in t for t in notes))

    def test_at_most_five_rounds(self):
        reg, msgs, notes = self.run_plan(["VERDICT: FIX\nMust fix:\n- still wrong\n\n[model: deepseek-v4-pro]"] * 9,
                                         max_turns=40)
        self.assertEqual(len(reg.calls), 5)
        self.assertTrue(any("stopped after 5 rounds" in t for t in notes))

    def test_no_review_without_a_plan(self):
        a = A.Advisor({"yolo": True})
        with patch.dict(os.environ, {"DL_ADVISOR_FINAL": "0"}):
            self.assertEqual(a.final_review(FakeRegistry(), "p", "r", {}, 1), ("skip", None))

    def test_big_files_are_cut_to_the_budget(self):
        reg = FakeRegistry(answer="VERDICT: PASS\n\n[model: deepseek-v4-pro]")
        verdict, _ = A.Advisor({"yolo": True}).final_review(reg, "plan", "done", {"a.js": "x" * 50000, "b.js": "y" * 50000}, 1)
        self.assertEqual(verdict, "pass")
        self.assertLessEqual(len(reg.calls[0]["prompt"]), 60500)
        self.assertIn("file cut", reg.calls[0]["prompt"])


class FinalReviewFiles(Env):
    """2026-11-15: two stale scripts in /tmp, the plan and a file of the user's filled the final review's brief
    before the game itself, and the reviewer asked for the user's file to be removed."""

    def test_project_files_first_no_plan_nothing_outside_the_workspace(self):
        ws = Path(self.tmp.name) / "ws_final"
        (ws / "tetris").mkdir(parents=True)
        for name in ("tetris/index.html", "PLAN.md", "LAPTOP-SETUP.md", "tetris.test.js"):
            (ws / name).write_text("x")
        changed = [Path("/tmp/model.js"), Path("/tmp/selftest.js"), ws / "PLAN.md", ws / "tetris" / "index.html"]
        via_cps = ["LAPTOP-SETUP.md", "PLAN.md", "tetris.test.js", "tetris/index.html"]
        self.assertEqual(cli.final_review_files(ws, changed, via_cps, str(ws / "PLAN.md")),
                         ["tetris/index.html", "LAPTOP-SETUP.md", "tetris.test.js"])

    def test_the_reviewer_is_told_not_to_ask_for_files_to_be_removed(self):
        self.assertIn("never ask for a file to be deleted", A.FINAL_SYSTEM)


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


PATCH = ("FILE: a.js\n<<<OLD\nlet x = 1;\n===\nlet x = 3;\nNEW>>>\n\n"
         "FILE: a.js\n<<<OLD\nlet y = 2;\n===\nlet y = 5;\nNEW>>>\n\n"
         "FILE: /etc/hosts\n<<<OLD\nlocalhost\n===\nx\nNEW>>>\n\n"
         "CHECK: node a.test.js prints 3\nWhy: x was never set.\n\n[model: deepseek-flash]")


class PatchMode(Env):
    """Stuck in known files: DeepSeek writes exact old -> new blocks; only blocks that match once reach Ray."""

    def ws(self):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir(exist_ok=True)
        (ws / "a.js").write_text("let x = 1;\nlet y = 2;\nlet y = 2;\n")
        return ws

    def test_only_unique_blocks_in_the_workspace_are_kept(self):
        valid, bad, check = A.parse_patch(PATCH, self.ws())
        self.assertEqual([(Path(b["file"]).name, b["new"]) for b in valid], [("a.js", "let x = 3;")])
        self.assertEqual(len(bad), 2)
        self.assertIn("found 2 times", bad[0])
        self.assertIn("not a file in the workspace", bad[1])
        self.assertEqual(check, "node a.test.js prints 3")

    def test_patch_note_has_the_blocks_and_the_check(self):
        ws = self.ws()
        a, reg = stuck_advisor(yolo=True, workspace=ws), FakeRegistry(answer=PATCH)
        note = a.patch(reg, *a.stuck(), files=a.target_files(["a.js"]))
        sent = reg.calls[0]
        self.assertEqual(sent["system"], A.PATCH_SYSTEM)
        self.assertIn("## File a.js", sent["prompt"])
        self.assertIn("let y = 2;", sent["prompt"])
        self.assertTrue(note.startswith("[D.L. CLI] You were stuck"))
        self.assertIn("<<<OLD\nlet x = 1;\n===\nlet x = 3;\nNEW>>>", note)
        self.assertIn("node a.test.js prints 3", note)
        self.assertIn("Dropped", note)
        self.assertNotIn("/etc/hosts\n<<<OLD", note)
        self.assertEqual(a.consults[-1]["patch_blocks"], 1)

    def test_a_long_patch_keeps_its_later_blocks(self):
        ws = self.ws()                                   # cut at 8,000 characters, the second block was lost
        long_new = "let x = 3; // " + "x" * 9000
        answer = (f"FILE: a.js\n<<<OLD\nlet x = 1;\n===\n{long_new}\nNEW>>>\n"
                  "FILE: a.js\n<<<OLD\nlet y = 2;\nlet y = 2;\n===\nlet y = 5;\nNEW>>>\nCHECK: node a.js\n\n"
                  "[model: deepseek-flash]")
        a, reg = stuck_advisor(yolo=True, workspace=ws), FakeRegistry(answer=answer)
        note = a.patch(reg, *a.stuck(), files=a.target_files(["a.js"]))
        self.assertEqual(a.consults[-1]["patch_blocks"], 2)
        self.assertIn("let y = 5;", note)

    def test_advice_that_starts_with_the_word_error_is_advice(self):
        answer = "Errors come from the test, not the code (401 is what it expects): fix line 3.\n\n[model: deepseek-flash]"
        a, reg = stuck_advisor(yolo=True), FakeRegistry(answer=answer)
        note = a.consult(reg, *a.stuck())
        self.assertIn("Errors come from the test", note or "")
        self.assertIsNone(A.paused())

    def test_a_patch_that_matches_nothing_becomes_advice(self):
        ws = self.ws()
        a = stuck_advisor(yolo=True, workspace=ws)
        reg = FakeRegistry(answer="FILE: a.js\n<<<OLD\nnot there\n===\nx\nNEW>>>\n\n[model: deepseek-flash]")
        note = a.patch(reg, *a.stuck(), files={"a.js": "let x = 1;"})
        self.assertTrue(note.startswith("[D.L. CLI] You were stuck"))
        self.assertIn("Its advice", note)

    def test_no_files_means_plain_advice(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        note = a.patch(reg, *a.stuck(), files={})
        self.assertEqual(reg.calls[0]["system"], A.SYSTEM)
        self.assertIn("Root cause", note)

    def test_oversized_files_fall_back_to_advice(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        note = a.patch(reg, *a.stuck(), files={"big.js": "x" * 70000})
        self.assertEqual(reg.calls[0]["system"], A.SYSTEM)
        self.assertNotIn("## File big.js", reg.calls[0]["prompt"])
        self.assertIn("Root cause", note)

    def test_target_files_are_the_ones_ray_works_on(self):
        ws = self.ws()
        (ws / "b.js").write_text("b")
        (ws / ".env").write_text("SECRET=1")
        a = A.Advisor({"workspace": ws})
        for _ in range(2):
            a.note_result("view_file", {"AbsolutePath": str(ws / "a.js")}, "1: let x")
        a.note_result("run_command", {"CommandLine": "node b.js && cat .env /tmp/x.js"}, "ok")
        self.assertEqual(list(a.target_files()), ["a.js", "b.js"])
        self.assertEqual(list(a.target_files(["b.js"])), ["b.js", "a.js"])

    def test_pro_gets_room_to_answer(self):
        a, reg = stuck_advisor(yolo=True), FakeRegistry()
        a.consult(reg, "why", "k1")
        a.consult(reg, "why", "k2", A.PRO)
        self.assertEqual([c["max_tokens"] for c in reg.calls], [16384, 32768])


class TextCalls(Env):
    def test_a_tool_call_written_as_text_is_not_a_loop(self):
        a = stuck_advisor(yolo=True)
        a.note_raise("tool call sent as text")
        a.note_raise("tool call sent as text")
        self.assertEqual(a.raises, [])


class TextCallRevive(Env):
    def test_a_text_call_to_a_stopped_server_turns_it_back_on(self):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir()
        reg = FakeRegistry()
        reg.route = lambda *a, **k: []
        reg.tick = lambda: None
        revived = []
        reg.revive = lambda name: revived.append(name) or True
        replies = iter([reply("<tool_call>\n<function=playwright__browser_navigate>\n<parameter=url>\nhttp://x\n"
                              "</parameter>\n</function>\n</tool_call>"), reply("Done.")])
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "open it"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": False, "effort": "low",
               "effort_auto": False, "user_text": "open it", "mcp": reg}
        with patch.object(cli, "chat_turn_in_context", side_effect=lambda *a, **k: next(replies)), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=5, session_context=ctx)
        self.assertEqual(revived, ["playwright__browser_navigate"])
        self.assertTrue(any("(playwright) had been turned off" in str(m.get("content", "")) for m in msgs))


class Watchdog(Env):
    """Coding work that goes 12 rounds without changing a project file is told to edit; at 18 DeepSeek writes the
    patch (or, with the helper off, Ray is told again)."""

    def run_reading(self, rounds=25, helper=True, answer=PATCH):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir(exist_ok=True)
        (ws / "a.js").write_text("let x = 1;\nlet y = 2;\nlet y = 2;\n")
        n = 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            if any(str(m.get("content", "")).startswith(("[D.L. CLI] You were stuck", "[D.L. CLI] 18 rounds"))
                   for m in messages):
                return reply("Applied it.")
            return reply("", call(n, "view_file", {"AbsolutePath": str(ws / "a.js"), "StartLine": n}))

        reg = FakeRegistry(answer=answer)
        reg.route = lambda *a, **k: []
        reg.tick = lambda: None
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\nfix a.js"}]
        notes = []
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high", "effort_auto": False,
               "effort_reason": "coding task", "user_text": "fix a.js", "mcp": reg,
               "emit": lambda e: notes.append(e.get("text", "")) if e.get("type") == "notice" else None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "1" if helper else "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=rounds, session_context=ctx)
        return reg, msgs, notes

    def test_nudge_at_12_then_patch_at_18(self):
        reg, msgs, notes = self.run_reading()
        texts = [str(m.get("content", "")) for m in msgs if m.get("role") == "user"]
        nudges = [t for t in texts if t.startswith("[D.L. CLI] 12 rounds without changing")]
        self.assertEqual(len(nudges), 1)
        self.assertEqual(len(reg.calls), 1)
        self.assertEqual(reg.calls[0]["system"], A.PATCH_SYSTEM)
        self.assertIn("## File a.js", reg.calls[0]["prompt"])
        self.assertTrue(any("<<<OLD\nlet x = 1;" in t for t in texts))
        self.assertTrue(any("Watchdog: 12 rounds" in t for t in notes))

    def test_helper_off_tells_ray_again(self):
        reg, msgs, notes = self.run_reading(helper=False)
        texts = [str(m.get("content", "")) for m in msgs if m.get("role") == "user"]
        self.assertEqual(reg.calls, [])
        self.assertTrue(any(t.startswith("[D.L. CLI] 18 rounds and still no project file") for t in texts))

    def test_off_for_questions(self):
        ws = Path(self.tmp.name) / "ws2"
        ws.mkdir()
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}]
        n = 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            return reply("", call(n, "view_file", {"AbsolutePath": str(ws / "x"), "StartLine": n}))
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": False, "effort": "medium",
               "effort_auto": True, "effort_reason": "explanation", "user_text": "explain x", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=20, session_context=ctx)
        self.assertFalse(any("rounds without changing" in str(m.get("content", "")) for m in msgs))


class WatchdogWithoutCheckpoints(Env):
    """Checkpoints that turned themselves off (no jj, too big a folder) report no change: the edit tools count then."""

    def test_edits_every_round_are_not_nudged(self):
        ws = Path(self.tmp.name) / "ws_off"
        ws.mkdir()
        (ws / "a.js").write_text("let x = 0;\n")
        n = 0

        class Off(cli.Checkpoints):
            def __init__(self, ws_, emit=None):
                super().__init__(ws_, emit)
                self.off = "jj is not installed"

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            if n > 14:
                return reply("Done.")
            return reply("", call(n, "write_to_file", {"TargetFile": str(ws / "a.js"), "CodeContent": f"let x = {n};\n",
                                                       "Overwrite": True}))
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\nfix a.js"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high", "effort_auto": False,
               "effort_reason": "coding task", "user_text": "fix a.js", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "Checkpoints", Off), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "1", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=20, session_context=ctx)
        self.assertEqual((ws / "a.js").read_text(), "let x = 14;\n")
        self.assertFalse([m for m in msgs if "rounds without changing" in str(m.get("content", ""))])


class WatchdogIgnoresScratchFiles(Env):
    """Test, probe and scratch files are not a changed project file (the user's choice, 2026-11-15); the plan is."""

    def test_which_files_count(self):
        for name in ("tetris.test.js", "test_game.py", "game_test.go", "probe-tetris.html", "scratch.js", "tmp_gen.py",
                     "tests/unit/a.js", "/tmp/gen.js"):
            self.assertFalse(cli.project_change([name], Path(self.tmp.name)), name)
        for name in ("tetris.html", "src/game.js", "template.html", "contest.py", "latest.md", "PLAN.md"):
            self.assertTrue(cli.project_change([name], Path(self.tmp.name)), name)
        self.assertTrue(cli.project_change(["a.test.js", "a.js"]))

    def test_only_scratch_files_written_is_still_nudged(self):
        ws = Path(self.tmp.name) / "ws_scratch"
        ws.mkdir()
        (ws / "a.js").write_text("let x = 0;\n")
        n = 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            if n > 14:
                return reply("Done.")
            return reply("", call(n, "write_to_file", {"TargetFile": str(ws / f"probe_{n}.test.js"),
                                                       "CodeContent": f"// {n}\n", "Overwrite": True}))
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\nfix a.js"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high", "effort_auto": False,
               "effort_reason": "coding task", "user_text": "fix a.js", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=20, session_context=ctx)
        self.assertEqual(len([m for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI] 12 rounds")]), 1)


class LeanThinking(Env):
    """Auto effort on coding work: high in the first round and for 2 rounds after a failure, medium otherwise."""

    def test_high_to_plan_medium_to_act(self):
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir()
        efforts, n = [], 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            efforts.append((k.get("effort"), k.get("budget")))
            if n >= 8:
                return reply("Done.")
            return reply("", call(n, "run_command", {"CommandLine": f"node t.js # {n}"}))

        def run(args, ws_):
            return ("Error: boom\n[Command exited with code 1]" if "# 3" in args.get("CommandLine", "")
                    else "ok\n[Command exited with code 0]")
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high",
               "effort_auto": True, "effort_reason": "coding task", "reasoning_budget_tokens": 4096,
               "user_text": "fix t.js", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "tool_run_command", side_effect=run), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=12, session_context=ctx)
        levels = [e for e, _ in efforts]
        self.assertEqual(levels[:6], ["high", "medium", "medium", "high", "high", "medium"])
        self.assertEqual(efforts[1][1], 2048)
        self.assertTrue(ctx.get("raised"))

    def test_a_long_failing_command_keeps_its_exit_code(self):
        ws = Path(self.tmp.name) / "ws_long"             # cut to its first 8,000 characters, the run looked like a pass
        ws.mkdir()
        efforts, n = [], 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            efforts.append(k.get("effort"))
            return reply("Done.") if n >= 3 else reply("", call(n, "run_command", {"CommandLine": f"node t.js # {n}"}))

        def run(args, ws_):
            return ("x" * 20000 + "\nFAIL t clears 4 rows\n[Command exited with code 1]"
                    if "# 1" in args.get("CommandLine", "") else "ok\n[Command exited with code 0]")
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high",
               "effort_auto": True, "effort_reason": "coding task", "reasoning_budget_tokens": 4096,
               "user_text": "fix t.js", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "tool_run_command", side_effect=run), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=5, session_context=ctx)
        first = next(str(m["content"]) for m in msgs if m.get("role") == "tool")
        self.assertIn("FAIL t clears 4 rows\n[Command exited with code 1]", first)
        self.assertLess(len(first), 8600)
        self.assertEqual(efforts, ["high", "high", "high"])

    def test_bare_filename_or_model2vec_reason_still_enables_lean_thinking(self):
        ws = Path(self.tmp.name) / "ws_bare"
        ws.mkdir()
        efforts, n = [], 0

        def turn(messages, *a, **k):
            nonlocal n
            n += 1
            efforts.append(k.get("effort"))
            return reply("Done.") if n >= 3 else reply("", call(n, "run_command", {"CommandLine": f"true # {n}"}))

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}]
        ctx = {"workspace": ws, "messages": msgs, "mode": "act", "yolo": True, "effort": "high",
               "effort_auto": True, "effort_reason": "model2vec high", "reasoning_budget_tokens": 4096,
               "user_text": "change S to green and Z to red in tetris.html", "mcp": None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "tool_run_command", return_value="ok\n[Command exited with code 0]"), \
             patch.object(cli, "get_active_tools", return_value=[]), \
             patch.dict(os.environ, {"DL_REVIEW": "0", "DL_CHECKPOINTS": "0", "DL_BROWSER_CHECK": "0",
                                     "DL_EVIDENCE": "0", "DL_ADVISOR": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ws, max_turns=5, session_context=ctx)
        self.assertEqual(efforts, ["high", "medium", "medium"])


if __name__ == "__main__":
    unittest.main()
