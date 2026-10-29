"""tools/test_dl_tool_calls.py - how D.L. CLI handles a broken tool call, without a model: a typo of a real tool
name runs that tool, a made-up name gets suggestions, and arguments that are not valid JSON (a reply cut off by the
length limit) come back to the model as an error instead of running the tool with no arguments.

    python tools/test_dl_tool_calls.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli  # noqa: E402


class ToolNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "a.txt").write_text("hello world\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_typo_runs_the_real_tool(self):
        out = cli.dispatch_dl_tool("replace_file_ontent", {"TargetFile": str(self.ws / "a.txt"),
                                                           "TargetContent": "world", "ReplacementContent": "there"},
                                   self.ws)
        self.assertTrue(out.startswith("['replace_file_ontent' is not a tool; ran 'replace_file_content']"), out)
        self.assertEqual((self.ws / "a.txt").read_text(), "hello there\n")

    def test_a_typo_with_arguments_of_another_tool_is_not_run(self):
        out = cli.dispatch_dl_tool("replace_file_contnt", {"path": "a.txt", "old": "x", "new": "y"}, self.ws)
        self.assertTrue(out.startswith("Error: Unknown tool replace_file_contnt. Did you mean 'replace_file_content'"),
                        out)
        self.assertEqual((self.ws / "a.txt").read_text(), "hello world\n")

    def test_a_made_up_name_gets_the_list(self):
        out = cli.dispatch_dl_tool("edit_file", {"x": 1}, self.ws)
        self.assertTrue(out.startswith("Error: Unknown tool edit_file."), out)
        self.assertIn("Tools you have: run_command", out)

    def test_an_alias_runs_the_real_tool(self):
        out = cli.dispatch_dl_tool("write_file", {"TargetFile": str(self.ws / "b.txt"), "CodeContent": "x\n"}, self.ws)
        self.assertTrue(out.startswith("['write_file' is not a tool; ran 'write_to_file']"), out)
        self.assertEqual((self.ws / "b.txt").read_text(), "x\n")

    def test_an_alias_with_other_arguments_is_not_run(self):
        out = cli.dispatch_dl_tool("write_file", {"path": str(self.ws / "b.txt"), "content": "x"}, self.ws)
        self.assertTrue(out.startswith("Error: Unknown tool write_file."), out)
        self.assertFalse((self.ws / "b.txt").exists())

    def test_plan_mode_does_not_turn_a_typo_into_a_write(self):
        out = cli.dispatch_dl_tool("write_to_fle", {"TargetFile": str(self.ws / "b.txt"), "CodeContent": "x"},
                                   self.ws, mode="plan")
        self.assertTrue(out.startswith("Error: Unknown tool"), out)
        self.assertFalse((self.ws / "b.txt").exists())


# ---------------------------------------------------------------------------------------------------- bad JSON
class CutOff(BaseHTTPRequestHandler):
    """First reply: a write_to_file whose arguments stop mid-string (finish_reason length); then plain text."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"max_context": 65536}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        msgs = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if msgs[-1]["role"] == "user":
            delta = {"tool_calls": [{"index": 0, "id": "c1", "function": {
                "name": "write_to_file", "arguments": '{"TargetFile": "/x/t.html", "CodeContent": "<html>' + "x" * 5000}}]}
            chunk = {"choices": [{"delta": delta, "finish_reason": "length"}]}
        else:
            chunk = {"choices": [{"delta": {"content": "noted"}, "finish_reason": "stop"}]}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


class BadArguments(unittest.TestCase):
    def test_cut_off_arguments_come_back_as_an_error(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), CutOff)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "write the page"}]
                events = []
                cli.execute_agent_loop(msgs, f"http://127.0.0.1:{srv.server_port}", "k", Path(d),
                                       session_context={"emit": events.append})
                tool = next(m for m in msgs if m["role"] == "tool")
                self.assertTrue(tool["content"].startswith("Error: the arguments of this write_to_file call are "
                                                           "not valid JSON"), tool["content"])
                self.assertIn("cut off by the length limit", tool["content"])
                self.assertFalse(any(Path(d).iterdir()))           # nothing was written
                self.assertEqual(msgs[-1]["content"], "noted")
        finally:
            srv.shutdown()
            srv.server_close()


# ---------------------------------------------------------------------------------------------------- calls as text
TEXT_CALL = ("Fixing the spawn table now.\n<tool_call>\n<function=replace_file_\n<parameter=parameter>\n"
             "TargetContent>\nold\n</parameter>\n</function>\n</tool_call>")


class TextCalls(BaseHTTPRequestHandler):
    """Writes its tool call as text first (as the 2026-10-14 batch-2 run did); after D.L. CLI's note it sends a
    real one, unless the prompt says "stubborn"."""

    def log_message(self, *a):
        pass

    do_GET = CutOff.do_GET

    def do_POST(self):
        msgs = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
        first = next(m["content"] for m in msgs if m["role"] == "user")
        last = msgs[-1]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if last["role"] == "tool":
            delta, finish = {"content": "done"}, "stop"
        elif "stubborn" in first or last["content"] == first:
            delta, finish = {"content": TEXT_CALL}, "stop"
        else:                                          # after the note: a real call
            delta = {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "write_to_file", "arguments":
                     json.dumps({"TargetFile": first.split()[-1], "CodeContent": "ok\n", "Overwrite": True})}}]}
            finish = "tool_calls"
        chunk = {"choices": [{"delta": delta, "finish_reason": finish}]}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


class CallsWrittenAsText(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), TextCalls)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def run_loop(self, prompt):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": prompt}]
        events = []
        cli.execute_agent_loop(msgs, self.url, "k", Path(self.tmp.name), session_context={"emit": events.append})
        return msgs, events

    def test_the_model_is_told_and_resends_a_real_call(self):
        target = Path(self.tmp.name) / "a.txt"
        msgs, events = self.run_loop(f"write {target}")
        self.assertEqual(target.read_text(), "ok\n")
        self.assertEqual(sum(1 for m in msgs if m["role"] == "user" and m["content"] == cli.TEXT_CALL_NOTE), 1)
        self.assertTrue(any(e["type"] == "notice" and "as text" in e["text"] for e in events))
        self.assertEqual(msgs[-1]["content"], "done")

    def test_a_model_that_keeps_doing_it_is_not_looped_forever(self):
        msgs, events = self.run_loop(f"stubborn {Path(self.tmp.name) / 'b.txt'}")
        notes = sum(1 for m in msgs if m["role"] == "user" and m["content"] == cli.TEXT_CALL_NOTE)
        self.assertEqual(notes, cli.TEXT_CALL_RETRIES)
        self.assertTrue(any(e["type"] == "stats" for e in events))          # the turn ended normally
        self.assertFalse((Path(self.tmp.name) / "b.txt").exists())

    def test_plain_answers_mentioning_tools_are_left_alone(self):
        self.assertIsNone(cli.TEXT_TOOL_CALL.search("I used write_to_file and replace_file_content to fix it."))


# ---------------------------------------------------------------------------------------------------- small talk
class Greeter(BaseHTTPRequestHandler):
    """Answers every user message with a write_to_file call to TARGET, then with text once a tool result is back."""
    TARGET = ""

    def log_message(self, *a):
        pass

    do_GET = CutOff.do_GET

    def do_POST(self):
        msgs = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if msgs[-1]["role"] == "tool":
            delta, finish = {"content": "Doing well!"}, "stop"
        else:
            delta = {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "write_to_file", "arguments":
                     json.dumps({"TargetFile": Greeter.TARGET, "CodeContent": "x\n"})}}]}
            finish = "tool_calls"
        chunk = {"choices": [{"delta": delta, "finish_reason": finish}]}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


class SmallTalkGuard(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Greeter)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        Greeter.TARGET = str(self.ws / "t.txt")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def turn(self, text: str) -> tuple[list[dict], list[dict]]:
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": text}]
        events = []
        cli.execute_agent_loop(msgs, f"http://127.0.0.1:{self.srv.server_port}", "k", self.ws,
                               session_context={"emit": events.append, "user_text": text})
        return msgs, events

    def test_small_talk_answers_the_call_without_running_it(self):
        msgs, events = self.turn("hello Ray, how are you")
        self.assertFalse((self.ws / "t.txt").exists())
        self.assertEqual(next(m for m in msgs if m["role"] == "tool")["content"], cli.SMALL_TALK_NOTE)
        self.assertEqual(next(e for e in events if e["type"] == "tool_call").get("skipped"), "small talk")
        self.assertEqual(msgs[-1]["content"], "Doing well!")

    def test_a_request_after_a_greeting_runs(self):
        self.turn("Hello Ray, please write the file")
        self.assertTrue((self.ws / "t.txt").exists())

    def test_the_guard_can_be_turned_off(self):
        os.environ["DL_SMALLTALK_GUARD"] = "0"
        try:
            self.turn("hello Ray, how are you")
        finally:
            del os.environ["DL_SMALLTALK_GUARD"]
        self.assertTrue((self.ws / "t.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
