"""tools/test_dl_sessiond.py - the shared session daemon without a model: two clients see one session, slash commands,
shell commands behind the approval gate (answered from the other client), and a session that survives a restart.

    python tools/test_dl_sessiond.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Client:
    def __init__(self, path: Path, attach: bool = True):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(20)
        self.s.connect(str(path))
        self.f = self.s.makefile("rwb")
        if attach:
            self.send(op="attach")
            self.hello = self.next()

    def send(self, **msg):
        self.f.write((json.dumps({"session": "t", **msg}) + "\n").encode())
        self.f.flush()

    def next(self) -> dict:
        line = self.f.readline()
        if not line:
            raise EOFError
        return json.loads(line)

    def until(self, pred, limit=200) -> list[dict]:
        seen = []
        for _ in range(limit):
            ev = self.next()
            seen.append(ev)
            if pred(ev):
                return seen
        raise AssertionError(f"not seen in {seen[-5:]}")

    def close(self):
        self.s.close()


class SharedSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "ws"
        self.ws.mkdir()
        self.env = {**os.environ, "HOME": str(root / "home"), "XDG_RUNTIME_DIR": str(root / "run"),
                    "STRATA_URL": "http://127.0.0.1:9", "STRATA_API_KEY": "x"}
        self.sock = root / "run" / "dl-ai" / "sessiond.sock"
        self.start()

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(HERE / "dl_sessiond.py"), "--workspace", str(self.ws)],
                                     env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                Client(self.sock, attach=False).close()
                return
            except OSError:
                time.sleep(0.05)
        self.fail(self.proc.stdout.read().decode())

    def stop(self):
        self.proc.terminate()
        self.proc.wait(10)

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def test_two_clients_one_session(self):
        a, b = Client(self.sock), Client(self.sock)
        self.assertEqual(a.hello["state"]["workspace"], str(self.ws))
        a.send(op="input", text="/think low")
        for c in (a, b):                                       # both see the command and its result
            seen = c.until(lambda e: e["type"] == "turn_end")
            self.assertIn({"user": "/think low"}, [{"user": e.get("text")} for e in seen if e["type"] == "user"])
            self.assertTrue(any(e["type"] == "notice" and "low" in e["text"] for e in seen))
        a.send(op="input", text="!echo hello-from-shell")
        seen = b.until(lambda e: e["type"] == "turn_end")
        self.assertTrue(any(e["type"] == "output" and "hello-from-shell" in e["text"] for e in seen))

    def test_destructive_shell_waits_for_approval(self):
        a, b = Client(self.sock), Client(self.sock)
        victim = self.ws / "victim"
        victim.mkdir()
        a.send(op="input", text=f"!rm -rf {victim}")
        req = b.until(lambda e: e["type"] == "approval_request")[-1]
        self.assertIn("deletes", req["reason"])
        self.assertTrue(victim.exists())
        side = Client(self.sock, attach=False)                 # a one-shot connection, as the web bridge sends
        side.send(op="deny", id=req["id"])
        self.assertEqual(side.next()["type"], "ok")
        seen = a.until(lambda e: e["type"] == "turn_end")
        self.assertTrue(any(e["type"] == "approval_resolved" and not e["ok"] for e in seen))
        self.assertTrue(victim.exists())
        a.send(op="input", text=f"!rm -rf {victim}")
        req = a.until(lambda e: e["type"] == "approval_request")[-1]
        a.send(op="approve", id=req["id"])
        a.until(lambda e: e["type"] == "turn_end")
        self.assertFalse(victim.exists())

    def test_session_survives_restart_and_exports(self):
        a = Client(self.sock)
        a.send(op="input", text="/cd sub")
        a.until(lambda e: e["type"] == "turn_end")
        a.close()
        self.stop()
        self.start()
        b = Client(self.sock)
        self.assertEqual(b.hello["state"]["workspace"], str(self.ws / "sub"))
        self.assertTrue(any(e["type"] == "user" and e["text"] == "/cd sub" for e in b.hello["events"]))
        c = Client(self.sock, attach=False)
        c.send(op="export")
        exp = c.next()
        self.assertTrue(exp["filename"].startswith("dl-ai-code-chat-") and exp["filename"].endswith(".md"))

    def test_busy_and_unknown(self):
        a = Client(self.sock)
        a.send(op="input", text="/nope")
        seen = a.until(lambda e: e["type"] == "turn_end")
        self.assertTrue(any(e["type"] == "notice" and "Unknown command" in e["text"] for e in seen))
        side = Client(self.sock, attach=False)
        side.send(op="approve", id="missing")
        self.assertEqual(side.next()["type"], "error")



class JobApprovalAfterInterrupt(unittest.TestCase):
    """A scheduled job's card must not be denied by an interrupt left over from the user's last turn."""

    def test_own_cancel_event(self):
        import threading
        sys.path.insert(0, str(HERE))
        import dl_sessiond as sessiond
        sess = sessiond.Session("audit-approve", Path(tempfile.mkdtemp()))
        try:
            sess.cancel.set()                                  # the user's last turn was interrupted
            job_cancel = threading.Event()
            got = []
            t = threading.Thread(target=lambda: got.append(sess.approve("tool", "x", "y", cancel=job_cancel)))
            t.start()
            for _ in range(50):
                if sess.pending:
                    break
                time.sleep(0.02)
            self.assertTrue(sess.pending)                      # still waiting, not denied at once
            sess.answer(next(iter(sess.pending)), True)
            t.join(5)
            self.assertEqual(got, [True])
        finally:
            sess.mcp.close()


class ScheduleStop(unittest.TestCase):
    def test_stop_the_running_job(self):
        import threading
        sys.path.insert(0, str(HERE))
        import dl_sessiond as sessiond
        self.assertIn("No scheduled job is running", sessiond.schedule_command("stop", Path(tempfile.mkdtemp())))
        fake = type("S", (), {"cancel": threading.Event()})()
        sessiond.RUNNING.update(job=9, session=fake)
        try:
            self.assertIn("Stopping job #9", sessiond.schedule_command("stop", Path(tempfile.mkdtemp())))
            self.assertTrue(fake.cancel.is_set())
        finally:
            sessiond.RUNNING.clear()


class DamagedSessionFile(unittest.TestCase):
    def test_seq_continues_after_the_highest_shown(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond as sessiond
        from unittest import mock
        d = Path(tempfile.mkdtemp())
        (d / "x.json").write_text(json.dumps({"seq": "bad", "events": [{"type": "text", "seq": 40}, {"seq": 41}],
                                              "messages": []}))
        with mock.patch.object(sessiond, "STATE_DIR", d):
            s = sessiond.Session.load("x", d)
        self.assertEqual(s.seq, 41)
        s.mcp.close()
        (d / "y.json").write_text("null")
        with mock.patch.object(sessiond, "STATE_DIR", d):
            sessiond.Session.load("y", d).mcp.close()
        self.assertTrue(list(d.glob("y.json.unreadable-*")))      # the damaged file is kept


if __name__ == "__main__":
    unittest.main()
