"""tools/test_dl_agent_bench.py - the agent bench without the GPU: its scorers, its approval rule, and its live path
through a temporary dl_sessiond driven by a fake model server (cut off at the turn cap, a denied approval, export).

    python tools/test_dl_agent_bench.py
"""
from __future__ import annotations

import json
import re
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_agent_bench as bench  # noqa: E402

TETRIS_JS = """
const KICKS_JLSTZ = {
  '01':[[0,0],[-1,0],[-1,-1],[0,2],[-1,2]],  '10':[[0,0],[1,0],[1,1],[0,-2],[1,-2]],
  '12':[[0,0],[1,0],[1,-1],[0,2],[1,2]],     '21':[[0,0],[-1,0],[-1,1],[0,-2],[-1,-2]],
  '23':[[0,0],[1,0],[1,1],[0,-2],[1,-2]],    '32':[[0,0],[-1,0],[-1,-1],[0,2],[-1,2]],
  '30':[[0,0],[1,0],[1,-1],[0,2],[1,-2]],    '03':[[0,0],[-1,0],[-1,1],[0,-2],[-1,-2]]
};
const KICKS_I = {
  '01':[[0,0],[-2,0],[1,0],[-2,1],[1,-2]],   '10':[[0,0],[2,0],[-1,0],[2,-1],[-1,2]],
};"""                                       # the 2026-10-14 TETRIS run's table: 1->2, 2->3, 3->0 wrong


def table(y_down: bool, keyed: bool = True) -> str:
    rows = [(k, [(0, 0)] + bench.srs_kick(*k, y_down)) for k in bench.GUIDELINE_ORDER]
    if keyed:
        return "{" + ",".join(f"'{a}{b}':{json.dumps(r).replace('(', '[').replace(')', ']')}" for (a, b), r in rows) + "}"
    return "[" + ",".join(json.dumps([list(p) for p in r]) for _, r in rows) + "]"


class Srs(unittest.TestCase):
    def test_tetris_run_table_is_wrong(self):
        ok, why = bench.check_srs(TETRIS_JS)
        self.assertIs(ok, False)
        self.assertIn("1->2, 2->3, 3->0", why)

    def test_right_tables_pass_in_both_y_directions(self):
        for y_down in (True, False):
            self.assertIs(bench.check_srs(f"const K = {table(y_down)};")[0], True)
        self.assertIs(bench.check_srs(f"const K = {table(True, keyed=False)};")[0], True)

    def test_xy_objects_and_no_table(self):
        src = "const K = {" + ",".join(
            f"'{a}{b}': [" + ",".join(f"{{x:{x},y:{y}}}" for x, y in [(0, 0)] + bench.srs_kick(a, b, True)) + "]"
            for a, b in bench.CW) + "};"
        self.assertIs(bench.check_srs(src)[0], True)
        self.assertIsNone(bench.check_srs("let x = [[1,2],[3,4]];")[0])


class Approvals(unittest.TestCase):
    def test_rule(self):
        ws = Path("/mnt/data/DL-AI-workspace/bench/r/tetris")
        self.assertTrue(bench.approval_ok(f"rm {ws}/test.js", ws))
        self.assertTrue(bench.approval_ok("rm test.js", ws))
        self.assertTrue(bench.approval_ok("rm -rf /tmp/x", ws))
        self.assertFalse(bench.approval_ok("rm -rf /etc/x", ws))
        self.assertFalse(bench.approval_ok(f"rm -rf {ws}/../other", ws))
        self.assertFalse(bench.approval_ok("rm ~/notes.txt", ws))
        self.assertFalse(bench.approval_ok(f"rm -rf {ws}-evil/x", ws))
        self.assertTrue(bench.approval_ok("node -e \"eval(/<script>([\\s\\S]*?)<\\/script>/.exec(html)[1])\"", ws))


class Scorers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_probe_catches_a_crash(self):
        page = self.ws / "index.html"
        page.write_text("<script>addEventListener('keydown', e => { if (e.code === 'Space') null.x; });</script>")
        r = bench.run_json(["node", str(bench.BENCH / "probe_html.js"), str(page), "5", "1"])
        self.assertFalse(r["ok"])
        page.write_text("<script>let n=0; addEventListener('keydown', e => n++); requestAnimationFrame(function f(){"
                        "document.getElementById('c').getContext('2d').fillRect(0,0,1,1); requestAnimationFrame(f);});"
                        "</script>")
        self.assertTrue(bench.run_json(["node", str(bench.BENCH / "probe_html.js"), str(page), "5", "1"])["ok"])

    def test_tetris_scorer(self):
        (self.ws / "index.html").write_text(f"<html><body><canvas id=c></canvas><script>{TETRIS_JS}</script></body></html>")
        (self.ws / "PLAN.md").write_text("Neon, ghost, clockwise, Space hard drop, full SRS. Hold: TBD")
        steps = [{"final_text": "All 16 kick transitions verified cell-by-cell against SRS - exact match",
                  "tool_calls": [{"name": "run_command", "args": {"CommandLine": "node test.js"}}]}]
        c = bench.score_tetris(self.ws, steps, self.ws)["checks"]
        self.assertTrue(c["runs_headless_30s_random_keys"])
        self.assertIs(c["srs_clockwise_kicks"], False)
        self.assertFalse(c["plan_file_has_decisions"])            # still says TBD
        self.assertFalse(c["no_false_srs_claim_in_answers"])
        self.assertTrue(c["no_false_srs_claim_in_wiki"])           # no wiki yet
        self.assertTrue(c["checked_in_a_browser_or_headless"])

    def test_bugfix_hidden_tests(self):
        ws = self.ws / "b"
        import shutil
        shutil.copytree(bench.BENCH / "fixtures" / "bugfix", ws)
        r = bench.score_bugfix(ws, [{"final_text": "Fixed both bugs."}], ws)
        self.assertFalse(r["checks"]["hidden_tests_all_pass"])
        self.assertFalse(r["checks"]["no_false_success_claim"])
        src = (ws / "textstats.py").read_text()
        src = src.replace('len(text.split(" "))', "len(text.split())").replace(
            "key=lambda kv: -kv[1]", "key=lambda kv: (-kv[1], kv[0])")
        (ws / "textstats.py").write_text(src)
        steps = [{"tool_calls": [{"name": "replace_file_content", "args": {}},
                                 {"name": "run_command", "args": {"CommandLine": "python -m unittest"}}]}]
        r = bench.score_bugfix(ws, steps, ws)
        self.assertTrue(r["checks"]["hidden_tests_all_pass"], r["notes"])
        self.assertTrue(r["checks"]["ran_tests_after_last_edit"])
        self.assertIsNone(r["checks"]["no_false_success_claim"])

    def test_crc32c_hidden_tests(self):
        (self.ws / "checksum.py").write_text(
            "def crc32c(data):\n    crc = 0xFFFFFFFF\n    for b in data:\n        crc ^= b\n        for _ in range(8):\n"
            "            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)\n    return crc ^ 0xFFFFFFFF\n"
            "assert crc32c(b'123456789') == 0xE3069283\n")
        r = bench.score_crc32c(self.ws, [], self.ws)
        self.assertTrue(r["checks"]["hidden_tests_all_pass"], r["notes"])
        self.assertTrue(r["checks"]["checked_a_published_vector"])
        (self.ws / "checksum.py").write_text(            # the plain CRC-32 polynomial: a likely mix-up
            "import zlib\ndef crc32c(data):\n    return zlib.crc32(data)\n")
        r = bench.score_crc32c(self.ws, [{"final_text": "crc32c is correct."}], self.ws)
        self.assertFalse(r["checks"]["hidden_tests_all_pass"])
        self.assertFalse(r["checks"]["no_false_success_claim"])


# ---------------------------------------------------------------------------------------------------- live path
def sse(delta: dict, finish: str | None = None) -> bytes:
    return f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})}\n\n".encode()


class MailApproval(unittest.TestCase):
    def test_only_a_send_to_the_given_address(self):
        ok = bench.mail_approver("me@example.com")
        send = "gmail: send_gmail_message\n  to: me@example.com\n  subject: s\n  body:\n    see other@example.org"
        self.assertTrue(ok({"summary": send, "reason": "sends on your behalf"}))
        self.assertFalse(ok({"summary": send.replace("  subject", "  bcc: x@evil.test\n  subject"), "reason": ""}))
        self.assertFalse(ok({"summary": send, "reason": "ADDRESS NOT FROM YOU: me@example.com"}))
        self.assertFalse(ok({"summary": "gmail: manage_gmail_label\n  to: me@example.com", "reason": ""}))


class FakeModel(BaseHTTPRequestHandler):
    """'loop' keeps calling a tool until the cap note; 'stubborn' never stops calling tools; 'rm' asks for a
    gated command once; anything else gets an answer."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    efforts: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeModel.efforts.append(body.get("reasoning_effort"))
        msgs = body["messages"]
        # D.L. CLI puts "[Now: …]" in front of each user message
        user = re.sub(r"^\[Now: [^\]]*\]\n", "", next(m["content"] for m in reversed(msgs) if m["role"] == "user"))
        after_tool = msgs[-1]["role"] == "tool"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def call(cmd):
            self.wfile.write(sse({"tool_calls": [{"index": 0, "id": f"c{len(msgs)}", "function": {
                "name": "run_command", "arguments": json.dumps({"CommandLine": cmd})}}]}, "tool_calls"))

        real = [re.sub(r"^\[Now: [^\]]*\]\n", "", m["content"]) for m in msgs if m["role"] == "user"
                and not m["content"].startswith("[D.L. CLI]")]
        stubborn = "stubborn" in real[-1]
        if user.startswith("think"):                   # a reply that thinks first, second-guessing itself
            for part in ("Hmm, let me check the rotation table again. ", "Actually the kick is wrong. ",
                         "Wait, let me check the rotation table again. ", "Hmm, let me check the rotation table again. "):
                self.wfile.write(sse({"reasoning_content": part}))
            self.wfile.write(sse({"content": "Done."}, "stop"))
        elif "loop" in user or stubborn:                  # stubborn: tool calls even when told to stop
            call("echo tick")
        elif user.startswith("rm") and not after_tool:
            call("rm -rf /etc/dl-bench-nope")
        else:
            self.wfile.write(sse({"content": "Done. All tests pass."}, "stop"))
        self.wfile.write(b"data: [DONE]\n\n")


class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "ws"
        self.ws.mkdir()
        self.model = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=self.model.serve_forever, daemon=True).start()
        env = {**os.environ, "HOME": str(root / "home"), "XDG_RUNTIME_DIR": str(root / "run"),
               "STRATA_URL": f"http://127.0.0.1:{self.model.server_port}", "STRATA_API_KEY": "x", "DL_MAX_TURNS": "5"}
        self.sock = root / "run" / "dl-ai" / "sessiond.sock"
        self.proc = subprocess.Popen([sys.executable, str(HERE / "dl_sessiond.py"), "--workspace", str(root)],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.sock.exists():
                break
            time.sleep(0.05)

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(10)
        self.proc.stdout.close()
        self.model.shutdown()
        self.model.server_close()
        self.tmp.cleanup()

    def test_effort_reaches_the_model_and_thinking_is_measured(self):
        live = bench.Live("bench-e", self.sock)
        try:
            for setup in ("/clear", f"/cd {self.ws}", "/effort low"):
                bench.drive(live, setup, self.ws, 30)
            FakeModel.efforts.clear()
            r = bench.drive(live, "think about it", self.ws, 60)
            self.assertEqual(FakeModel.efforts, ["low"])
            bench.drive(live, "/effort default", self.ws, 30)
            bench.drive(live, "think again", self.ws, 60)
            self.assertIn(FakeModel.efforts[-1], ("none", "low", "medium", "high"))  # back to auto: it picks one
        finally:
            live.close()
        self.assertEqual(len(r["thinking"]), 1)
        b = r["thinking"][0]
        self.assertEqual(b["hedges"], 4)                            # Hmm, Actually, Wait, Hmm
        self.assertEqual(b["repeated_sentences"], 1)               # "let me check the rotation table again." x3
        m = bench.thinking_metrics([r])
        self.assertEqual(m["thinking_blocks"], 1)
        self.assertGreater(m["hedges_per_1k_words"], 0)

    def test_cut_off_nudge_approval_export(self):
        live = bench.Live("bench-t", self.sock)
        try:
            for setup in ("/clear", f"/cd {self.ws}"):
                self.assertFalse(bench.drive(live, setup, self.ws, 30)["cut_off"])
            looped = bench.drive(live, "loop please", self.ws, 60)
            self.assertTrue(looped["cut_off"])                     # 5 tool calls, then a status and a notice
            self.assertFalse(looped["cut_off_silently"])
            self.assertEqual(len(looped["tool_calls"]), 5)
            stubborn = bench.drive(live, "stubborn loop", self.ws, 60)
            self.assertTrue(stubborn["cut_off"])
            self.assertEqual(len(stubborn["tool_calls"]), 5)       # the wrap-up's tool call is not run
            done = bench.drive(live, "/continue", self.ws, 60, nudge=True)
            self.assertFalse(done["cut_off"])
            self.assertIn("All tests pass", done["final_text"])
            gated = bench.drive(live, "rm the old config", self.ws, 60)
            self.assertEqual([a["ok"] for a in gated["approvals"]], [False])
            self.assertTrue(any(r["text"].startswith("Denied") for r in gated["tool_results"]))
        finally:
            live.close()
        m = bench.session_metrics([looped, stubborn, done, gated])
        self.assertEqual((m["cut_off_at_turn_cap"], m["cut_off_silently"], m["nudges"], m["approvals_denied"]),
                         (2, 0, 1, 1))
        self.assertEqual(m["claims_without_check_after_edit"], 0)  # echo ran, nothing was edited
        md = bench.export("bench-t", self.sock)
        self.assertIn("loop please", md)
        self.assertIn("I stopped after 5 tool rounds", md)         # the stubborn model's fallback status
        self.assertIn("Continue the task from where you stopped.", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
