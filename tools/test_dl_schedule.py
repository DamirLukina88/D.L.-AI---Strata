# scan-secrets: fake-fixtures (the Google token below is made up to test the credential filter)
"""tools/test_dl_schedule.py - scheduled jobs (tools/dl_schedule.py and the daemon's /schedule): reading the time,
the next run, catch-up after the PC was off, warming the model, a server that is down or drops a job, pre-approved
actions, the approval card and the credential filter.  No model, no network, no real clock.

    python tools/test_dl_schedule.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_schedule as S  # noqa: E402
import dl_mcp  # noqa: E402

# Thu 2026-10-15 20:00 local time
NOW = dt.datetime(2026, 10, 15, 20, 0).timestamp()


def at(*a) -> float:
    return dt.datetime(*a).timestamp()


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "cfg.json").write_text(json.dumps({"notify_email": "me@example.com", "tick_s": 1}))
        self.patches = [mock.patch.object(S, "STORE", d / "schedule.json"),
                        mock.patch.object(S, "CONFIG", d / "cfg.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class When(unittest.TestCase):
    def test_once_forms(self):
        cases = {"2026-10-16 09:00 x": at(2026, 10, 16, 9, 0), "2026-10-16T09:00 x": at(2026, 10, 16, 9, 0),
                 "tomorrow 07:00 x": at(2026, 10, 16, 7, 0), "today 21:30 x": at(2026, 10, 15, 21, 30),
                 "21:15 x": at(2026, 10, 15, 21, 15), "08:00 x": at(2026, 10, 16, 8, 0),
                 "fri 09:00 x": at(2026, 10, 16, 9, 0), "thu 09:00 x": at(2026, 10, 22, 9, 0),
                 "in 2h x": NOW + 7200, "in 1h30m x": NOW + 5400, "in 1h 30m x": NOW + 5400, "in 45 m x": NOW + 2700}
        for text, want in cases.items():
            spec, rest = S.parse_when(text, NOW)
            self.assertEqual((spec["kind"], spec["at"], rest), ("once", want, "x"), text)

    def test_repeating_forms(self):
        self.assertEqual(S.parse_when("daily 08:00 a", NOW)[0], {"kind": "days", "time": "08:00", "days": list(range(7))})
        self.assertEqual(S.parse_when("mon-fri 07:30 a", NOW)[0]["days"], [0, 1, 2, 3, 4])
        self.assertEqual(S.parse_when("weekdays 07:30 a", NOW)[0]["days"], [0, 1, 2, 3, 4])
        self.assertEqual(S.parse_when("every mon,wed 18:00 a", NOW)[0]["days"], [0, 2])
        self.assertEqual(S.parse_when("every fri 09:00 a", NOW)[0]["days"], [4])
        self.assertEqual(S.parse_when("every day 06:00 a", NOW)[0]["days"], list(range(7)))
        self.assertEqual(S.parse_when("sat-mon 10:00 a", NOW)[0]["days"], [0, 5, 6])
        self.assertEqual(S.parse_when("every 2h a", NOW)[0], {"kind": "every", "seconds": 7200, "start": NOW})

    def test_croatian_forms(self):
        cases = {"16.10.2026. 09:00 x": at(2026, 10, 16, 9, 0), "16.10.2026 09:00 x": at(2026, 10, 16, 9, 0),
                 "16.10. 09:00 x": at(2026, 10, 16, 9, 0), "1.10. 09:00 x": at(2027, 10, 1, 9, 0),
                 "sutra 07:00 x": at(2026, 10, 16, 7, 0), "danas 21:30 x": at(2026, 10, 15, 21, 30),
                 "pet 09:00 x": at(2026, 10, 16, 9, 0), "čet 09:00 x": at(2026, 10, 22, 9, 0),
                 "za 2h x": NOW + 7200}
        for text, want in cases.items():
            spec, rest = S.parse_when(text, NOW)
            self.assertEqual((spec["at"], rest), (want, "x"), text)
        self.assertEqual(S.parse_when("pon-pet 07:30 x", NOW)[0]["days"], [0, 1, 2, 3, 4])
        self.assertEqual(S.fmt(at(2026, 10, 16, 21, 30)), "pet 16.10.2026. 21:30")

    def test_too_far_says_so(self):
        with self.assertRaisesRegex(S.WhenError, "year ahead"):
            S.parse_when("in 400d x", NOW)

    def test_only_whole_weekday_words(self):
        for bad in ("wedding 18:00 x", "monitor 09:00 x", "sunny 10:00 x"):
            with self.assertRaises(S.WhenError, msg=bad):
                S.parse_when(bad, NOW)
        self.assertEqual(S.parse_when("friday 09:00 x", NOW)[0]["at"], at(2026, 10, 16, 9, 0))
        self.assertEqual(S.parse_when("srijeda 09:00 x", NOW)[0]["at"], at(2026, 10, 21, 9, 0))
        self.assertEqual(S.parse_when("tue,thu 07:00 x", NOW)[0]["days"], [1, 3])

    def test_day_month_without_the_last_dot(self):
        spec, rest = S.parse_when("16.10 09:00 x", NOW)          # a date when a time follows, not 16:10
        self.assertEqual((spec["at"], rest), (at(2026, 10, 16, 9, 0), "x"))
        spec, rest = S.parse_when("21.30 call mum", NOW)         # a time with a dot stays a time
        self.assertEqual((spec["at"], rest), (at(2026, 10, 15, 21, 30), "call mum"))

    def test_time_that_passed_while_working_runs_at_once(self):
        asked = at(2026, 10, 15, 21, 17)                # the user asked at 21:17 for 21:30 ...
        now = at(2026, 10, 15, 21, 37)                  # ... and the work took until 21:37
        for when in ("21:30 send it", "today 21:30 send it", "2026-10-15 21:30 send it", "15.10.2026. 21:30 send it",
                     "in 13m send it"):
            spec, _ = S.parse_when(when, now, anchor=asked)
            self.assertEqual(spec["at"], now, when)                       # at once, not tomorrow
            self.assertAlmostEqual(spec["planned"], at(2026, 10, 15, 21, 30), delta=60, msg=when)
        spec, _ = S.parse_when("21:00 x", now, anchor=asked)             # already past when asked: tomorrow
        self.assertEqual(spec["at"], at(2026, 10, 16, 21, 0))
        with self.assertRaises(S.WhenError):
            S.parse_when("2026-10-15 21:00 x", now, anchor=asked)

    def test_errors(self):
        for bad in ("in 99999999d x", "every 99999999d x", "31.12.9999. 23:59 x", "9999-12-31 23:59 x", "in 400d x",
                    "", "soon do it", "2026-10-14 09:00 past", "today 19:00 past", "every 10s x", "25:00 x",
                    "in forever x", "2026-13-01 09:00 x"):
            with self.assertRaises(S.WhenError, msg=bad):
                S.parse_when(bad, NOW)

    def test_next_run(self):
        spec = S.parse_when("mon-fri 07:30 a", NOW)[0]
        self.assertEqual(S.next_run(spec, NOW), at(2026, 10, 16, 7, 30))           # Friday
        self.assertEqual(S.next_run(spec, at(2026, 10, 16, 8, 0)), at(2026, 10, 19, 7, 30))   # Monday
        every = {"kind": "every", "seconds": 3600, "start": NOW}
        self.assertEqual(S.next_run(every, NOW + 5000), NOW + 7200)
        self.assertIsNone(S.next_run({"kind": "once", "at": NOW}, NOW))


class Store(Temp):
    def test_tool_add_list_remove(self):
        with mock.patch.object(S.time, "time", return_value=NOW):
            out = S.call("add", {"when": "tomorrow 07:00", "prompt": "summarise my unread mail", "email_result": True})
        self.assertIn("#1 once at pet 16.10.2026. 07:00: summarise my unread mail", out)
        self.assertIn("result by email", out)
        self.assertIn("#1", S.call("list", {}))
        self.assertTrue(S.call("add", {"when": "in 2h"}).startswith("Error: nothing to do"))
        self.assertTrue(S.call("add", {"when": "in 2h", "action": {"tool": "schedule__add", "args": {}}}).startswith("Error"))
        self.assertTrue(S.call("add", {"when": "in 2h", "action": "send it"}).startswith("Error"))
        self.assertEqual(S.call("remove", {"id": 1}), "Removed #1.")
        self.assertEqual(S.call("list", {}), "No scheduled jobs.")

    def test_late_job_summary_and_yolo_from_the_turn(self):
        asked, now = at(2026, 10, 15, 21, 17), at(2026, 10, 15, 21, 37)
        ctx = {"request_time": asked, "yolo": True, "workspace": "/tmp"}
        with mock.patch.object(S.time, "time", return_value=now), mock.patch.object(S, "_context", lambda: ctx):
            out = S.call("add", {"when": "21:30", "prompt": "send the weather"})
        self.assertIn("planned 21:30, already passed: runs at once, 7 min late", out)
        job = S.load()["jobs"][0]
        self.assertEqual((job["yolo"], job["workspace"], job["next"]), (True, "/tmp", now))

    def test_scheduled_action_is_checked_now(self):
        class Reg:
            def owns(self, name):
                return name == "proton__send_mail"

            def unknown_args(self, name, args):
                return "error: proton__send_mail has no parameter 'html_body'" if "html_body" in args else None
        with mock.patch.object(S, "_context", lambda: {"registry": Reg()}):
            out = S.call("add", {"when": "in 1h", "action": {"tool": "gmail__send", "args": {}}})
            self.assertIn("turn on 'gmail' first", out)
            out = S.call("add", {"when": "in 1h", "action": {"tool": "proton__send_mail",
                                                            "args": {"to": "a@example.com", "html_body": "x"}}})
            self.assertIn("no parameter 'html_body'", out)
            self.assertTrue(S.call("add", {"when": "in 1h", "action": {"tool": "proton__send_mail", "args": {
                "to": "a@example.com", "subject": "s", "html": "<b>x</b>"}}}).startswith("Scheduled"))

    def test_a_job_cannot_schedule_or_remove_jobs(self):
        S.add("in 2h keep me", now=NOW)
        with mock.patch.object(S, "_context", lambda: {"job": 7, "yolo": True}):
            self.assertIn("cannot schedule jobs", S.call("add", {"when": "in 1h", "prompt": "again"}))
            self.assertIn("cannot remove jobs", S.call("remove", {"id": 1}))
        self.assertEqual(len(S.load()["jobs"]), 1)

    def test_a_job_that_cannot_be_shown_is_not_saved(self):
        with mock.patch.object(S, "summary", side_effect=ValueError("year 10000")):
            with self.assertRaises(ValueError):
                S.add("in 2h x", now=NOW)
        self.assertEqual(S.load()["jobs"], [])

    def test_a_damaged_entry_does_not_hide_the_others(self):
        S.add("in 2h fine", now=NOW)
        data = S.load()
        data["jobs"].append({"id": 99, "spec": {"kind": "once", "at": 1e15}, "next": 1e15, "enabled": True})
        S.save(data)
        out = S.list_text()
        self.assertIn("#1 ", out)
        self.assertIn("#99 (unreadable entry", out)

    def test_an_unreadable_store_is_kept_not_lost(self):
        S.add("in 2h x", now=NOW)
        S.STORE.write_text('{"next_id": 5, "jobs": [{"id": 4, "when": broken')
        data = S.load()
        self.assertEqual((data["jobs"], data["next_id"]), ([], 5))         # new jobs do not reuse #4
        copies = list(S.STORE.parent.glob("schedule.json.unreadable-*"))
        self.assertEqual(len(copies), 1)
        self.assertIn('"id": 4', copies[0].read_text())
        S.load()                                                             # the same damage is copied once
        self.assertEqual(len(list(S.STORE.parent.glob("schedule.json.unreadable-*"))), 1)

    def test_store_is_private(self):
        S.add("in 2h ping", now=NOW)
        self.assertEqual(S.STORE.stat().st_mode & 0o777, 0o600)


class Runner(Temp):
    def make(self, health=True, prompt_results=None):
        self.clock = [NOW]
        self.posts, self.mails, self.prompts, self.actions, self.warmed = [], [], [], [], []
        results = list(prompt_results or [{"ok": True, "text": "done", "acted": False, "server_error": False}])
        h = health if callable(health) else (lambda: health)

        def run_prompt(job):
            self.prompts.append(job["id"])
            return results.pop(0) if len(results) > 1 else results[0]

        def run_action(job):
            self.actions.append(job["action"])
            return {"ok": True, "text": "Sent"}
        self.sched = S.Scheduler(run_prompt, run_action, h, lambda: self.warmed.append(self.clock[0]),
                                 lambda t, x, level="info": self.posts.append((t, x, level)),
                                 lambda subj, body: self.mails.append((subj, body)),
                                 clock=lambda: self.clock[0], sleep=lambda s: self.clock.__setitem__(0, self.clock[0] + s))
        return self.sched

    def test_runs_when_due_and_once_jobs_finish(self):
        sched = self.make()
        S.add("in 10m check mail", now=NOW)
        self.assertEqual(sched.tick(), [])
        self.clock[0] = NOW + 601
        self.assertEqual(sched.tick(), [1])
        self.assertEqual(sched.tick(), [])
        job = S.load()["jobs"][0]
        self.assertEqual((job["enabled"], job["runs"], job["last"]["status"]), (False, 1, "ok"))
        self.assertIn("done", self.posts[-1][1])
        self.assertEqual(self.mails, [])

    def test_a_job_cut_off_by_a_daemon_stop_is_reported_not_rerun(self):
        sched = self.make()
        S.add("in 1m tidy up", now=NOW)
        data = S.load()
        data["jobs"][0]["running_since"] = NOW               # the daemon died while it ran
        S.save(data)
        self.assertEqual(sched.recover(), [1])
        job = S.load()["jobs"][0]
        self.assertEqual(job["last"]["status"], "interrupted")
        self.assertNotIn("running_since", job)
        self.assertIn("interrupted", self.mails[0][0])
        self.assertEqual(sched.recover(), [])                 # reported once

    def test_running_mark_is_cleared_after_a_run(self):
        sched = self.make()
        S.add("in 1m x", now=NOW)
        self.clock[0] = NOW + 61
        sched.tick()
        self.assertNotIn("running_since", S.load()["jobs"][0])

    def test_reports_go_out_after_the_lock(self):
        sched = self.make()
        held = []
        sched.notify = lambda subj, body: held.append(S._lock._is_owned())
        S.add("2026-10-15 20:30 late", now=NOW)
        self.clock[0] = at(2026, 10, 16, 9, 0)                 # 12.5 h late: skipped, with a notice email
        sched.tick()
        self.assertEqual(held, [False])

    def test_a_damaged_entry_is_switched_off_once(self):
        sched = self.make()
        S.add("in 1m fine", now=NOW)
        data = S.load()
        data["jobs"].append({"id": 50, "next": NOW, "enabled": True})          # no spec
        S.save(data)
        self.clock[0] = NOW + 61
        self.assertEqual(sched.tick(), [1])                                     # the good job still runs
        self.assertEqual(sched.tick(), [])
        bad = next(j for j in S.load()["jobs"] if j["id"] == 50)
        self.assertEqual((bad["enabled"], bad["last"]["status"]), (False, "error"))
        self.assertEqual(sum("switched off" in p[0] for p in self.posts), 1)  # reported once, not every tick

    def test_warms_the_model_before_a_prompt_job(self):
        sched = self.make()
        S.add("in 10m check mail", now=NOW)
        self.clock[0] = NOW + 600 - 120
        with mock.patch.object(S.threading, "Thread") as T:
            T.return_value.start = lambda: sched._warm()
            sched.tick()
            sched.tick()
        self.assertEqual(len(self.warmed), 1)

    def test_catch_up_runs_once_and_skips_when_too_late(self):
        sched = self.make()
        S.add("daily 08:00 morning summary", now=NOW)               # next: Fri 08:00
        self.clock[0] = at(2026, 10, 16, 9, 0)                     # the PC was off at 08:00: one hour late
        self.assertEqual(sched.tick(), [1])
        self.assertIn("late by 60 min", self.posts[-1][0])
        self.assertEqual(S.load()["jobs"][0]["next"], at(2026, 10, 17, 8, 0))
        self.clock[0] = at(2026, 10, 20, 9, 0)                     # off for three days: one run, not three
        self.assertEqual(sched.tick(), [1])
        self.assertEqual(S.load()["jobs"][0]["next"], at(2026, 10, 21, 8, 0))
        S.add("2026-10-21 07:00 once", now=self.clock[0])
        self.clock[0] = at(2026, 10, 21, 20, 0)                    # 13 h late: skipped and reported
        ran = sched.tick()
        self.assertEqual(ran, [1])                                 # the daily one (12 h late) still runs
        once = S.load()["jobs"][1]
        self.assertEqual(once["last"]["status"], "skipped")
        self.assertTrue(any("skipped" in m[0] for m in self.mails))

    def test_server_down_waits_then_fails_with_a_notice(self):
        sched = self.make(health=False)
        S.add("in 1m check mail", now=NOW)
        self.clock[0] = NOW + 61
        sched.tick()
        self.assertEqual(self.prompts, [])
        self.assertGreaterEqual(self.clock[0] - NOW, 30 * 60)       # waited the 30 minutes
        self.assertEqual(S.load()["jobs"][0]["last"]["status"], "failed")
        self.assertIn("failed", self.mails[0][0])

    def test_server_back_within_the_wait(self):
        calls = []

        def health():
            calls.append(1)
            return len(calls) > 3
        sched = self.make(health=health)
        S.add("in 1m check mail", now=NOW)
        self.clock[0] = NOW + 61
        sched.tick()
        self.assertEqual(self.prompts, [1])
        self.assertEqual(S.load()["jobs"][0]["last"]["status"], "ok")

    def test_dropped_read_only_job_runs_once_more(self):
        sched = self.make(prompt_results=[{"ok": False, "text": "Connection failed", "acted": False, "server_error": True},
                                          {"ok": True, "text": "done", "acted": False, "server_error": False}])
        S.add("in 1m check mail", now=NOW)
        self.clock[0] = NOW + 61
        sched.tick()
        self.assertEqual(self.prompts, [1, 1])
        self.assertEqual(S.load()["jobs"][0]["last"]["status"], "ok")

    def test_dropped_job_that_acted_is_not_run_twice(self):
        sched = self.make(prompt_results=[{"ok": False, "text": "Connection failed", "acted": True, "server_error": True}])
        S.add("in 1m tidy the folder", now=NOW)
        self.clock[0] = NOW + 61
        sched.tick()
        self.assertEqual(self.prompts, [1])
        self.assertEqual(S.load()["jobs"][0]["last"]["status"], "interrupted")
        self.assertIn("interrupted", self.mails[0][0])

    def test_action_job_needs_no_model_and_email_result(self):
        sched = self.make(health=False)
        action = {"tool": "proton__send_mail", "args": {"to": "ana@example.com", "subject": "Hi", "body": "Hello"}}
        S.add("in 1m", action=action, now=NOW)
        S.add("in 1m summarise", email_result=True, now=NOW)
        sched.make = None
        self.clock[0] = NOW + 61
        with mock.patch.object(sched, "health", lambda: True):
            sched.tick()
        self.assertEqual(self.actions, [action])
        self.assertEqual([m[1] for m in self.mails], ["done"])     # the action sends nothing extra


class LateNote(Temp):
    def test_late_action_gets_planned_time_and_note(self):
        import dl_sessiond
        seen = []
        sched = S.Scheduler(lambda j: {}, lambda j: seen.append(j) or {"ok": True, "text": "Sent"}, lambda: True,
                            lambda: None, lambda *a, **k: None, lambda *a: None, clock=lambda: at(2026, 10, 15, 21, 37))
        S.add("21:30", action={"tool": "proton__send_mail", "args": {"to": "a@example.com", "body": "Bok"}},
              now=at(2026, 10, 15, 21, 37), anchor=at(2026, 10, 15, 21, 17))
        sched.tick()
        self.assertAlmostEqual(seen[0]["late_s"], 7 * 60, delta=1)
        self.assertEqual(seen[0]["planned_at"], at(2026, 10, 15, 21, 30))
        with mock.patch("dl_translate.detect", return_value="HR"), \
                mock.patch("dl_translate.translate", return_value=("Planirano za 21:30, poslano u 21:37.", "EN")):
            out = dl_sessiond.add_late_note({"to": "a@example.com", "body": "Bok", "html": "<p>Bok</p>"},
                                            seen[0]["planned_at"], at(2026, 10, 15, 21, 37))
        self.assertTrue(out["body"].startswith("Planirano za 21:30, poslano u 21:37."))
        self.assertTrue(out["html"].startswith("<p><i>Planirano"))
        with mock.patch("dl_translate.detect", return_value=""):
            out = dl_sessiond.add_late_note({"body": "Hello"}, seen[0]["planned_at"], at(2026, 10, 15, 21, 37))
        self.assertIn("Planned for 21:30, sent at 21:37 (7 min later than planned).", out["body"])


class Approval(unittest.TestCase):
    """Adding a job with an action shows the action's every argument on the card (outside YOLO)."""

    def setUp(self):
        dl_mcp.register_builtin("schedule", S.TOOLS, S.call)
        self.tmp = tempfile.TemporaryDirectory()
        cat = Path(self.tmp.name) / "mcp.json"
        cat.write_text(json.dumps({"servers": {"schedule": {
            "builtin": "schedule", "description": "Scheduled jobs", "surfaces": ["code"], "readonly_tools": ["list"],
            "ask": ["add", "remove"], "ask_always_args": {"add": ["action"]}, "triggers": ["remind"]}}}))
        self.reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(cat))
        self.reg.enable("schedule", "test")

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_action_card(self):
        args = {"when": "tomorrow 09:00", "action": {"tool": "proton__send_mail", "args": {
            "to": "boss@example.com", "subject": "Report", "body": "The report is attached."}}}
        summary, reason, always = self.reg.approval("schedule__add", args, ["send it to ana@example.com tomorrow"])
        self.assertTrue(always)
        self.assertIn("action: proton__send_mail", summary)
        self.assertIn("The report is attached.", summary)
        self.assertIn("ADDRESS NOT FROM YOU: boss@example.com", reason)
        self.assertIn("approved now", reason)

    def test_card_shows_an_html_file_email(self):
        ws = Path(self.tmp.name)
        (ws / "mail.html").write_text("<html><head><title>T</title></head><body><p>Vremenska prognoza</p>"
                                      "<table><tr><td>14:00</td><td>17</td></tr></table></body></html>")
        args = {"when": "tomorrow 09:00", "action": {"tool": "proton__send_mail", "args": {
            "to": "a@example.com", "html_file": "mail.html"}}}
        with mock.patch.object(dl_mcp, "call_context", lambda: {"workspace": ws}):
            summary, reason, _ = self.reg.approval("schedule__add", args, ["send to a@example.com"])
        self.assertIn("Vremenska prognoza", summary)
        self.assertIn("14:00 | 17", summary)
        self.assertNotIn("ADDRESS NOT FROM YOU", reason)

    def test_recipient_must_match_a_whole_address(self):
        args = {"when": "in 1h", "action": {"tool": "proton__send_mail", "args": {"to": "a@example.com", "body": "x"}}}
        _, reason, _ = self.reg.approval("schedule__add", args, ["send it to ba@example.com"])
        self.assertIn("ADDRESS NOT FROM YOU: a@example.com", reason)
        for said in ("send it to a@example.com.", "to a@example.com, thanks", "<a@example.com>"):
            _, reason, _ = self.reg.approval("schedule__add", args, [said])
            self.assertNotIn("ADDRESS NOT FROM YOU", reason, said)
        _, reason, _ = self.reg.approval("schedule__add", args, ["to a@example.com.hr"])
        self.assertIn("ADDRESS NOT FROM YOU", reason)

    def test_prompt_job_asks_unless_yolo(self):
        ask = self.reg.approval("schedule__add", {"when": "daily 08:00", "prompt": "summarise mail"})
        self.assertFalse(ask[2])
        self.assertIsNone(self.reg.approval("schedule__list", {}))

    def test_credential_in_a_scheduled_action_is_blocked(self):
        args = {"when": "in 1h", "action": {"tool": "proton__send_mail", "args": {
            "to": "x@example.com", "body": "token ya29.a0AfH6SMBfakefakefakefakefakefakefake"}}}
        self.assertIn("BLOCKED", self.reg.leak(args) or "")


class SlashCommand(Temp):
    def test_schedule_command(self):
        import dl_sessiond
        ws = Path(self.tmp.name)
        out = dl_sessiond.schedule_command("--email daily 08:00 summarise my unread mail", ws)
        self.assertIn("#1 daily 08:00: summarise my unread mail", out)
        self.assertIn("result by email", out)
        self.assertIn("off", dl_sessiond.schedule_command("off 1", ws))
        self.assertIn("next", dl_sessiond.schedule_command("on 1", ws))
        self.assertIn("runs within", dl_sessiond.schedule_command("run 1", ws))
        self.assertIn("Usage", dl_sessiond.schedule_command("someday x", ws))
        self.assertEqual(dl_sessiond.schedule_command("rm 1", ws), "Removed #1.")


if __name__ == "__main__":
    unittest.main(verbosity=1)
