"""tools/test_dl_memory.py - D.L. CLI keeps the task and uses its memory files, without a model: trimming keeps the
user's own messages (the CONTRA run of 2026-10-19 lost its task to a D.L. CLI note), the plan is saved as PLAN.md on
approval, AGENTS.md / CLAUDE.md / the plan's Progress / the wiki's pages are in the system prompt, and the finish
checks (done check, browser check, evidence check, reviewer) send the agent back when it stops too early.

    python tools/test_dl_memory.py
"""
from __future__ import annotations

import json
import os
import time
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli  # noqa: E402

BIG = "x" * 9000                                   # a long tool result, like a harness run


def contra_like(rounds: int) -> list[dict]:
    """system, an unrelated first message, the real task, then work, a text-tool-call note and more work - the
    shape of the CONTRA session when it lost its task."""
    msgs = [{"role": "system", "content": "You are D.L. AI."},
            {"role": "user", "content": "[Now: Mon]\ncreate a folder called CONTRA"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "[Now: Mon]\nbuild the game, then email it"}]
    for i in range(rounds):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
                     "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "node t.mjs"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "run_command", "content": BIG})
        if i == rounds // 2:
            msgs.append({"role": "user", "content": cli.TEXT_CALL_NOTE})
    return msgs


def reply(content="", calls=None):
    return {"content": content, "reasoning": "", "tokens": 10, "prompt_tokens": 100,
            "finish_reason": "tool_calls" if calls else "stop", "tool_calls": calls or []}


def call(i, name, args):
    return [{"id": f"t{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]


class Trimming(unittest.TestCase):
    def test_a_note_cannot_push_the_task_out(self):
        msgs = contra_like(40)
        cli.compact_history(msgs, None, limit=20000, target=12000, force=True)
        texts = [m.get("content") for m in msgs if m.get("role") == "user"]
        self.assertIn("[Now: Mon]\nbuild the game, then email it", texts)
        self.assertIn("[Now: Mon]\ncreate a folder called CONTRA", texts)
        self.assertTrue(any(str(t).startswith("[D.L. CLI:") for t in texts))     # the trim note

    def test_every_tool_call_keeps_its_result(self):
        msgs = contra_like(40)
        cli.compact_history(msgs, None, limit=20000, target=12000, force=True)
        ids = {tc["id"] for m in msgs for tc in m.get("tool_calls") or []}
        results = {m["tool_call_id"] for m in msgs if m.get("role") == "tool"}
        self.assertEqual(ids, results)

    def test_a_huge_paste_is_not_kept_forever(self):
        msgs = contra_like(10)
        msgs.insert(4, {"role": "user", "content": "[Now: Mon]\n" + "pasted " * 20000})
        msgs.append({"role": "user", "content": "[Now: Mon]\nnow fix the bug"})
        keep = cli.protected_user_messages(msgs, 12000)
        self.assertIn(1, keep)                                # first
        self.assertIn(len(msgs) - 1, keep)                   # latest
        self.assertNotIn(4, keep)                            # over the budget

    def test_notes_are_recognised(self):
        self.assertTrue(cli.is_cli_note({"role": "user", "content": cli.TEXT_CALL_NOTE}))
        self.assertTrue(cli.is_cli_note({"role": "user", "content": cli.DROPPED.format(n=3)}))
        self.assertFalse(cli.is_cli_note({"role": "user", "content": "[Now: x]\nhello"}))
        self.assertFalse(cli.is_cli_note({"role": "assistant", "content": "[D.L. CLI] x"}))


PLAN = """# Plan

1. one
2. two

## Progress

- [x] S1 one
- [ ] S2 two
- [ ] S3 three

## Notes
not part of it
- [ ] not counted
"""


class Memory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_progress(self):
        (self.ws / "PLAN.md").write_text(PLAN)
        section, open_items, done, blocked = cli.plan_progress(self.ws / "PLAN.md")
        self.assertEqual(open_items, ["S2 two", "S3 three"])
        self.assertEqual(done, ["S1 one"])
        self.assertFalse(blocked)
        self.assertNotIn("not counted", section)
        (self.ws / "PLAN.md").write_text(PLAN.replace("## Notes", "Blocked: no node\n\n## Notes"))
        self.assertTrue(cli.plan_progress(self.ws / "PLAN.md")[3])
        (self.ws / "P2.md").write_text("# no checklist\n- [ ] x\n")
        self.assertEqual(cli.plan_progress(self.ws / "P2.md")[1], [])

    def test_memory_section(self):
        (self.ws / "AGENTS.md").write_text("Rule: timers count in frames.")
        (self.ws / "CLAUDE.md").write_text("Rule: timers count in frames.")
        (self.ws / "PLAN.md").write_text(PLAN)
        p1 = cli.build_dl_system_prompt(self.ws, "act", self.ws / "PLAN.md")
        self.assertIn("timers count in frames", p1)
        self.assertEqual(p1.count("timers count in frames"), 1)          # an identical CLAUDE.md is not repeated
        self.assertIn('progress="1 done, 2 open"', p1)
        self.assertEqual(p1, cli.build_dl_system_prompt(self.ws, "act", self.ws / "PLAN.md"))   # stable bytes
        (self.ws / "CLAUDE.md").write_text("@AGENTS.md\n")
        self.assertNotIn('path="CLAUDE.md"', cli.build_dl_system_prompt(self.ws, "act"))
        (self.ws / "CLAUDE.md").write_text("Only for Claude Code.")
        self.assertIn("Only for Claude Code.", cli.build_dl_system_prompt(self.ws, "act"))
        self.assertIn("timers count in frames", cli.build_dl_system_prompt(self.ws, "plan"))
        (self.ws / "AGENTS.md").write_text("y" * 20000)
        self.assertIn("more chars - view_file AGENTS.md", cli.build_dl_system_prompt(self.ws, "act"))

    def test_no_memory_files_no_section(self):
        self.assertNotIn("<project_memory>", cli.build_dl_system_prompt(self.ws, "act"))

    def test_wiki_pages_listed(self):
        (self.ws / "wiki").mkdir()
        (self.ws / "wiki" / "index.md").write_text("# Index\n\n- [Respawn freeze](decisions/r.md) - why 180 frames\n")
        self.assertIn("Respawn freeze", cli.build_dl_system_prompt(self.ws, "act"))

    def test_save_approved_plan(self):
        msgs = [{"role": "user", "content": "plan it"}, {"role": "assistant", "content": "# Plan\n1. a\n2. b"}]
        p = cli.save_approved_plan(msgs, self.ws)
        self.assertEqual(p, self.ws / "PLAN.md")
        text = p.read_text()
        self.assertIn("## Progress", text)                               # added when the plan had none
        msgs[-1]["content"] = PLAN
        cli.save_approved_plan(msgs, self.ws)
        self.assertEqual((self.ws / "PLAN.md").read_text().strip(), PLAN.strip())
        self.assertEqual(len(list(self.ws.glob("PLAN.*.md"))), 1)       # the older plan is kept

    def test_wiki_schema_lists_new_page_fields(self):
        wiki = next(t for t in cli.DL_TOOLS if t["function"]["name"] == "local_wiki")
        props = wiki["function"]["parameters"]["properties"]
        for f in ("page_type", "slug", "title", "description"):
            self.assertIn(f, props)


class FinishChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.notices = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_loop(self, replies, yolo=True, plan=None, dispatch=None, env=None):
        it = iter(replies)
        sent = []

        def fake_turn(messages, url, api_key, tools, **kw):
            sent.append([dict(m) for m in messages])
            return next(it)

        def emit(ev):
            if ev.get("type") == "notice":
                self.notices.append(ev["text"])

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ndo the plan"}]
        ctx = {"workspace": self.ws, "messages": msgs, "mode": "act", "yolo": yolo, "emit": emit,
               "plan_file": str(plan) if plan else None}
        env = {"DL_REVIEW": "0", "DL_BROWSER_CHECK": "0", **(env or {})}
        with patch.object(cli, "chat_turn_in_context", side_effect=fake_turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=dispatch or (lambda *a, **k: "ok")), \
             patch.dict("os.environ", env):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", self.ws, max_turns=30, session_context=ctx)
        return msgs, ctx, sent

    def test_done_check_sends_back_until_ticked(self):
        plan = self.ws / "PLAN.md"
        plan.write_text(PLAN)

        def tick(name, args, ws, **kw):
            plan.write_text(PLAN.replace("- [ ] S2 two", "- [x] S2 two").replace("- [ ] S3 three", "- [x] S3 three"))
            return "ticked"

        msgs, ctx, _ = self.run_loop([reply("done!"), reply("", call(1, "run_command", {"CommandLine": "x"})),
                                      reply("all done")], plan=plan, dispatch=tick)
        self.assertTrue(any(str(m.get("content", "")).startswith("[D.L. CLI] PLAN.md still has 2 open")
                            for m in msgs))
        self.assertTrue(any("Plan complete" in n for n in self.notices))
        self.assertIsNone(ctx["plan_file"])

    def test_plan_without_checklist_asks_for_one(self):
        plan = self.ws / "PLAN.md"
        plan.write_text("# Plan\n1. a\n2. b\n")

        def add(name, args, ws, **kw):
            plan.write_text("# Plan\n\n## Progress\n- [x] a\n- [x] b\n")
            return "added"

        msgs, ctx, _ = self.run_loop([reply("done"), reply("", call(1, "run_command", {"CommandLine": "x"})),
                                      reply("done")], plan=plan, dispatch=add)
        self.assertTrue(any("Progress\" checklist to the plan" in str(m.get("content", "")) for m in msgs))
        self.assertIsNone(ctx["plan_file"])

    def test_done_check_stops_at_blocked(self):
        plan = self.ws / "PLAN.md"
        plan.write_text(PLAN.replace("## Notes", "Blocked: the card is gone\n\n## Notes"))
        msgs, _, _ = self.run_loop([reply("cannot go on")], plan=plan)
        self.assertEqual(msgs[-1]["content"], "cannot go on")
        self.assertTrue(any("blocked" in n for n in self.notices))

    def test_done_check_stops_when_nothing_changes(self):
        plan = self.ws / "PLAN.md"
        plan.write_text(PLAN)
        msgs, _, _ = self.run_loop([reply("done")] * 10, plan=plan)
        sendbacks = sum(1 for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI] PLAN.md still"))
        self.assertEqual(sendbacks, cli.DONE_STALL_LIMIT)
        self.assertTrue(any("nothing in the folder changed" in n for n in self.notices))

    def test_without_yolo_only_a_notice(self):
        plan = self.ws / "PLAN.md"
        plan.write_text(PLAN)
        msgs, _, _ = self.run_loop([reply("done")], yolo=False, plan=plan)
        self.assertEqual(msgs[-1]["content"], "done")
        self.assertTrue(any("still open; /continue" in n for n in self.notices))

    def test_evidence_check_once(self):
        target = self.ws / "a.py"

        def write(name, args, ws, **kw):
            target.write_text("x = 2\n")
            return "written"

        msgs, _, _ = self.run_loop([reply("", call(1, "write_to_file", {"TargetFile": str(target)})),
                                    reply("All tests pass."), reply("All tests pass.")], dispatch=write)
        notes = [m for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI] Your answer says")]
        self.assertEqual(len(notes), 1)

    def test_no_evidence_note_after_a_check(self):
        target = self.ws / "a.py"

        def act(name, args, ws, **kw):
            if name == "write_to_file":
                target.write_text("x = 2\n")
            return "ok"

        msgs, _, _ = self.run_loop([reply("", call(1, "write_to_file", {"TargetFile": str(target)})),
                                    reply("", call(2, "run_command", {"CommandLine": "python3 -m unittest"})),
                                    reply("All tests pass.")], dispatch=act)
        self.assertFalse(any(str(m.get("content", "")).startswith("[D.L. CLI] Your answer says") for m in msgs))

    def test_reviewer_findings_go_back_once(self):
        target = self.ws / "a.py"

        def write(name, args, ws, **kw):
            target.write_text("def f():\n    return 1\n")
            return "written"

        with patch.object(cli, "stream_chat_turn", return_value={"content": "- a.py:2 - returns 1, task wants 2"}):
            msgs, _, _ = self.run_loop([reply("", call(1, "write_to_file", {"TargetFile": str(target)})),
                                        reply("finished"), reply("fixed it")], dispatch=write,
                                       env={"DL_REVIEW": "1", "DL_EVIDENCE": "0"})
        notes = [m for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI] A reviewer")]
        self.assertEqual(len(notes), 1)
        self.assertIn("returns 1, task wants 2", notes[0]["content"])
        self.assertEqual(msgs[-1]["content"], "fixed it")

    def test_reviewer_no_problems(self):
        target = self.ws / "a.py"

        def write(name, args, ws, **kw):
            target.write_text("y\n")
            return "written"

        with patch.object(cli, "stream_chat_turn", return_value={"content": "NO PROBLEMS"}):
            msgs, _, _ = self.run_loop([reply("", call(1, "write_to_file", {"TargetFile": str(target)})),
                                        reply("finished")], dispatch=write, env={"DL_REVIEW": "1", "DL_EVIDENCE": "0"})
        self.assertEqual(msgs[-1]["content"], "finished")
        self.assertTrue(any("no problems" in n for n in self.notices))

    def test_browser_check_reports_errors(self):
        page = self.ws / "index.html"

        def write(name, args, ws, **kw):
            page.write_text("<script>boom(</script>")
            return "written"

        with patch.object(cli, "browser_errors", return_value=(["uncaught: SyntaxError"], "")):
            msgs, _, _ = self.run_loop([reply("", call(1, "write_to_file", {"TargetFile": str(page)})),
                                        reply("finished"), reply("fixed")], dispatch=write,
                                       env={"DL_BROWSER_CHECK": "1", "DL_EVIDENCE": "0"})
        self.assertTrue(any(str(m.get("content", "")).startswith("[D.L. CLI] Browser check") for m in msgs))

    def test_trim_refreshes_memory(self):
        (self.ws / "AGENTS.md").write_text("Rule A")
        msgs = [{"role": "system", "content": "old"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": self.ws, "messages": msgs, "mode": "act", "yolo": False, "emit": lambda e: None}
        with patch.object(cli, "chat_turn_in_context", return_value=reply("done")), \
             patch.dict("os.environ", {"DL_REVIEW": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", self.ws, session_context=ctx)
        self.assertIn("Rule A", msgs[0]["content"])                       # refreshed at the start of the request


class Counters(unittest.TestCase):
    def test_yolo_notice_counts_all_rounds(self):
        notices = []
        n = 0

        def turn(*a, **k):
            nonlocal n
            n += 1
            return reply("done") if n > 7 else reply("", call(n, "run_command", {"CommandLine": "x"}))

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": Path(tempfile.mkdtemp()), "messages": msgs, "mode": "act", "yolo": True,
               "emit": lambda e: notices.append(e.get("text", "")) if e.get("type") == "notice" else None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "dispatch_dl_tool", return_value="ok"), patch.dict("os.environ", {"DL_REVIEW": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ctx["workspace"], max_turns=3, session_context=ctx)
        yolo = [t for t in notices if "YOLO" in t]
        self.assertIn("3 tool rounds so far", yolo[0])
        self.assertIn("6 tool rounds so far", yolo[1])

    def run_yolo(self, script, max_turns=3):
        """script: one entry per model call - 'tool', 'textcall', 'loop' or 'done'."""
        it = iter(script)
        notices = []

        def turn(*a, **k):
            kind = next(it)
            if kind == "tool":
                return reply("", call(id(kind), "run_command", {"CommandLine": "x"}))
            if kind == "textcall":
                return reply("<tool_call><function=run_command>")
            if kind == "loop":
                return {**reply(""), "finish_reason": "loop", "loop_sentence": "again."}
            return reply("done")

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": Path(tempfile.mkdtemp()), "messages": msgs, "mode": "act", "yolo": True,
               "emit": lambda e: notices.append(e.get("text", "")) if e.get("type") == "notice" else None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "dispatch_dl_tool", return_value="ok"), patch.dict("os.environ", {"DL_REVIEW": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ctx["workspace"], max_turns=max_turns,
                                   session_context=ctx)
        return msgs, notices

    def test_text_call_on_the_last_round_does_not_end_yolo(self):
        # 2026-10-20 15:39: a text tool call on round 40 of 40 skipped the YOLO reset and ended the CONTRA run
        msgs, notices = self.run_yolo(["tool", "tool", "textcall", "tool", "done"])
        self.assertFalse(any(str(m.get("content", "")).startswith("[D.L. CLI] You have used all") for m in msgs))
        self.assertEqual(msgs[-1]["content"], "done")
        self.assertTrue(any("tool rounds so far" in n for n in notices))

    def test_loop_guard_on_the_last_round_does_not_end_yolo(self):
        msgs, _ = self.run_yolo(["tool", "tool", "loop", "tool", "done"])
        self.assertFalse(any(str(m.get("content", "")).startswith("[D.L. CLI] You have used all") for m in msgs))
        self.assertEqual(msgs[-1]["content"], "done")

    def test_each_stretch_gets_fresh_text_call_retries(self):
        # two text calls per stretch are allowed; a third one in a new stretch is still caught
        msgs, _ = self.run_yolo(["textcall", "textcall", "tool", "textcall", "tool", "done"])
        self.assertEqual(sum(1 for m in msgs if m.get("content") == cli.TEXT_CALL_NOTE), 3)
        self.assertEqual(msgs[-1]["content"], "done")

    def test_prompts_ask_to_tick_each_line(self):
        ws = Path(tempfile.mkdtemp())
        (ws / "PLAN.md").write_text(PLAN)
        self.assertIn("as soon as its own check passes", cli.build_dl_system_prompt(ws, "act", ws / "PLAN.md"))
        self.assertIn("as soon as its own check passes", cli.DONE_NOTE)


class LoopGuard(unittest.TestCase):
    def test_detects_a_loop(self):
        loop = ("Cleaner approach: split the engine from the frontend. That's a decent amount of stub work. "
                "For testing, run the script in node with minimal stubs. ") * 20
        self.assertIsNotNone(cli.thinking_loops("Some real start of the reasoning here, fine. " + loop))

    def test_detects_a_long_cycle(self):
        cycle = "\n".join(f"Idea {i}: maybe check the value against source number {i} before trusting it." for i in range(20))
        self.assertIsNotNone(cli.thinking_loops((cycle + "\n") * 5))

    def test_normal_thinking_passes(self):
        text = " ".join(f"Step {i}: check the value of item number {i} against the table." for i in range(400))
        self.assertIsNone(cli.thinking_loops(text))

    def test_loop_is_dropped_and_retried(self):
        replies = iter([{**reply(""), "finish_reason": "loop", "reasoning": "x" * 50, "loop_sentence": "again."},
                        reply("done")])
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": Path(tempfile.mkdtemp()), "messages": msgs, "mode": "act", "yolo": False,
               "emit": lambda e: None}
        with patch.object(cli, "chat_turn_in_context", side_effect=lambda *a, **k: next(replies)), \
             patch.dict("os.environ", {"DL_REVIEW": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", ctx["workspace"], session_context=ctx)
        self.assertTrue(any(str(m.get("content", "")).startswith("[D.L. CLI] Your thinking went round") for m in msgs))
        self.assertFalse(any(m.get("reasoning_content") == "x" * 50 for m in msgs))     # the loop is not kept
        self.assertEqual(msgs[-1]["content"], "done")


class StandIn(unittest.TestCase):
    """CONTRA, 2026-10-20: the model copied trim stand-ins out of its own trimmed edit calls into new ones, and
    twice overwrote a 14k test file with the one-line stand-in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.f = self.ws / "h14.mjs.part"     # CONTRA's parts: no syntax check
        self.f.write_text("const a = 1;\nconst b = 2;\n")

    def tearDown(self):
        self.tmp.cleanup()

    def trimmed_arg(self) -> str:
        """The stand-in _shrink really leaves, so a change to ELIDED cannot slip past the guard."""
        m = {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {
             "name": "write_to_file", "arguments": json.dumps({"TargetFile": "h14.mjs.part", "CodeContent": "y" * 12035})}}]}
        cli._shrink(m, 400, 4000, {"reasoning": 0, "file_contents": 0, "tool_results": 0})
        return json.loads(m["tool_calls"][0]["function"]["arguments"])["CodeContent"]

    def test_write_of_a_stand_in_is_refused(self):
        out = cli.tool_write_to_file({"TargetFile": "h14.mjs.part", "CodeContent": self.trimmed_arg()}, self.ws)
        self.assertIn("stand_in_guard", out)
        self.assertEqual(self.f.read_text(), "const a = 1;\nconst b = 2;\n")
        out = cli.tool_write_to_file({"TargetFile": "new.mjs", "CodeContent": "x\n" + self.trimmed_arg()}, self.ws)
        self.assertIn("stand_in_guard", out)
        self.assertFalse((self.ws / "new.mjs").exists())

    def test_edit_that_adds_a_stand_in_is_refused(self):
        old_form = "[1,048 chars removed by D.L. CLI to fit the context; the file on disk has the current content - view_file it]"
        result_form = "[... 2,310 chars removed by D.L. CLI to fit the context ...]"
        for stand_in in (self.trimmed_arg(), old_form, result_form):
            out = cli.tool_replace_file_content({"TargetFile": "h14.mjs.part", "TargetContent": "const b = 2;",
                                                 "ReplacementContent": stand_in}, self.ws)
            self.assertIn("stand_in_guard", out)
        self.assertEqual(self.f.read_text(), "const a = 1;\nconst b = 2;\n")

    def test_stand_in_target_says_why_it_is_not_found(self):
        out = cli.tool_replace_file_content({"TargetFile": "h14.mjs.part", "TargetContent": self.trimmed_arg(),
                                             "ReplacementContent": "const c = 3;"}, self.ws)
        self.assertIn("not found", out)
        self.assertIn("stand-in", out)

    def test_repairs_and_files_that_hold_stand_ins_still_work(self):
        stand_in = self.trimmed_arg()
        self.f.write_text(f"const a = 1;\n{stand_in}\n")                  # a bad write from an older run
        out = cli.tool_replace_file_content({"TargetFile": "h14.mjs.part", "TargetContent": "const a = 1;",
                                             "ReplacementContent": "const a = 10;"}, self.ws)
        self.assertIn("Successfully", out)                                  # the stand-in was already there
        out = cli.tool_replace_file_content({"TargetFile": "h14.mjs.part", "TargetContent": stand_in,
                                             "ReplacementContent": "const b = 2;"}, self.ws)
        self.assertIn("Successfully", out)                                  # the repair
        self.assertNotIn("removed by D.L. CLI", self.f.read_text())
        code = 'ELIDED = "[{n:,} chars removed by D.L. CLI to fit the context]"\n'   # D.L. CLI's own source
        out = cli.tool_write_to_file({"TargetFile": "cli.py", "CodeContent": code}, self.ws)
        self.assertIn("Successfully", out)


class Checkpointing(unittest.TestCase):
    """CONTRA, 2026-10-20 21:23: a shell-command edit emptied a 33 KB part and nothing could undo it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws, self.cps = root / "ws", root / "checkpoints"
        (self.ws / "src").mkdir(parents=True)
        self.data = self.ws / "src" / "data.part"
        self.data.write_text("const C = 1;\n" * 400)
        patcher = patch.object(cli, "CHECKPOINT_DIR", self.cps)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def git(self, cp, *args):
        import subprocess
        return subprocess.run(["git", f"--git-dir={cp.git_dir}", *args], capture_output=True, text=True,
                              cwd=self.ws).stdout

    def test_alarm_names_the_file_and_the_restore_works(self):
        import subprocess
        notices, n = [], 0

        def turn(*a, **k):
            nonlocal n
            n += 1
            if n == 1:   # the 21:23 accident: the file is opened for writing, then building its text fails
                return reply("", call(1, "run_command", {"CommandLine": "python3 -c \"f=open('src/data.part','w'); "
                                                                       "f.write('x' + 1)\""}))
            return reply("done")

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": self.ws, "messages": msgs, "mode": "act", "yolo": True,
               "emit": lambda e: notices.append(e.get("text", "")) if e.get("type") == "notice" else None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.dict("os.environ", {"DL_REVIEW": "0", "DL_CHECKPOINTS": "1"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", self.ws, max_turns=5, session_context=ctx)
        self.assertEqual(self.data.stat().st_size, 0)
        result = next(m["content"] for m in msgs if m.get("role") == "tool")
        self.assertIn("emptied src/data.part (5,200 -> 0 bytes)", result)
        self.assertTrue(any(t.startswith("Shrink alarm: run_command emptied src/data.part") for t in notices))
        restore = result.split("taken before this round:\n  ", 1)[1].splitlines()[0]
        subprocess.run(restore, shell=True, check=True, cwd=self.ws)
        self.assertEqual(self.data.read_text(), "const C = 1;\n" * 400)
        log = self.git(cli.Checkpoints(self.ws), "log", "--format=%s")
        self.assertEqual(log.split("\n")[:2], ["round 1: run_command", "request start"])

    def test_off_unless_the_entry_point_turns_it_on(self):
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        with patch.object(cli, "chat_turn_in_context", return_value=reply("done")), \
             patch.dict("os.environ", {"DL_REVIEW": "0"}):
            os.environ.pop("DL_CHECKPOINTS", None)
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", self.ws, max_turns=2,
                                   session_context={"workspace": self.ws, "messages": msgs, "mode": "act"})
        self.assertFalse(self.cps.exists())

    def test_shrink_rules(self):
        before = {"a.js": (5000, 1), "b.js": (5000, 1), "c.js": (5000, 1), "small.js": (900, 1),
                  os.path.join("tmp", "x.mjs"): (9000, 1), "d.js": (5000, 1)}
        after = {"a.js": (0, 2), "c.js": (2400, 2), "small.js": (0, 2), "d.js": (2600, 2)}
        self.assertEqual([h[0] for h in cli.shrunk_files(before, after)], ["a.js", "b.js", "c.js"])

    def test_big_files_and_broad_folders_are_left_out(self):
        (self.ws / "model.bin").write_bytes(b"0" * 7000)                   # data.part is 5,200 bytes
        with patch.object(cli, "CHECKPOINT_MAX_FILE", 6000):
            cp = cli.Checkpoints(self.ws)
            self.assertTrue(cp.take("start"))
        self.assertEqual(self.git(cp, f"--work-tree={self.ws}", "ls-files").split(), ["src/data.part"])
        self.assertIsNone(cp.take("again"))                                  # nothing changed
        self.assertTrue(cli.Checkpoints(Path.home()).off)
        with patch.object(cli, "CHECKPOINT_MAX_FILES", 1):
            many = cli.Checkpoints(self.ws)
            self.assertIsNone(many.take("start"))
            self.assertIn("more than 1 files", many.off)


class BigOutput(unittest.TestCase):
    """CONTRA, 2026-10-20 22:12: a debug run printed 105,947 chars; the newest tool result was out of the trimmer's
    reach, so the prompt stayed at 79,813 tokens, Strata refused it twice and the request ended."""

    def history(self):
        return [{"role": "system", "content": "s" * 26000}, {"role": "user", "content": "[Now: x]\ntask"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "run_command", "arguments": json.dumps({"CommandLine": "node dbg.mjs"})}}]},
                {"role": "tool", "tool_call_id": "c1", "name": "run_command",
                 "content": "DBG f=1 live=0 enemies=0\n" * 4200 + "[Command exited with code 0]"}]

    def test_results_are_capped_where_they_enter(self):
        out = cli.cap_tool_result("x" * 100000 + "\n[Command exited with code 0]")
        self.assertLess(len(out), cli.TOOL_RESULT_MAX + 400)
        self.assertTrue(out.endswith("[Command exited with code 0]"))
        self.assertTrue(cli.STAND_IN.search(out))                 # copying the cut output into a file is refused
        self.assertEqual(cli.cap_tool_result("short"), "short")

    def test_overflow_retry_reaches_the_newest_result(self):
        msgs = self.history()
        calls = []

        def stream(messages, **k):
            calls.append(len(messages[-1]["content"]))
            if len(messages[-1]["content"]) > 50000:             # what Strata did with the 106k result
                raise RuntimeError('Strata API HTTP 400: {"error": {"message": "request exceeds the context window: '
                                   'prompt (79813 tokens) leaves no room to answer in the context (65536)"}}')
            return reply("next step")

        with patch.object(cli, "stream_chat_turn", side_effect=stream), \
             patch.object(cli, "context_window", return_value=65536):
            res = cli.chat_turn_in_context(msgs, "http://127.0.0.1:1", "k", [], measured=(4, 30000))
        self.assertEqual(res["content"], "next step")
        self.assertLess(len(msgs[-1]["content"]), 5000)
        self.assertIn("[Command exited with code 0]", msgs[-1]["content"])
        self.assertEqual(msgs[1]["content"], "[Now: x]\ntask")       # the task is still there


@unittest.skipUnless(Path(cli.PLAYWRIGHT_CORE).is_dir() and cli.shutil.which("node"), "needs playwright-core and node")
class RealBrowserCheck(unittest.TestCase):
    """2026-10-20 22:45: the browser check read the wrong process.argv slots and had never run (every call was
    "skipped"); the other tests mock browser_errors, so only a real Chromium run catches that."""

    def test_reports_errors_and_passes_a_clean_page(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = Path(d) / "bad.html", Path(d) / "good.html"
            bad.write_text("<!doctype html><title>t</title><script>console.error('boom'); undefinedThing();</script>")
            good.write_text("<!doctype html><title>t</title><script>document.title = 'ok';</script>")
            errs, why = cli.browser_errors(bad)
            self.assertEqual(why, "")
            self.assertTrue(any("boom" in e for e in errs) and any("undefinedThing" in e for e in errs), errs)
            self.assertEqual(cli.browser_errors(good), ([], ""))


class BuiltPageBrowserCheck(unittest.TestCase):
    """2026-10-20: CONTRA edits src/*.part and builds index.html with a script, so the browser check (which looked
    only at files the edit tools changed) never chose its page, and a YOLO request that runs for hours never reached
    the finish checks at all; in a real browser the page died on its first frame."""
    ERRS = ["uncaught: ReferenceError: roundRectPath is not defined"]

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.page = self.ws / "index.html"
        self.page.write_text("<!doctype html><title>t</title>")
        self.ns = time.time_ns()

    def rebuild(self):                                   # what tools/build.sh does: rewrite the page
        self.ns += 1_000_000
        self.page.write_text(f"<!doctype html><title>{self.ns}</title>")
        os.utime(self.page, ns=(self.ns, self.ns))

    def test_a_built_page_is_checked_when_the_run_ends(self):
        state = {"changes": cli.RequestChanges(self.ws), "pages": cli.web_pages(self.ws)}
        self.rebuild()
        with patch.object(cli, "browser_errors", return_value=(self.ERRS, "")), \
             patch.dict("os.environ", {"DL_REVIEW": "0", "DL_EVIDENCE": "0"}):
            back = cli.finish_checks(state, [], "done", "act", self.ws, {"yolo": True}, "http://127.0.0.1:1", "k")
        self.assertIsNotNone(back)
        self.assertIn("roundRectPath is not defined", back)

    def test_a_long_yolo_run_gets_the_errors_once(self):
        it = iter(["tool"] * 6 + ["done"])

        def turn(*a, **k):
            return reply("", call(time.time_ns(), "run_command", {"CommandLine": "bash tools/build.sh"})) \
                if next(it) == "tool" else reply("done")

        def build(*a, **k):
            self.rebuild()
            return "built index.html"

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "[Now: x]\ntask"}]
        ctx = {"workspace": self.ws, "messages": msgs, "mode": "act", "yolo": True, "emit": lambda e: None}
        with patch.object(cli, "chat_turn_in_context", side_effect=turn), \
             patch.object(cli, "dispatch_dl_tool", side_effect=build), \
             patch.object(cli, "browser_errors", return_value=(self.ERRS, "")), \
             patch.dict("os.environ", {"DL_REVIEW": "0", "DL_EVIDENCE": "0"}):
            cli.execute_agent_loop(msgs, "http://127.0.0.1:1", "k", self.ws, max_turns=2, session_context=ctx)
        live = [m for m in msgs if m.get("role") == "user" and "Browser check during the run" in str(m.get("content"))]
        self.assertEqual(len(live), 1)                    # three auto-continues, the same errors: told once
        self.assertIn("roundRectPath is not defined", live[0]["content"])


class ReviewSeesEverything(unittest.TestCase):
    """2026-10-21: CONTRA's final review saw 1 changed file (the edit tools' own record) while the request had
    changed dozens through shell commands and builds; its 6 findings showed only as a count; and a trim 6 minutes
    later could have dropped the findings before the agent was through them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()
        (self.ws / "game.js").write_text("const speed = 1;\n")
        patcher = patch.object(cli, "CHECKPOINT_DIR", Path(self.tmp.name) / "cps")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_reviewer_gets_shell_edits_and_its_findings_are_shown(self):
        cps = cli.Checkpoints(self.ws)
        cps.take("request start")
        start = cps.head
        (self.ws / "game.js").write_text("const speed = 1;\nconst gravity = -9;\n")   # as a shell command would
        cps.take("round 1: run_command")
        state = {"changes": cli.RequestChanges(self.ws), "pages": {}, "cps": cps, "cp_start": start}
        bodies, events = [], []

        def review(messages, *a, **k):
            bodies.append(messages[1]["content"])
            return reply("- gravity points the wrong way")

        msgs = [{"role": "user", "content": "[Now: x]\nbuild it"}]
        with patch.object(cli, "stream_chat_turn", side_effect=review), \
             patch.dict("os.environ", {"DL_BROWSER_CHECK": "0", "DL_EVIDENCE": "0"}):
            back = cli.finish_checks(state, msgs, "done", "act", self.ws, {"yolo": True}, "http://127.0.0.1:1", "k",
                                     emit=events.append)
        self.assertIn("gravity points the wrong way", back or "")
        self.assertIn("+const gravity = -9;", bodies[0])
        shown = [e for e in events if e.get("type") == "output" and e.get("title") == "Review findings"]
        self.assertEqual(shown[0]["text"], "- gravity points the wrong way")

    def test_the_current_review_note_survives_a_trim(self):
        msgs = contra_like(0)
        msgs.append({"role": "user", "content": cli.REVIEW_NOTE.format(findings="- the audit cannot fail")})
        for i in range(40):
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"r{i}", "type": "function",
                         "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "ls"})}}]})
            msgs.append({"role": "tool", "tool_call_id": f"r{i}", "name": "run_command", "content": BIG})
        cli.compact_history(msgs, None, limit=8000, target=5000, force=True)
        self.assertTrue(any("the audit cannot fail" in str(m.get("content")) for m in msgs))


class Transcript(unittest.TestCase):
    def setUp(self):
        import dl_sessiond as sessiond
        self.sd = sessiond
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(sessiond, "TRANSCRIPT_DIR", Path(self.tmp.name) / "transcripts")
        patcher.start()
        self.addCleanup(patcher.stop)

    def lines(self, name):
        files = sorted((self.sd.TRANSCRIPT_DIR / name).glob("*.jsonl"))
        return [json.loads(x) for f in files for x in f.read_text().splitlines()]

    def test_every_event_once_with_whole_blocks(self):
        s = self.sd.Session("ttest", Path(self.tmp.name))
        with patch.dict("os.environ", {"DL_TRANSCRIPT": "1"}):
            s.emit({"type": "user", "text": "build it"})
            for t in ("thin", "king"):
                s.emit({"type": "thinking", "text": t})
            s.emit({"type": "tool_call", "id": "c1", "name": "run_command", "args": {"CommandLine": "ls"}})
            s.emit({"type": "tool_result", "id": "c1", "name": "run_command", "text": "index.html"})
            for t in ("all ", "done"):
                s.emit({"type": "text", "text": t})
            s.emit({"type": "turn_end"})
            got = self.lines("ttest")
            self.assertEqual([e["type"] for e in got], ["user", "thinking", "tool_call", "tool_result", "text",
                                                        "turn_end"])
            self.assertEqual((got[1]["text"], got[4]["text"]), ("thinking", "all done"))
            md = s.transcript_markdown()
            for part in ("## You", "build it", "<details><summary>Thinking</summary>", "Tool run_command",
                         "index.html", "all done"):
                self.assertIn(part, md)
            s._command("/clear")
            s.emit({"type": "user", "text": "next task"})
            self.assertEqual([e.get("text") for e in s.transcript_events() if e["type"] == "user"], ["next task"])
        s.mcp.close()

    def test_off_unless_the_daemon_turns_it_on(self):
        s = self.sd.Session("toff", Path(self.tmp.name))
        os.environ.pop("DL_TRANSCRIPT", None)
        s.emit({"type": "user", "text": "x"})
        self.assertEqual(self.lines("toff"), [])
        s.mcp.close()


class Daemon(unittest.TestCase):
    def test_act_saves_plan_and_planfile(self):
        import dl_sessiond as sessiond
        ws = Path(tempfile.mkdtemp())
        s = sessiond.Session("memtest", ws)
        s.mode = "plan"
        s.messages.append({"role": "assistant", "content": PLAN})
        prompt = s._command("/act")
        self.assertEqual(s.plan_file, str(ws / "PLAN.md"))
        self.assertIn("PLAN.md", prompt)
        self.assertEqual(s.state()["plan"], {"file": "PLAN.md", "done": 1, "open": 2, "blocked": False})
        self.assertIsNone(s._command("/planfile off"))
        self.assertIsNone(s.plan_file)
        self.assertIsNone(s._command("/planfile PLAN.md"))
        self.assertEqual(s.plan_file, str((ws / "PLAN.md").resolve()))
        s._command("/clear")
        self.assertIsNone(s.plan_file)
        s.mcp.close()

    def test_chip_follows_ticks_during_a_request(self):
        import os
        import queue
        import dl_sessiond as sessiond
        ws = Path(tempfile.mkdtemp())
        plan = ws / "PLAN.md"
        plan.write_text(PLAN)
        s = sessiond.Session("chiptest", ws)
        s.plan_file = str(plan)
        q: queue.Queue = queue.Queue()
        s.clients.add(q)

        def states():
            out = []
            while not q.empty():
                ev = q.get()
                if ev["type"] == "state":
                    out.append(ev["plan"])
            return out

        s.emit({"type": "tool_result", "name": "run_command", "text": "ok"})
        self.assertEqual(states(), [{"file": "PLAN.md", "done": 1, "open": 2, "blocked": False}])
        s.emit({"type": "tool_result", "name": "run_command", "text": "ok"})
        self.assertEqual(states(), [])                                     # unchanged plan: no new state
        plan.write_text(PLAN.replace("- [ ] S2 two", "- [x] S2 two"))
        os.utime(plan, ns=(time.time_ns(), time.time_ns() + 1_000_000))    # a distinct mtime on coarse clocks
        s.emit({"type": "tool_result", "name": "replace_file_content", "text": "ok"})
        self.assertEqual(states(), [{"file": "PLAN.md", "done": 2, "open": 1, "blocked": False}])
        s.emit({"type": "thinking", "text": "x"})
        self.assertEqual(states(), [])                                     # only tool results check the plan
        s.mcp.close()


if __name__ == "__main__":
    unittest.main()
