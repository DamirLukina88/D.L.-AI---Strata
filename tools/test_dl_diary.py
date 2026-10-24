"""tools/test_dl_diary.py - unit tests and trajectory replay simulations for Ray's Struggle Diary.

Validates all 5 friction categories (FAILURE, INEFFICIENCY, CONFUSION, UNASKED_CLARIFICATION, INTERVENTION),
trajectory replays, atomic ledger writing, and recent incident formatting without requiring a model or GPU.

    python tools/test_dl_diary.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import dl_diary as diary


class TestDlDiary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.diary_dir = Path(self.tmp.name) / "diary"
        self.diary_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_session_records_nothing(self):
        tracker = diary.FrictionTracker(
            prompt="summarize this file",
            workspace="/tmp/ws",
            session_id="test-clean"
        )
        tracker.record_tool_dispatch("view_file", {"Path": "a.txt"}, "file contents here")
        rep = tracker.finalize(total_turns=2, total_tokens=500)
        self.assertIsNone(rep)

    def test_failure_classification_tool_error(self):
        tracker = diary.FrictionTracker(
            prompt="run a script",
            workspace="/tmp/ws",
            session_id="test-fail"
        )
        tracker.record_tool_dispatch(
            "run_command",
            {"command": "python test.py"},
            "Error: Traceback (most recent call last):\n[Command exited with code 1]"
        )
        rep = tracker.finalize(total_turns=2, total_tokens=600)
        self.assertIsNotNone(rep)
        self.assertIn("FAILURE", rep.categories)
        self.assertEqual(rep.tool_errors_count, 1)
        self.assertTrue(any("Command failed" in s for s in rep.symptoms))

    def test_failure_classification_bad_args(self):
        tracker = diary.FrictionTracker(
            prompt="write file",
            workspace="/tmp/ws",
            session_id="test-bad-args"
        )
        tracker.record_bad_arguments("write_to_file", "{bad:json", "Expecting property name enclosed in double quotes")
        rep = tracker.finalize(total_turns=1, total_tokens=200)
        self.assertIsNotNone(rep)
        self.assertIn("FAILURE", rep.categories)
        self.assertEqual(rep.tool_errors_count, 1)
        self.assertTrue(any("Malformed JSON arguments" in s for s in rep.symptoms))

    def test_inefficiency_repeated_call_and_high_turns(self):
        tracker = diary.FrictionTracker(
            prompt="find all references",
            workspace="/tmp/ws",
            session_id="test-inefficient"
        )
        # Repeat identical tool call
        tracker.record_tool_dispatch("run_command", {"command": "ls -l"}, "file1 file2")
        tracker.record_tool_dispatch("run_command", {"command": "ls -l"}, "file1 file2")
        rep = tracker.finalize(total_turns=12, total_tokens=16000)
        self.assertIsNotNone(rep)
        self.assertIn("INEFFICIENCY", rep.categories)
        self.assertTrue(any("Repeated identical tool call" in s for s in rep.symptoms))
        self.assertTrue(any("High turn count" in s for s in rep.symptoms))
        self.assertTrue(any("High token consumption" in s for s in rep.symptoms))

    def test_confusion_shrink_alarm(self):
        tracker = diary.FrictionTracker(
            prompt="refactor engine",
            workspace="/tmp/ws",
            session_id="test-confusion"
        )
        tracker.record_shrink_alarm("replace_file_content", "engine.cpp halved (200 -> 80 lines)")
        rep = tracker.finalize(total_turns=3, total_tokens=1000)
        self.assertIsNotNone(rep)
        self.assertIn("CONFUSION", rep.categories)
        self.assertTrue(any("Shrink alarm triggered" in s for s in rep.symptoms))

    def test_unasked_clarification_user_correction_prompt(self):
        tracker = diary.FrictionTracker(
            prompt="that's wrong, you edited the wrong file",
            workspace="/tmp/ws",
            session_id="test-clarify"
        )
        rep = tracker.finalize(total_turns=1, total_tokens=300)
        self.assertIsNotNone(rep)
        self.assertIn("UNASKED_CLARIFICATION", rep.categories)
        self.assertTrue(any("correction phrase" in s for s in rep.symptoms))
        self.assertIsNotNone(rep.clarification_gap)

    def test_unasked_clarification_speculative_file_path(self):
        tracker = diary.FrictionTracker(
            prompt="update config",
            workspace="/tmp/ws",
            session_id="test-speculate"
        )
        tracker.record_tool_dispatch(
            "view_file",
            {"Path": "configs/secret_settings.json"},
            "Error: No such file or directory: 'configs/secret_settings.json'"
        )
        rep = tracker.finalize(total_turns=2, total_tokens=400)
        self.assertIsNotNone(rep)
        self.assertIn("UNASKED_CLARIFICATION", rep.categories)
        self.assertIn("FAILURE", rep.categories)
        self.assertTrue(any("guessed non-existent target" in s for s in rep.symptoms))

    def test_intervention_checks(self):
        tracker = diary.FrictionTracker(
            prompt="build webpage",
            workspace="/tmp/ws",
            session_id="test-intervention"
        )
        tracker.record_check_intervention("Browser Check", "index.html has 2 unhandled console error(s)")
        tracker.record_check_intervention("Reviewer", "Missing error handling in save_user()")
        tracker.record_stall_limit("PLAN.md", open_steps=3)
        rep = tracker.finalize(total_turns=4, total_tokens=2500)
        self.assertIsNotNone(rep)
        self.assertIn("INTERVENTION", rep.categories)
        self.assertTrue(any("Sent back by Browser Check" in s for s in rep.symptoms))
        self.assertTrue(any("Sent back by Reviewer" in s for s in rep.symptoms))
        self.assertTrue(any("Plan stall limit reached" in s for s in rep.symptoms))

    def test_atomic_file_writing_and_formatting(self):
        tracker = diary.FrictionTracker(
            prompt="fix failing unit test",
            workspace="/tmp/ws",
            session_id="test-write"
        )
        tracker.record_tool_dispatch("run_command", {"command": "pytest"}, "Error: [Command exited with code 1]")
        rep = tracker.finalize(total_turns=3, total_tokens=1500)
        self.assertIsNotNone(rep)

        diary.log_incident(rep, diary_dir=self.diary_dir)

        # Check JSONL
        jsonl = self.diary_dir / "incidents.jsonl"
        self.assertTrue(jsonl.is_file())
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["session_id"], "test-write")
        self.assertIn("FAILURE", data["categories"])

        # Check Markdown
        mds = list(self.diary_dir.glob("*.md"))
        self.assertEqual(len(mds), 1)
        md_content = mds[0].read_text(encoding="utf-8")
        self.assertIn("# Ray Struggle Diary", md_content)
        self.assertIn("`[FAILURE]`", md_content)
        self.assertIn("fix failing unit test", md_content)

        # Check formatting utility
        formatted = diary.format_recent_markdown(n=5, diary_dir=self.diary_dir)
        self.assertIn("Recent Struggle Diary Incidents", formatted)
        self.assertIn("fix failing unit test", formatted)


    def test_trajectory_replay_multi_turn_with_unasked_clarification(self):
        """Simulates a multi-turn trajectory where Ray makes a speculative assumption,
        fails, user corrects him, and Ray recovers."""
        # Turn 1: User prompt is vague
        t1 = diary.FrictionTracker(
            prompt="check the status of the device",
            workspace="/tmp/ws",
            session_id="sim-session",
            transcript_path="/tmp/transcripts/sim.jsonl"
        )
        # Ray guesses an entity name instead of querying
        t1.record_tool_dispatch(
            "view_file",
            {"Path": "/etc/device_config.yaml"},
            "Error: No such file or directory: '/etc/device_config.yaml'"
        )
        rep1 = t1.finalize(total_turns=2, total_tokens=800)
        self.assertIsNotNone(rep1)
        self.assertIn("FAILURE", rep1.categories)
        self.assertIn("UNASKED_CLARIFICATION", rep1.categories)
        diary.log_incident(rep1, diary_dir=self.diary_dir)

        # Turn 2: User corrects Ray
        t2 = diary.FrictionTracker(
            prompt="that's wrong, it's a Home Assistant light not a local file",
            workspace="/tmp/ws",
            session_id="sim-session",
            transcript_path="/tmp/transcripts/sim.jsonl"
        )
        t2.record_tool_dispatch(
            "run_command",
            {"command": "ha status"},
            "light.living_room is on\n[Command exited with code 0]"
        )
        rep2 = t2.finalize(total_turns=1, total_tokens=400)
        self.assertIsNotNone(rep2)
        self.assertIn("UNASKED_CLARIFICATION", rep2.categories)
        diary.log_incident(rep2, diary_dir=self.diary_dir)

        # Verify 2 incidents are recorded in index
        incidents = diary.read_recent_incidents(n=10, diary_dir=self.diary_dir)
        self.assertEqual(len(incidents), 2)
        self.assertEqual(incidents[0]["session_id"], "sim-session")
        self.assertEqual(incidents[1]["session_id"], "sim-session")
        self.assertEqual(incidents[0]["transcript_path"], "/tmp/transcripts/sim.jsonl")


if __name__ == "__main__":
    unittest.main()
