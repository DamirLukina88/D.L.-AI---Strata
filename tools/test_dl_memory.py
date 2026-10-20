"""tools/test_dl_memory.py - D.L. CLI keeps the task and uses its memory files, without a model: trimming keeps the
user's own messages (the CONTRA run of 2026-10-19 lost its task to a D.L. CLI note), the plan is saved as PLAN.md on
approval, AGENTS.md / CLAUDE.md / the plan's Progress / the wiki's pages are in the system prompt, and the finish
checks (done check, browser check, evidence check, reviewer) send the agent back when it stops too early.

    python tools/test_dl_memory.py
"""
from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
