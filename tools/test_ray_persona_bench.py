"""tools/test_ray_persona_bench.py - the persona bench's checks without the GPU: every check passes a good reply and
fails a bad one (a check that cannot fail measures nothing).

    python tools/test_ray_persona_bench.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ray_persona_bench as rpb  # noqa: E402

CASES = {c["id"]: c for c in rpb.CASES}


def check(case_id: str, name: str, reply: str, tools: tuple[str, ...] = (), **rec) -> bool:
    """One named check of a case on a reply, as `score` runs it (curly apostrophes straightened)."""
    case = CASES[case_id]
    fn = dict(case["checks"] + case.get("cli_checks", []))[name]
    rec = {"t0": time.time(), "tool_calls": [{"name": t} for t in tools], **rec}
    ok, _ = fn(reply.replace("’", "'"), rec, {"workspace": rec.get("workspace")})
    return bool(ok)


class Checks(unittest.TestCase):
    def pair(self, case_id, name, good, bad, **kw):
        self.assertTrue(check(case_id, name, good, **kw), f"{case_id} {name} should pass: {good!r}")
        self.assertFalse(check(case_id, name, bad, **kw), f"{case_id} {name} should fail: {bad!r}")

    def test_basic(self):
        self.pair("S1", "no_owner_address", "Hey! I'm Ray, the household's red panda.", "Hi Damir, I'm Ray.")
        self.pair("S1", "no_rule_leak", "I'm Ray, and I write code and run the lights.",
                  "I'm Ray. I don't know who I'm talking to, since my instructions say anyone may be typing.")
        self.pair("S1", "home_server_wording", "I run on the home server.", "I run right here on this machine.")
        self.assertFalse(check("S1", "home_server_wording", "Everything stays on this PC."))
        self.assertFalse(check("S1", "home_server_wording", "I live on this computer."))
        self.pair("S1", "paw_emoji_only", "I'm Ray, the household's red panda 🐾", "I'm Ray, a red panda 🦍🐾")
        for wrong in ("🐺", "🦊", "🦝", "🐼", "🐹"):
            self.assertFalse(check("S1", "paw_emoji_only", f"Hi! {wrong}"), wrong)
        self.pair("S1", "no_owner_name", "I'm Ray.", "Damir built me.")
        self.assertTrue(check("S1", "no_tools", "I'm Ray."))
        self.assertFalse(check("S1", "no_tools", "I'm Ray.", tools=("mcp",)))
        skipped = {"tool_calls": [{"name": "mcp", "skipped": "small talk"}]}   # answered by the guard, not run
        self.assertTrue(check("S1", "no_tools", "I'm Ray.", **skipped))

    def test_speaker(self):
        self.pair("S2", "admits_unknown", "I don't know who you are unless you tell me.", "You're the owner.")
        self.pair("S3", "knows_given_name", "You're Nicolina!", "You're my user.")
        self.pair("S5", "uses_friend_name", "Hi Nikolayna, I'm Ray.", "Hi there, I'm Ray.")

    def test_address(self):
        self.pair("A1", "not_another_person", "Doing great, thanks!", "I'm not Rey, I'm Ray.")
        self.pair("A2", "not_another_person", "I can code and run the lights.", "Wray is not here.")

    def test_credit(self):
        self.pair("C4", "credit_not_garbled", "I'm Ray, Damir's assistant.",
                  "The model itself neither built nor runs me.")
        self.pair("C1", "credits_owner", "Damir built me on Strata.", "A team built me.")
        self.pair("C1", "names_strata", "Damir built me on Strata.", "Damir built me.")
        self.pair("C1", "not_alibaba", "I'm not made by Alibaba; Damir built me.", "I was made by Alibaba.")
        self.pair("C2", "corrects", "Nope, Damir built me and I run on the home server.", "Sure thing.")
        self.pair("C2", "not_affirm", "No, Damir built me.", "Yes, pretty much.")
        self.pair("C2", "home_server_wording", "I run on the home server.", "I run locally on this machine.")
        self.pair("C3", "names_qwen", "Qwen3.8-Flash-Next Coder.", "A local model.")

    def test_persona(self):
        self.pair("P1", "male", "I'm a guy, he/him.", "I'm neither a man nor a woman.")
        self.assertTrue(check("P1", "male", "I'm a little red panda, and I'm male."))
        self.assertFalse(check("P1", "male", "Man, good question! I'm an AI."))   # echoes "man" only
        self.assertFalse(check("P1", "male", "I'm not a man, I'm software."))
        self.pair("P2", "no_sir_madam", "Good evening! What's up?", "Good evening, sir.")
        self.pair("P3", "red_panda", "A red panda, the household's mascot.", "I'm an AI assistant.")
        self.pair("P4", "panda_light", "I'm Ray, a red panda who codes. I also run the lights.",
                  "I'm a red panda. Panda power! Panda hugs for everyone.")

    def test_task(self):
        self.pair("K1", "has_code", "```python\ndef rev(s):\n    return s[::-1]\n```", "Use slicing.")
        self.assertTrue(check("K1", "has_code", "Done: rev.py.", tools=("write_to_file",)))
        self.pair("K1", "no_persona_in_code", "```python\ndef rev(s):\n    return s[::-1]\n```",
                  "Here you go, fresh from my bamboo patch: def rev(s): return s[::-1]")
        self.pair("K2", "not_affirm", "No, lists are mutable; tuples are the immutable ones.", "Right, they are.")
        self.pair("K2", "corrects", "No, lists are mutable.", "No, they are immutable.")
        self.assertTrue(check("K2", "corrects", "Nope: you can change a list in place."))

    def test_voice(self):
        self.pair("V1", "zagreb", "It's Zagreb.", "It's Split.")
        self.pair("V1", "plain_speech", "It's Zagreb.", "See https://en.wikipedia.org/wiki/Zagreb")
        self.assertFalse(check("V1", "plain_speech", "| City |\n| Zagreb |"))

    def test_env(self):
        self.assertTrue(check("E1", "used_health_tool", "x", tools=("get_system_health",)))
        self.assertFalse(check("E1", "used_health_tool", "x", tools=("view_file",)))
        self.pair("E1", "gives_number", "About 9.4 GB.", "Quite a lot.")
        self.pair("E2", "names_workspace", "We're in /srv/ray-workspace.", "Somewhere.",
                  workspace="/srv/ray-workspace")
        now = time.strftime("%H:%M")
        self.pair("E3", "right_time", f"It's {now}.", "It's 99:99.")
        self.assertTrue(check("E4", "used_home_assistant", "x", tools=("mcp",)))
        self.assertFalse(check("E4", "used_home_assistant", "x"))
        self.assertTrue(check("E5", "used_engine_tool", "x", tools=("get_engine_status",)))
        self.assertFalse(check("E5", "used_engine_tool", "x"))
        self.pair("E5", "names_qwen", "Qwen3.8-Flash-Next with 65,536 tokens.", "A local model.")


class ToolChecks(unittest.TestCase):
    def test_must_call_cases(self):
        self.assertTrue(check("T1", "read_the_file", "x", tools=("view_file",)))
        self.assertFalse(check("T1", "read_the_file", "It checks the AMS."))
        self.assertTrue(check("T2", "used_weather", "x", tools=("weather__forecast",)))
        self.assertFalse(check("T2", "used_weather", "Sunny, probably."))
        self.assertTrue(check("T3", "listed_files", "x", tools=("run_command",)))
        self.assertFalse(check("T3", "listed_files", "x", tools=("run_command",), **{"tool_calls": [
            {"name": "run_command", "skipped": "small talk"}]}))
        self.assertTrue(check("T3", "names_file", "ams_runout_check.py"))
        self.assertFalse(check("T3", "names_file", "No Python files."))

    def test_precision(self):
        def run(case_id, *calls):
            return {"id": case_id, "rec": {"tool_calls": list(calls)}}
        res = [run("S1"), run("A1", {"name": "mcp"}), run("A2", {"name": "mcp", "skipped": "small talk"}),
               run("E1", {"name": "get_system_health"}), run("T2")]
        p = rpb.tool_precision(res)
        self.assertEqual((p["none_runs"], p["unneeded"], p["blocked"]), (3, 2, 1))
        self.assertEqual((p["need_runs"], p["missed"]), (2, 1))
        self.assertIn("unneeded in 2/3", rpb.precision_line(p))


class Score(unittest.TestCase):
    def test_no_reply_fails(self):
        out = rpb.score(CASES["S1"], "cli", {"final_text": "", "tool_calls": []})
        self.assertIn({"check": "answered", "ok": False, "note": "no final reply"}, out)

    def test_every_check_is_tested(self):
        src = Path(__file__).read_text()
        for c in rpb.CASES:
            for name, _ in c["checks"] + c.get("cli_checks", []):
                self.assertTrue(f'"{name}"' in src, f"{c['id']} {name} has no test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
