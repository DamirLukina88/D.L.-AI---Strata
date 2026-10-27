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
        (d / "z.json").write_text(json.dumps({"messages": [
            {"role": "system", "content": "old"}, {"role": "user"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_calls": [{"id": "1"}]}, {"role": "weird", "content": "x"}]}))
        with mock.patch.object(sessiond, "STATE_DIR", d):
            z = sessiond.Session.load("z", d)
        self.assertEqual([m["role"] for m in z.messages], ["system", "user", "assistant"])
        self.assertEqual(z.messages[1]["content"], "hi")
        z.mcp.close()
        (d / "y.json").write_text("null")
        with mock.patch.object(sessiond, "STATE_DIR", d):
            sessiond.Session.load("y", d).mcp.close()
        self.assertTrue(list(d.glob("y.json.unreadable-*")))      # the damaged file is kept


class TurnEffort(unittest.TestCase):
    """A prompt sent with its own effort (the web app's spoken prompts: none) runs that turn at it; the session's
    /effort level is left as it was, and a prompt without one uses that level."""

    def test_a_turn_effort_wins_once(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        seen = []
        orig = dl_sessiond.cli.execute_agent_loop
        dl_sessiond.cli.execute_agent_loop = lambda **kw: (seen.append(kw["session_context"]["effort"]),
                                                           kw["workspace"])[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                s = dl_sessiond.Session("t", Path(tmp))
                s.save = lambda: None
                s.effort = "high"
                for effort in ("none", None):
                    s.submit("hello", effort=effort)
                    for _ in range(200):
                        if not s.busy:
                            break
                        time.sleep(0.01)
        finally:
            dl_sessiond.cli.execute_agent_loop = orig
        self.assertEqual(seen, ["none", "high"])
        self.assertEqual(s.effort, "high")

    def test_auto_effort_resolves_per_turn_and_explicit_turn_effort_still_wins(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        seen = []
        orig = dl_sessiond.cli.execute_agent_loop
        dl_sessiond.cli.execute_agent_loop = lambda **kw: (
            seen.append((
                kw["session_context"]["effort"],
                kw["session_context"].get("effort_auto"),
                kw["session_context"].get("reasoning_budget_tokens"),
            )),
            kw["workspace"],
        )[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                s = dl_sessiond.Session("t", Path(tmp))
                s.save = lambda: None
                s._command("/effort auto")
                self.assertEqual(s.effort, "auto")
                for prompt, turn_eff in [
                    ("hello Ray", None),
                    ("what's 15% of 80?", None),
                    ("explain what ROCm is", None),
                    ("fix the failing test in tools/x", None),
                    ("fix the failing test in tools/x", "none"),  # explicit per-turn override (e.g. voice_no_thinking)
                ]:
                    s.submit(prompt, effort=turn_eff)
                    for _ in range(200):
                        if not s.busy:
                            break
                        time.sleep(0.01)
                self.assertEqual(s.last_auto, ("high", "coding task"))
                notices = []
                s.notice = lambda text, level="info": notices.append(text)
                s._command("/effort show")
                self.assertEqual(notices, ["Thinking level: auto (last: high, coding task)"])
        finally:
            dl_sessiond.cli.execute_agent_loop = orig
        self.assertEqual(
            seen,
            [
                ("none", True, 0),
                ("low", True, 1024),
                ("medium", True, 2048),
                ("high", True, 4096),
                ("none", False, 0),
            ],
        )
        self.assertEqual(s.effort, "auto")

    def test_effort_auto_survives_save_and_load(self):
        from unittest import mock
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            with mock.patch.object(dl_sessiond, "STATE_DIR", d):
                s = dl_sessiond.Session("save_test", d)
                s._command("/effort auto")
                s.save()
                loaded = dl_sessiond.Session.load("save_test", d)
                self.assertEqual(loaded.effort, "auto")
                loaded.mcp.close()
                s.mcp.close()

    def test_effort_auto_is_default_and_default_command_sets_it(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        with tempfile.TemporaryDirectory() as tmp:
            s = dl_sessiond.Session("default_test", Path(tmp))
            self.assertEqual(s.effort, "auto")
            s._command("/effort high")
            self.assertEqual(s.effort, "high")
            s._command("/effort default")
            self.assertEqual(s.effort, "auto")
            s.mcp.close()

    def test_effort_bogus_warns(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        with tempfile.TemporaryDirectory() as tmp:
            s = dl_sessiond.Session("t", Path(tmp))
            s.save = lambda: None
            notices = []
            s.notice = lambda text, level="info": notices.append((text, level))
            s._command("/effort bogus")
            self.assertTrue(any("Usage: /effort" in n[0] and n[1] == "warn" for n in notices))
            self.assertEqual(s.effort, "auto")
            s.mcp.close()

    def test_a_spoken_turn_gets_the_voice_note(self):
        """voice: true (the web Code tab's microphone) adds the spoken-answer note to that prompt only."""
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        seen = []
        orig = dl_sessiond.cli.execute_agent_loop
        dl_sessiond.cli.execute_agent_loop = lambda **kw: (seen.append(kw["messages"][-1]["content"]),
                                                           kw["workspace"])[1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                s = dl_sessiond.Session("t", Path(tmp))
                s.save = lambda: None
                for voice in (True, False):
                    s.submit("hello Ray", voice=voice)
                    for _ in range(200):
                        if not s.busy:
                            break
                        time.sleep(0.01)
        finally:
            dl_sessiond.cli.execute_agent_loop = orig
        self.assertIn(dl_sessiond.cli.VOICE_NOTE, seen[0])
        self.assertNotIn("Spoken prompt", seen[1])


class SavedSessions(unittest.TestCase):
    """/clear and /new keep the conversation they end; /sessions lists and searches, /resume brings one back (the
    one it replaces is kept first), /rename and /delete change the list. No model: the turns are written directly."""

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import dl_sessiond
        from unittest import mock
        self.sd = dl_sessiond
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "ws"
        self.ws.mkdir()
        self.patches = [mock.patch.object(dl_sessiond, "STATE_DIR", self.tmp / "sessions"),
                        mock.patch.object(dl_sessiond, "ARCHIVE_DIR", self.tmp / "archive")]
        for p in self.patches:
            p.start()
        self.s = dl_sessiond.Session("t", self.ws)
        self.seen = []
        self.q = __import__("queue").Queue()
        self.s.clients.add(self.q)

    def tearDown(self):
        self.s.mcp.close()
        for p in self.patches:
            p.stop()

    def turn(self, prompt, answer):
        self.s.emit({"type": "user", "text": prompt, "origin": "x"})
        self.s.emit({"type": "text", "text": answer})
        self.s.messages += [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}]

    def cmd(self, text):
        self.s.emit({"type": "user", "text": text, "origin": "x"})
        self.s._command(text)
        out = []
        while not self.q.empty():
            out.append(self.q.get())
        return out

    def notices(self, evs):
        return " ".join(e.get("text", "") for e in evs if e["type"] in ("notice", "output"))

    def test_clear_saves_and_resume_brings_it_back(self):
        self.turn("Fix the parser in tools/x.py", "Done, the parser is fixed.")
        evs = self.cmd("/clear")
        self.assertIn("Fix the parser", self.notices(evs))
        self.assertEqual([m["role"] for m in self.s.messages], ["system"])
        items = self.sd.archive_list("t")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Fix the parser in tools/x.py")
        self.assertEqual(items[0]["turns"], 1)
        data = self.sd.archive_read("t", items[0]["id"])
        self.assertFalse(any(e.get("text") == "/clear" for e in data["events"]))   # not the command that saved it
        self.assertEqual(self.cmd("/clear")[-1]["type"], "state")                 # an empty conversation is not kept
        self.assertEqual(len(self.sd.archive_list("t")), 1)

        self.turn("Second task: write the docs", "Docs written.")
        evs = self.cmd("/resume 1")
        restored = [e for e in evs if e["type"] == "restored"]
        self.assertEqual(len(restored), 1)
        self.assertTrue(any(e.get("text") == "Done, the parser is fixed." for e in restored[0]["events"]))
        self.assertEqual(self.s.messages[1]["content"], "Fix the parser in tools/x.py")
        self.assertEqual(self.s.messages[0]["role"], "system")
        titles = [m["title"] for m in self.sd.archive_list("t")]
        self.assertEqual(titles, ["Second task: write the docs"])                 # the live one left the list
        # cleared again, it goes back under its old id (not a second copy)
        old_id = self.s.archive_id
        self.cmd("/new")
        self.assertIn(old_id, [m["id"] for m in self.sd.archive_list("t")])
        self.assertEqual(len(self.sd.archive_list("t")), 2)

    def test_search_rename_delete(self):
        self.turn("Plan the garden lights", "Use the group light.garden.")
        self.cmd("/new")
        self.turn("Benchmark the engine", "4K prompt 302 tok/s.")
        self.cmd("/new")
        self.assertEqual([m["n"] for m in self.sd.archive_list("t")], [1, 2])
        found = self.sd.archive_list("t", "302 tok")
        self.assertEqual([m["title"] for m in found], ["Benchmark the engine"])
        self.assertIn("302 tok/s", found[0]["snippet"])
        self.assertEqual(found[0]["n"], 1)                                        # the number of the full list
        self.assertIn("garden", self.notices(self.cmd("/sessions garden")))
        self.cmd("/rename 2 Garden lighting")
        self.assertEqual(self.sd.archive_list("t")[1]["title"], "Garden lighting")
        self.cmd("/rename My live task")
        self.assertEqual(self.s.state()["title"], "My live task")
        self.assertIn("Deleted", self.notices(self.cmd("/delete 1")))
        self.assertEqual([m["title"] for m in self.sd.archive_list("t")], ["Garden lighting"])
        self.assertTrue(list((self.tmp / "archive" / "t" / ".deleted").glob("*.json")))   # recoverable
        self.assertIn("No saved conversation", self.notices(self.cmd("/resume 9")))
        (self.tmp / "archive" / "t" / "index.json").write_text("{broken")
        self.assertEqual([m["title"] for m in self.sd.archive_list("t")], ["Garden lighting"])  # rebuilt from files

    def test_saved_fields_survive_a_restart(self):
        self.turn("Keep me", "ok")
        self.cmd("/new")
        self.cmd("/resume 1")
        self.cmd("/rename Kept")
        self.s.save()
        again = self.sd.Session.load("t", self.ws)
        self.assertEqual((again.archive_id, again.title), (self.s.archive_id, "Kept"))
        again.mcp.close()


class RewindEditBranch(SavedSessions):
    """/rewind N, /edit N <text> and /branch N [text] go back to just before a prompt: its event and its user
    message (found by the dl_turn mark) and everything after them leave the conversation."""

    def turn(self, prompt, answer):
        self.s.emit({"type": "user", "text": prompt, "origin": "me"})
        self.s.messages += [{"role": "user", "content": prompt, "dl_turn": self.s.seq},
                            {"role": "assistant", "content": answer}]
        self.s.emit({"type": "text", "text": answer})

    def three(self):
        self.turn("first prompt", "first answer")
        self.turn("second prompt", "second answer")
        self.turn("third prompt", "third answer")

    def test_prompts_and_rewind(self):
        self.three()
        self.assertIn("2. second prompt", self.notices(self.cmd("/prompts")))
        self.s._turn_origin = "me"
        evs = self.cmd("/rewind 2")
        self.assertEqual([m.get("content") for m in self.s.messages[1:]], ["first prompt", "first answer"])
        self.assertEqual([e.get("text") for e in self.s.events if e["type"] in ("user", "text")],
                         ["first prompt", "first answer"])
        restored = [e for e in evs if e["type"] == "restored"]
        self.assertEqual(len(restored), 1)
        self.assertEqual([e for e in evs if e["type"] == "rewound"][0]["text"], "second prompt")
        self.assertEqual(self.s.messages[0]["role"], "system")

    def test_edit_returns_the_new_prompt_as_its_own_turn(self):
        self.three()
        self.s.emit({"type": "user", "text": "/edit 3 a better third", "origin": "me"})
        self.s._turn_origin = "me"
        prompt = self.s._command("/edit 3 a better third")
        self.assertEqual(prompt, "a better third")
        users = [e for e in self.s.events if e["type"] == "user"]
        self.assertEqual([e["text"] for e in users], ["first prompt", "second prompt", "a better third"])
        self.assertEqual(self.s._turn_seq, users[-1]["seq"])                     # the agent marks its message
        self.assertEqual(len(self.s.messages), 5)                                 # system + two turns
        self.assertIn("Usage", self.notices(self.cmd("/edit 2")))

    def test_branch_keeps_the_whole_conversation(self):
        self.three()
        self.cmd("/rename Big task")
        self.cmd("/branch 2")
        saved = self.sd.archive_list("t")
        self.assertEqual([(m["title"], m["turns"]) for m in saved], [("Big task", 3)])
        self.assertEqual([m.get("content") for m in self.s.messages[1:]], ["first prompt", "first answer"])
        self.assertIsNone(self.s.archive_id)
        self.assertEqual(self.s.title, "Big task (branch)")
        self.cmd("/new")                                                           # the branch is saved apart
        self.assertEqual(sorted(m["title"] for m in self.sd.archive_list("t")), ["Big task", "Big task (branch)"])

    def test_web_ref_unmarked_prompt_and_trimmed_prompt(self):
        self.three()
        second = [e for e in self.s.events if e.get("text") == "second prompt"][0]
        for m in self.s.messages:                                                  # a session from before the marks
            m.pop("dl_turn", None)
        self.cmd(f"/rewind @{second['seq']}")
        self.assertEqual(len(self.s.messages), 3)
        self.turn("again", "ok")
        self.s.messages = [m for m in self.s.messages if m.get("content") != "again"]   # trimmed away
        evs = self.cmd("/rewind 2")
        self.assertIn("no longer in the model's context", self.notices(evs))
        self.assertEqual(len(self.prompts_now()), 2)                               # nothing was cut
        self.assertIn("N from 1 to 2", self.notices(self.cmd("/rewind 7")))

    def test_unmarked_prompt_inside_a_built_message(self):
        """2026-10-27: a prompt sent before the marks is stored as "[Now: ...]\\n<prompt>" (with_now), or as parts."""
        self.s.emit({"type": "user", "text": "how are you?", "origin": "me"})
        self.s.messages += [{"role": "user", "content": "[Now: utorak, 27.10.2026. 17:44 (Europe/Zagreb)]\nhow are you?"},
                            {"role": "assistant", "content": "fine"}]
        self.s.emit({"type": "user", "text": "look at this\n@shot.png", "origin": "me"})
        self.s.messages += [{"role": "user", "content": [{"type": "text", "text": "[Now: x]\nlook at this\n(image)"},
                                                         {"type": "image_url", "image_url": {"url": "data:"}}]},
                            {"role": "assistant", "content": "a cat"}]
        self.cmd("/rewind 2")
        self.assertEqual(len(self.s.messages), 3)
        self.cmd("/branch 1")
        self.assertEqual([m["role"] for m in self.s.messages], ["system"])
        self.assertEqual(self.sd.archive_list("t")[0]["turns"], 1)

    def prompts_now(self):
        return self.s.prompt_events()

    def test_the_mark_is_not_sent_to_the_model(self):
        import dl_cli
        from unittest import mock
        sent = {}

        def fake(req, *a, **k):
            sent.update(json.loads(req.data))
            raise OSError("stop here")
        with mock.patch.object(dl_cli.urllib.request, "urlopen", fake):
            try:
                dl_cli.stream_chat_turn([{"role": "user", "content": "hi", "dl_turn": 5}], "http://127.0.0.1:9", "x")
            except Exception:
                pass
        self.assertEqual(sent.get("messages"), [{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
