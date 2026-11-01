"""tools/test_dl_context.py - D.L. CLI's context budget without a model: staged compaction of a long agent session,
tool calls kept paired with their results, the note for removed messages, and the retry after Strata refuses a
prompt as too long (a fake server).

    python tools/test_dl_context.py
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli  # noqa: E402

GAME = "const x = 1;\n" * 2000                     # a 26 kB file, written whole like the TETRIS run did


def session(rounds: int) -> list[dict]:
    """system, task, then `rounds` x (assistant reasoning + write_to_file, tool result)."""
    msgs = [{"role": "system", "content": "You are D.L. AI."}, {"role": "user", "content": "build tetris"}]
    for i in range(rounds):
        msgs.append({"role": "assistant", "content": "", "reasoning_content": "thinking " * 800,
                     "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
                         "name": "write_to_file",
                         "arguments": json.dumps({"TargetFile": "/w/t.html", "CodeContent": GAME})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "write_to_file",
                     "content": "Successfully wrote\n" + "line\n" * 1500})
    return msgs


def paired(msgs: list[dict]) -> bool:
    """Every tool message answers a tool call of the assistant message before its run of tool messages."""
    open_ids: set = set()
    for m in msgs:
        if m["role"] == "assistant":
            open_ids = {tc["id"] for tc in m.get("tool_calls") or []}
        elif m["role"] == "tool":
            if m["tool_call_id"] not in open_ids:
                return False
        else:
            open_ids = set()
    return True


class Compaction(unittest.TestCase):
    def test_under_the_limit_nothing_changes(self):
        msgs = session(2)
        before = json.dumps(msgs)
        self.assertIsNone(cli.compact_history(msgs, None, limit=10**6, target=10**5))
        self.assertEqual(json.dumps(msgs), before)

    def test_stage_one_keeps_the_last_six_whole(self):
        msgs = session(8)
        last6 = json.dumps(msgs[-6:])
        est = cli.estimate_prompt_tokens(msgs, None)
        stats = cli.compact_history(msgs, None, limit=est - 1, target=int(est * 0.5))
        self.assertEqual(json.dumps(msgs[-6:]), last6)
        self.assertGreater(stats["reasoning"], 0)
        self.assertGreater(stats["file_contents"], 0)
        self.assertEqual(stats["removed"], 0)
        self.assertLessEqual(stats["after"], int(est * 0.5))
        old = json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(old["TargetFile"], "/w/t.html")             # what was written stays, only the body goes
        self.assertIn("removed by D.L. CLI", old["CodeContent"])
        self.assertTrue(paired(msgs))

    def test_stage_three_removes_whole_units_with_one_note(self):
        msgs = session(30) + [{"role": "user", "content": "audit"}]
        msgs += session(2)[2:]
        stats = cli.compact_history(msgs, None, limit=1000, target=3000, force=True)
        self.assertGreater(stats["removed"], 0)
        self.assertTrue(paired(msgs))
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["content"], "build tetris")
        self.assertTrue(msgs[2]["content"].startswith("[D.L. CLI:"))
        self.assertIn({"role": "user", "content": "audit"}, msgs)       # the latest request is never removed
        first = int(msgs[2]["content"].split()[2])
        msgs += session(30)[2:]                                         # the session goes on and fills up again
        cli.compact_history(msgs, None, limit=1000, target=3000, force=True)
        notes = [m for m in msgs if str(m.get("content", "")).startswith("[D.L. CLI:")]
        self.assertEqual(len(notes), 1)                                 # one note, counting on
        self.assertGreater(int(notes[0]["content"].split()[2]), first)
        self.assertTrue(paired(msgs))

    def test_measured_size_is_used(self):
        msgs = session(1)
        self.assertEqual(cli.estimate_prompt_tokens(msgs, None, measured=(len(msgs), 5000)), 5000)
        msgs.append({"role": "user", "content": "x" * 280})
        self.assertEqual(cli.estimate_prompt_tokens(msgs, None, measured=(len(msgs) - 1, 5000)), 5000 + 104)


# ---------------------------------------------------------------------------------------------------- refused prompt
class Strict(BaseHTTPRequestHandler):
    """A server with a small context that refuses long prompts the way Strata does."""
    limit_chars = 60000
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"max_context": 40000}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        size = len(json.dumps(req["messages"]))
        Strict.seen.append(size)
        if size > Strict.limit_chars:
            body = json.dumps({"error": {"type": "invalid_request_error", "message":
                               f"request exceeds the context window: prompt ({size // 3} tokens) leaves no room "
                               "to answer in the context (40000); requests are never truncated"}}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunk = {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": size // 3, "completion_tokens": 1}}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


class Refused(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Strict)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        Strict.seen = []

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_compacts_before_sending(self):
        events = []
        msgs = session(12)
        res = cli.chat_turn_in_context(msgs, self.url, "k", [], emit=events.append)
        self.assertEqual(res["content"], "ok")
        self.assertEqual(res["prompt_tokens"], Strict.seen[-1] // 3)
        self.assertEqual(len(Strict.seen), 1)                           # fitted first, no refusal needed
        self.assertTrue(any(e["type"] == "notice" and e["text"].startswith("Context ") for e in events))

    def test_retries_once_after_a_refusal(self):
        events = []
        msgs = session(2)                                               # under the budget by estimate...
        Strict.limit_chars = len(json.dumps(msgs)) - 1                  # ...but the server says too long
        reserve, cli.CONTEXT_RESERVE = cli.CONTEXT_RESERVE, 0
        try:
            res = cli.chat_turn_in_context(msgs, self.url, "k", [], emit=events.append)
        finally:
            Strict.limit_chars = 60000
            cli.CONTEXT_RESERVE = reserve
        self.assertEqual(res["content"], "ok")
        self.assertEqual(len(Strict.seen), 2)
        self.assertLess(Strict.seen[1], Strict.seen[0])
        self.assertTrue(paired(msgs))


class CrashOnceHandler(BaseHTTPRequestHandler):
    """First POST streams an SSE error chunk + [DONE] (as serve/server.py does on EngineDied); second POST succeeds."""
    calls = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"max_context": 65536}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        _ = self.rfile.read(int(self.headers["Content-Length"]))
        CrashOnceHandler.calls += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if CrashOnceHandler.calls == 1:
            err = {"error": {"type": "server_error",
                             "message": "the engine stopped unexpectedly; the next request restarts it"}}
            self.wfile.write(f"data: {json.dumps(err)}\n\ndata: [DONE]\n\n".encode())
            return
        chunk = {"choices": [{"delta": {"content": "resumed after reload"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 120, "completion_tokens": 3}}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


class StreamErrorAndHandoff(unittest.TestCase):
    def test_sse_error_raises_and_retries_mid_turn(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), CrashOnceHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}"
        try:
            CrashOnceHandler.calls = 0
            msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
            # Direct stream_chat_turn must raise RuntimeError on SSE error chunk instead of returning finish_reason=stop
            with self.assertRaisesRegex(RuntimeError, "the engine stopped unexpectedly"):
                cli.stream_chat_turn(msgs, url, "k", [])

            # chat_turn_in_context must catch the transient engine stop, wait briefly, and retry automatically
            CrashOnceHandler.calls = 0
            events = []
            with patch.dict(os.environ, {"DL_ENGINE_RETRY_WAIT_S": "0.01"}):
                res = cli.chat_turn_in_context(msgs, url, "k", [], emit=events.append)
            self.assertEqual(res["content"], "resumed after reload")
            self.assertEqual(CrashOnceHandler.calls, 2)
            self.assertTrue(any(e["type"] == "notice" and "retrying (1/" in e["text"] for e in events))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_wiki_handoff_writes_diary_and_reloads_clean_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "wiki").mkdir()
            msgs = session(25)
            # Inject a failed command in round 10 to verify dead-end capture
            msgs[21]["content"] = "Command exited with code 1: error: undefined symbol gdn_head"
            before = cli.estimate_prompt_tokens(msgs, None)
            self.assertGreater(before, 50000)

            events = []
            with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "0"}):
                stats = cli.fit_context(msgs, None, "", "", emit=events.append, workspace=ws)
            self.assertIsNotNone(stats)
            self.assertEqual(stats["handoff"], 1)
            self.assertEqual(stats["diary"], "wiki/handoffs/latest.md")
            self.assertLess(stats["after"], 4000)
            self.assertTrue(paired(msgs))
            self.assertEqual(msgs[0]["role"], "system")
            self.assertEqual(msgs[1]["content"], "build tetris")
            self.assertIn("Session handoff #1", msgs[2]["content"])
            self.assertIn("## Goal & Live State", msgs[2]["content"])
            self.assertIn("## Completed & Verified", msgs[2]["content"])
            self.assertIn("## Dead Ends / Ruled Out", msgs[2]["content"])
            self.assertIn("gdn_head", msgs[2]["content"])
            self.assertIn("## Next Immediate Action", msgs[2]["content"])
            self.assertTrue((ws / "wiki" / "handoffs" / "latest.md").is_file())
            self.assertEqual(len(list((ws / "wiki" / "handoffs").glob("handoff-*-part-1.md"))), 1)
            self.assertTrue(any("wiki handoff #1" in e["text"] for e in events))

            # Continue working until the context fills a second time -> Handoff #2 preserves prior dead ends
            first_removed = stats["removed"]
            msgs += session(25)[2:]
            with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "0"}):
                stats2 = cli.fit_context(msgs, None, "", "", emit=events.append, workspace=ws)
            self.assertEqual(stats2["handoff"], 2)
            self.assertLess(stats2["after"], 4000)
            self.assertTrue(paired(msgs))
            handoff_notes = [m for m in msgs if "Session handoff #" in str(m.get("content", ""))]
            self.assertEqual(len(handoff_notes), 1)
            self.assertIn("Session handoff #2", handoff_notes[0]["content"])
            self.assertIn(f"{first_removed + stats2['removed']} earlier messages", handoff_notes[0]["content"])
            self.assertIn("gdn_head", handoff_notes[0]["content"])
            self.assertEqual(len(list((ws / "wiki" / "handoffs").glob("handoff-*-part-2.md"))), 1)

    def test_in_session_handoff_uses_live_prefix(self):
        class RecordingHandler(BaseHTTPRequestHandler):
            reqs = []
            def log_message(self, *a): pass
            def do_GET(self):
                body = json.dumps({"max_context": 65536}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                data = json.loads(raw)
                RecordingHandler.reqs.append(data)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                content = (
                    "## Goal & Live State\n- Workspace: /tmp\n- Task: build tetris\n\n"
                    "## Completed & Verified\n- Initial exploration done.\n\n"
                    "## Dead Ends / Ruled Out\n- None recorded in this stretch.\n\n"
                    "## Next Immediate Action\n- Complete next step\n"
                )
                chunk = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 52000, "completion_tokens": 150}}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

        RecordingHandler.reqs = []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp)
                (ws / "wiki").mkdir()
                msgs = session(25)
                active_tools = [{"type": "function", "function": {"name": "run_command"}}]
                with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "1"}):
                    stats = cli.fit_context(msgs, active_tools, url, "k", workspace=ws, in_session=True)
                self.assertIsNotNone(stats)
                self.assertEqual(stats["handoff"], 1)
                self.assertTrue(stats.get("in_session"))
                self.assertEqual(len(RecordingHandler.reqs), 1)
                req = RecordingHandler.reqs[0]
                # Tools passed unchanged
                self.assertEqual(req.get("tools"), active_tools)
                # Last message in request was the in-session prompt
                self.assertEqual(req["messages"][-1]["content"], cli.IN_SESSION_HANDOFF_PROMPT)
                # The in-session prompt was popped and is NOT in msgs afterwards
                self.assertFalse(any(m.get("content") == cli.IN_SESSION_HANDOFF_PROMPT for m in msgs))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_digest_fallback_above_61k(self):
        class DigestHandler(BaseHTTPRequestHandler):
            reqs = []
            def log_message(self, *a): pass
            def do_GET(self):
                body = json.dumps({"max_context": 65536}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                DigestHandler.reqs.append(json.loads(raw))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                content = (
                    "## Goal & Live State\n- Workspace: /tmp\n- Task: build tetris\n\n"
                    "## Completed & Verified\n- Initial exploration done.\n\n"
                    "## Dead Ends / Ruled Out\n- None recorded in this stretch.\n\n"
                    "## Next Immediate Action\n- Complete next step\n"
                )
                chunk = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 1200, "completion_tokens": 120}}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

        DigestHandler.reqs = []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), DigestHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp)
                (ws / "wiki").mkdir()
                # 31 rounds -> tokens > 61k (ctx - 4500)
                msgs = session(31)
                active_tools = [{"type": "function", "function": {"name": "run_command"}}]
                with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "1"}):
                    stats = cli.fit_context(msgs, active_tools, url, "k", workspace=ws)
                self.assertIsNotNone(stats)
                self.assertFalse(stats.get("in_session"))
                self.assertEqual(len(DigestHandler.reqs), 1)
                req = DigestHandler.reqs[0]
                # Digest mode uses empty tools and HANDOFF_SYSTEM prompt
                self.assertEqual(req.get("tools"), [])
                self.assertEqual(req["messages"][0]["content"], cli.HANDOFF_SYSTEM)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_digest_after_overflow_refusal(self):
        class OverflowHandler(BaseHTTPRequestHandler):
            calls = 0
            reqs = []
            def log_message(self, *a): pass
            def do_GET(self):
                body = json.dumps({"max_context": 65536}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                data = json.loads(raw)
                OverflowHandler.reqs.append(data)
                OverflowHandler.calls += 1
                if OverflowHandler.calls == 1:
                    # First call refuses as too long
                    body = json.dumps({"error": {"type": "invalid_request_error",
                                       "message": "request exceeds the context window: prompt (62000 tokens) leaves no room "
                                                  "to answer in the context (65536); requests are never truncated"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if OverflowHandler.calls == 2:
                    content = (
                        "## Goal & Live State\n- Workspace: /tmp\n- Task: build tetris\n\n"
                        "## Completed & Verified\n- Initial exploration done.\n\n"
                        "## Dead Ends / Ruled Out\n- None recorded in this stretch.\n\n"
                        "## Next Immediate Action\n- Complete next step\n"
                    )
                else:
                    content = "Turn resumed in clean session"
                chunk = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 1000, "completion_tokens": 50}}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

        OverflowHandler.calls = 0
        OverflowHandler.reqs = []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), OverflowHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_port}"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp)
                (ws / "wiki").mkdir()
                msgs = session(2)
                active_tools = [{"type": "function", "function": {"name": "run_command"}}]
                with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "1"}):
                    res = cli.chat_turn_in_context(msgs, url, "k", active_tools, workspace=ws)
                self.assertEqual(res["content"], "Turn resumed in clean session")
                self.assertEqual(OverflowHandler.calls, 3)
                # Call 2 was the digest diary (system = HANDOFF_SYSTEM)
                self.assertEqual(OverflowHandler.reqs[1]["messages"][0]["content"], cli.HANDOFF_SYSTEM)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_handoff_pages_not_in_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            wiki_dir = ws / "wiki"
            wiki_dir.mkdir()
            (wiki_dir / "index.md").write_text(
                "---\ntitle: \"Wiki Index\"\ntype: concept\ndescription: \"Index\"\nstatus: active\n"
                "tags: [index]\ncreated: 2026-11-01\nupdated: 2026-11-01\nlast_verified: 2026-11-01\n---\n\n"
                "# Wiki Index\n\n<!-- index:start -->\n<!-- index:end -->\n\n## Sources\n\n1. Wiki.\n",
                encoding="utf-8"
            )
            msgs1 = [{"role": "user", "content": "task 1"}]
            msgs2 = [{"role": "user", "content": "task 2"}]
            msgs3 = [{"role": "user", "content": "task 3"}]
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 1", 1, 10, messages=msgs1)
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 2", 2, 20, messages=msgs2)
            sys2 = cli.build_dl_system_prompt(ws, "act")
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 3", 3, 30, messages=msgs3)
            sys3 = cli.build_dl_system_prompt(ws, "act")

            # Contains latest.md
            self.assertIn("handoffs/latest.md", sys2)
            self.assertIn("handoffs/latest.md", sys3)
            # Contains NO part-N stretch archives
            self.assertNotIn("part-1", sys2)
            self.assertNotIn("part-2", sys2)
            self.assertNotIn("part-3", sys3)
            # R6: byte-identical system prompt across handoffs 2 and 3!
            self.assertEqual(sys2, sys3)

    def test_handoff_pages_in_wiki_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            wiki_dir = ws / "wiki"
            wiki_dir.mkdir()
            (wiki_dir / "index.md").write_text(
                "---\ntitle: \"Wiki Index\"\ntype: concept\ndescription: \"Index\"\nstatus: active\n"
                "tags: [index]\ncreated: 2026-11-01\nupdated: 2026-11-01\nlast_verified: 2026-11-01\n---\n\n"
                "# Wiki Index\n\n<!-- index:start -->\n<!-- index:end -->\n\n## Sources\n\n1. Wiki.\n",
                encoding="utf-8"
            )
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 1", 1, 10)
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 2", 2, 20)
            cli.save_handoff_diary(ws, "## Goal & Live State\n- Task 3", 3, 30)

            # All 3 archives exist on disk
            self.assertTrue((wiki_dir / "handoffs" / "latest.md").is_file())
            self.assertEqual(len(list((wiki_dir / "handoffs").glob("handoff-*-part-*.md"))), 3)

            wscript = cli.find_wiki_script(ws)
            if wscript:
                res = subprocess.run([sys.executable, str(wscript), "lint", "--root", str(wiki_dir)],
                                     capture_output=True, text=True, cwd=ws)
                # wiki.py lint must report 0 errors for wiki/handoffs/
                self.assertEqual(res.returncode, 0, f"wiki.py lint failed: {res.stdout}\n{res.stderr}")

    def test_diary_does_not_tick_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "wiki").mkdir()
            plan_file = ws / "PLAN.md"
            plan_file.write_text("# Plan\n- [ ] Step 1: one\n- [ ] Step 2: two\n", encoding="utf-8")
            msgs = session(25)
            # Handoff diary claims Step 2 is done, but R2 ensures it is NOT automatically ticked
            with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "0"}):
                cli.fit_context(msgs, None, "", "", workspace=ws, plan_file=plan_file)
            plan_after = plan_file.read_text(encoding="utf-8")
            self.assertIn("- [ ] Step 1: one", plan_after)
            self.assertIn("- [ ] Step 2: two", plan_after)
            self.assertNotIn("- [x]", plan_after)

    def test_no_back_to_back_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "wiki").mkdir()
            # 40k protected paste: 20000 words * 2 = 40000 chars / ~13k tokens
            big_paste = "print('data')\n" * 12000
            msgs = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": f"BIG PASTE:\n{big_paste}"}]
            # Add normal rounds to cross 50k
            msgs += session(20)[2:]
            before = cli.estimate_prompt_tokens(msgs, None)
            self.assertGreater(before, 50000)

            # First crossing triggers handoff #1
            with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "0"}):
                stats1 = cli.fit_context(msgs, None, "", "", workspace=ws)
            self.assertIsNotNone(stats1)
            self.assertEqual(stats1.get("handoff"), 1)

            # Next 3 rounds: each adds a small turn. Total prompt is still high (>40k) because of the protected paste,
            # but growth since handoff is < HANDOFF_MIN_GROWTH (8000), so R3 guard uses compact_history (0 extra handoffs).
            for round_num in range(3):
                msgs.append({"role": "user", "content": f"step {round_num}"})
                msgs.append({"role": "assistant", "content": "ok"})
                with patch.dict(os.environ, {"DL_HANDOFF": "1", "DL_HANDOFF_LLM": "0"}):
                    stats = cli.handoff_session(msgs, None, limit=1000, target=20000, ws=ws, force=False)
                # Must be compact_history (no "handoff" key)
                self.assertIsNotNone(stats)
                self.assertNotIn("handoff", stats)
            # Only 1 handoff archive created
            archives = list((ws / "wiki" / "handoffs").glob("handoff-*-part-*.md"))
            self.assertEqual(len(archives), 1)

    def test_archive_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            wiki_dir = ws / "wiki"
            wiki_dir.mkdir()
            msgs = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "fetch status"},
                {"role": "assistant", "tool_calls": [{
                    "id": "c1", "type": "function", "function": {
                        "name": "run_command",
                        "arguments": json.dumps({"CommandLine": "curl -H 'Authorization: Bearer sk-ant-api03-mocktest1234567890abcdef1234567890' https://api.anthropic.com"})
                    }
                }]},
                {"role": "tool", "tool_call_id": "c1", "name": "run_command",
                 "content": "export GITHUB_TOKEN=ghp_mocktest1234567890123456789012345678\nDone"}
            ]
            diary = "## Goal & Live State\n- Task: test\n## Completed & Verified\n- ok\n## Dead Ends / Ruled Out\n- none\n## Next Immediate Action\n- cont"
            latest_path, _, archive_rel = cli.save_handoff_diary(ws, diary, 1, 4, messages=msgs)
            archive_path = ws / archive_rel

            latest_text = latest_path.read_text(encoding="utf-8")
            archive_text = archive_path.read_text(encoding="utf-8")

            # Neither contains the raw tokens
            self.assertNotIn("sk-ant-api03-", archive_text)
            self.assertNotIn("ghp_1234567890", archive_text)
            # Contains redacted tags
            self.assertIn("[redacted:", archive_text)

            wscript = cli.find_wiki_script(ws)
            if wscript:
                proc = subprocess.run([sys.executable, str(wscript), "scan-secrets"],
                                      input=archive_text, capture_output=True, text=True, cwd=ws)
                self.assertEqual(proc.returncode, 0, f"wiki.py scan-secrets failed: {proc.stderr}")

    def test_on_handoff_snapshot(self):
        import dl_sessiond
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            ws = td / "ws"
            ws.mkdir()
            archive_dir = td / "archive"
            with patch.object(dl_sessiond, "ARCHIVE_DIR", archive_dir):
                sess = dl_sessiond.Session("test-sess", ws)
                sess.title = "Build tetris game"
                for i in range(15):
                    sess.messages.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})
                    sess.events.append({"type": "user" if i % 2 == 0 else "assistant", "text": f"msg {i}", "ts": time.time(), "seq": i})

                pre_count = len(sess.messages)
                aid = sess.snapshot_before_handoff(part=1)
                self.assertIsNotNone(aid)
                # Live session retained its identity
                self.assertEqual(sess.title, "Build tetris game")
                self.assertIsNone(sess.archive_id)

                # Snapshot on disk contains all pre-reset messages
                saved_file = archive_dir / "test-sess" / f"{aid}.json"
                self.assertTrue(saved_file.is_file())
                data = json.loads(saved_file.read_text(encoding="utf-8"))
                self.assertEqual(len(data["messages"]), pre_count)
                self.assertIn("handoff #1", data["title"])

    def test_fallback_dead_ends_precise(self):
        ws = Path("/tmp")
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "search and test"},
            {"role": "assistant", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "grep -rn 'error' src/"})}},
                {"id": "c2", "type": "function", "function": {"name": "run_command", "arguments": json.dumps({"CommandLine": "python3 test.py"})}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "name": "run_command",
             "content": "src/main.py:42: # check for error condition\nsrc/utils.py:10: error_count = 0"},
            {"role": "tool", "tool_call_id": "c2", "name": "run_command",
             "content": "Command exited with code 2:\nTraceback (most recent call last):\n  File 'test.py', line 1\nSyntaxError: invalid syntax"},
        ]
        diary = cli._fallback_handoff_diary(msgs, ws)
        # c1 (grep) must NOT be under Dead Ends
        self.assertNotIn("grep", diary.split("## Dead Ends / Ruled Out")[1])
        # c2 (python3 test.py) MUST be under Dead Ends
        self.assertIn("python3 test.py", diary.split("## Dead Ends / Ruled Out")[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
