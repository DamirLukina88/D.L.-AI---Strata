"""tools/test_dl_effort.py - Unit tests for tools/dl_effort.py rules and raise reasons."""
from __future__ import annotations

import unittest
import dl_effort


class TestDlEffortPick(unittest.TestCase):
    def test_plan_mode(self):
        self.assertEqual(dl_effort.pick("hello Ray", mode="plan"), ("high", "plan mode"))
        self.assertEqual(dl_effort.pick("turn off the light", mode="plan"), ("high", "plan mode"))

    def test_code_or_error(self):
        cases = [
            "Check @tools/dl_cli.py",
            "Here is the diff: @patch.diff",
            "Look at this code:\n```python\nprint(1)\n```",
            "Traceback (most recent call last):\n  File 'x.py', line 1",
            "Failed with Error: file not found",
            "Caught an unhandled Exception in worker",
            "The process returned exit code 1",
        ]
        for p in cases:
            self.assertEqual(dl_effort.pick(p), ("high", "code or error"), f"Failed on {p!r}")

    def test_coding_verbs(self):
        verbs = [
            "fix the failing test in tools/x",
            "debug why sessiond hangs",
            "refactor execute_agent_loop in dl_cli",
            "implement the auto effort selector",
            "build the ROCm HIP engine",
            "write a script to benchmark the model",
            "write a function to parse yaml",
            "write a test for dl_effort",
            "optimize prompt ingestion speed",
            "review the recent git diff",
            "migrate to the new config schema",
            "design the session architecture",
            "plan the next release milestones",
            "why does this loop stall?",
            "why doesn't the model stop thinking?",
        ]
        for p in verbs:
            self.assertEqual(dl_effort.pick(p), ("high", "coding task"), f"Failed on {p!r}")

    def test_followup_complaint(self):
        complaints = [
            "that's wrong",
            "thats wrong",
            "didn't work",
            "didnt work",
            "doesn't work",
            "still broken",
            "why?",
        ]
        for p in complaints:
            self.assertEqual(
                dl_effort.pick(p, last_reply="Here is your answer."),
                ("high", "follow-up on a failed answer"),
                f"Failed on {p!r}",
            )
        # Without last_reply, "why?" is a short question, not a follow-up
        self.assertEqual(dl_effort.pick("why?", last_reply=""), ("low", "short question"))
        # Ordinary "why is ..." questions after a reply stay short question / explanation, not complaint
        self.assertEqual(dl_effort.pick("why is the sky blue?", last_reply="Here is your answer."), ("low", "short question"))
        self.assertEqual(dl_effort.pick("explain why ROCm is used", last_reply="Here is your answer."), ("medium", "explanation"))

    def test_small_talk_and_ray_variants(self):
        cases = [
            "hi",
            "hello Ray",
            "hello Rey",
            "hi Rae",
            "hey Wray",
            "Rey",
            "thanks",
            "thank you very much",
            "how are you",
            "introduce yourself",
            "what can you do",
            "good morning Ray",
        ]
        for p in cases:
            self.assertEqual(dl_effort.pick(p), ("none", "small talk"), f"Failed on {p!r}")

    def test_home_commands(self):
        cases = [
            "turn on the light",
            "turn off the living room lights",
            "turn off the ac",
            "switch on bedroom lamp",
            "dim the kitchen lights",
            "set the ac to 22 degrees",
            "open the printer camera",
            "close the smart plug",
        ]
        for p in cases:
            self.assertEqual(dl_effort.pick(p), ("none", "home command"), f"Failed on {p!r}")

    def test_explanations(self):
        cases = [
            "explain what ROCm is",
            "summarize the French Revolution",
            "compare apples and oranges",
            "translate this text to German: good morning",
            "what is quantum entanglement",
        ]
        for p in cases:
            self.assertEqual(dl_effort.pick(p), ("medium", "explanation"), f"Failed on {p!r}")

    def test_short_questions(self):
        cases = [
            "what's 15% of 80?",
            "who was the first president of the United States?",
            "when was the Eiffel Tower built?",
            "where is Mount Everest located?",
            "how tall is Mount Kilimanjaro?",
            "is water wet?",
            "can dogs see in color?",
        ]
        for p in cases:
            self.assertEqual(dl_effort.pick(p), ("low", "short question"), f"Failed on {p!r}")

    def test_voice_word_limits(self):
        # 14 words greeting: fails small talk normally (limit 12), passes with voice=True (limit 18)
        p14 = "hello Ray how are you doing on this very wonderful and sunny day my friend"
        self.assertEqual(dl_effort.pick(p14, voice=False), ("high", "default"))
        self.assertEqual(dl_effort.pick(p14, voice=True), ("none", "small talk"))

        # 22 words home command: fails normally (limit 20), passes with voice=True (limit 26)
        p22 = "please turn on the living room lights and switch the kitchen lamp on because it is getting dark in here tonight"
        self.assertEqual(dl_effort.pick(p22, voice=False), ("high", "default"))
        self.assertEqual(dl_effort.pick(p22, voice=True), ("none", "home command"))

    def test_fallback(self):
        # Long prose or unclassified requests fall back to high default
        fallback = "write a poem about autumn leaves gently falling in the crisp October morning air"
        self.assertEqual(dl_effort.pick(fallback), ("high", "default"))
        # Code words in explanations/questions fall back to high default
        self.assertEqual(dl_effort.pick("explain C++ templates"), ("high", "default"))
        self.assertEqual(dl_effort.pick("what is a python function?"), ("high", "default"))
        # Salutations before commands/questions route to the command/question rule, not small talk
        self.assertEqual(dl_effort.pick("Ray, what's 15% of 80?"), ("low", "short question"))
        self.assertEqual(dl_effort.pick("Hey Ray, explain what ROCm is"), ("medium", "explanation"))
        self.assertEqual(dl_effort.pick("Hi Ray, turn on the living room lights"), ("none", "home command"))


class TestDlEffortSmallTalkGuard(unittest.TestCase):
    """is_small_talk: only greetings and talk about Ray, never a request after a greeting (the guard skips tools)."""

    def test_small_talk(self):
        for t in ("Please introduce yourself.", "hello Rey, how are you", "Wray, what can you do?",
                  "Hello Ring, introduce yourself to my friend.", "Who are you and what you do?", "Good evening.",
                  "Hello Ray introduce yourself to my friend Nikolayna please.", "thanks Ray", "hi"):
            self.assertTrue(dl_effort.is_small_talk(t), t)

    def test_requests_are_not(self):
        for t in ("Hello Ray, please check the printer", "hi Ray, what's the weather tomorrow?", "hello, read the README",
                  "Hey Ray, turn on the lights", "Hi Ray, send me the report", "What time is it?",
                  "Is the 3D printer printing anything right now?", "hello, fix the failing test in app.py"):
            self.assertFalse(dl_effort.is_small_talk(t), t)


class TestDlEffortRaiseReason(unittest.TestCase):
    def test_tool_error(self):
        seen = set()
        r = dl_effort.raise_reason("view_file", {"Path": "missing.py"}, "Error: file not found", seen)
        self.assertEqual(r, "tool error")

    def test_command_exit_codes(self):
        seen = set()
        # Exit 0 -> None
        r0 = dl_effort.raise_reason("run_command", {"CommandLine": "true"}, "ok\n[Command exited with code 0]", seen)
        self.assertIsNone(r0)
        # Exit 2 -> command failed
        r2 = dl_effort.raise_reason("run_command", {"CommandLine": "ls bad"}, "fail\n[Command exited with code 2]", seen)
        self.assertEqual(r2, "command failed")

    def test_repeated_tool_call(self):
        seen = set()
        # First call -> None (added to seen)
        r1 = dl_effort.raise_reason("view_file", {"Path": "a.txt"}, "contents of a", seen)
        self.assertIsNone(r1)
        # Same call repeated -> repeated tool call
        r2 = dl_effort.raise_reason("view_file", {"Path": "a.txt"}, "contents of a", seen)
        self.assertEqual(r2, "repeated tool call")

    def test_clean_result(self):
        seen = set()
        r = dl_effort.raise_reason("view_file", {"Path": "clean.txt"}, "clean output", seen)
        self.assertIsNone(r)


class TestDlEffortBudget(unittest.TestCase):
    def test_default_tiers(self):
        self.assertEqual(dl_effort.budget_for("none"), 0)
        self.assertEqual(dl_effort.budget_for("low"), 1024)
        self.assertEqual(dl_effort.budget_for("medium"), 2048)
        self.assertEqual(dl_effort.budget_for("high"), 4096)

    def test_unknown_level_defaults_to_high(self):
        self.assertEqual(dl_effort.budget_for("unknown"), 4096)
        self.assertEqual(dl_effort.budget_for(""), 4096)

    def test_custom_caps(self):
        custom = {"none": 0, "low": 512, "medium": 1024, "high": 8192}
        self.assertEqual(dl_effort.budget_for("low", custom), 512)
        self.assertEqual(dl_effort.budget_for("high", custom), 8192)
        self.assertEqual(dl_effort.budget_for("other", custom), 4096)


if __name__ == "__main__":
    unittest.main()
