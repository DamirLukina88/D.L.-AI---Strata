"""tools/test_dl_harness.py - unit tests for Ray's modular harness assembler.

Validates file loading, mtime caching, fallback behavior when files are missing,
skill listing, and guideline composition.

    python tools/test_dl_harness.py
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import dl_harness as harness


class TestDlHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h_dir = Path(self.tmp.name) / "harness"
        self.h_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_files_return_fallbacks(self):
        empty_dir = Path(self.tmp.name) / "nonexistent"
        self.assertEqual(harness.get_guardrails(empty_dir), "")
        self.assertEqual(harness.get_tool_guidance(empty_dir), "")
        self.assertEqual(harness.get_system_prompt_text(empty_dir), "")
        self.assertEqual(harness.list_skills(empty_dir), [])
        self.assertIsNone(harness.load_skill("any", empty_dir))

    def test_load_and_mtime_caching(self):
        g_file = self.h_dir / "guardrails.md"
        g_file.write_text("Rule 1: Ask before guessing\n", encoding="utf-8")

        res1 = harness.get_guardrails(self.h_dir)
        self.assertEqual(res1, "Rule 1: Ask before guessing")

        # Read again - cached
        res2 = harness.get_guardrails(self.h_dir)
        self.assertEqual(res2, "Rule 1: Ask before guessing")

        # Update file and modify mtime
        time.sleep(0.02)
        g_file.write_text("Rule 1: Ask before guessing\nRule 2: Run tests\n", encoding="utf-8")
        res3 = harness.get_guardrails(self.h_dir)
        self.assertEqual(res3, "Rule 1: Ask before guessing\nRule 2: Run tests")

    def test_skill_listing_and_loading(self):
        skills_dir = self.h_dir / "skills"
        s1 = skills_dir / "test_skill"
        s1.mkdir(parents=True, exist_ok=True)
        (s1 / "SKILL.md").write_text("# Test Skill\nDo xyz\n", encoding="utf-8")

        # A folder without SKILL.md should be ignored
        s2 = skills_dir / "ignored_dir"
        s2.mkdir(parents=True, exist_ok=True)

        skills = harness.list_skills(self.h_dir)
        self.assertEqual(skills, ["test_skill"])

        content = harness.load_skill("test_skill", self.h_dir)
        self.assertIsNotNone(content)
        self.assertIn("# Test Skill", content)

        self.assertIsNone(harness.load_skill("nonexistent", self.h_dir))

    def test_build_modular_guidelines(self):
        (self.h_dir / "guardrails.md").write_text("No secrets", encoding="utf-8")
        (self.h_dir / "tool_guidance.md").write_text("Use JSON", encoding="utf-8")
        s = self.h_dir / "skills" / "demo"
        s.mkdir(parents=True, exist_ok=True)
        (s / "SKILL.md").write_text("Demo procedure", encoding="utf-8")

        composed = harness.build_modular_guidelines(self.h_dir)
        self.assertIn("<guardrails>\nNo secrets\n</guardrails>", composed)
        self.assertIn("<tool_guidance>\nUse JSON\n</tool_guidance>", composed)
        self.assertIn("Specialist playbooks available: `demo`", composed)


if __name__ == "__main__":
    unittest.main()
