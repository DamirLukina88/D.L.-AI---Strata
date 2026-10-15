"""tools/test_dl_context.py - D.L. CLI's context budget without a model: staged compaction of a long agent session,
tool calls kept paired with their results, the note for removed messages, and the retry after Strata refuses a
prompt as too long (a fake server).

    python tools/test_dl_context.py
"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
