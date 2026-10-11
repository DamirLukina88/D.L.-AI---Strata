#!/usr/bin/env python3
"""test_dl_auditing.py - Unit tests for D.L. CLI auditing and guardrail suite."""
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.dl_auditing import (
    audit_git_diff,
    get_system_health,
    run_smart_tests,
    scan_secrets_in_text,
    validate_syntax,
)
from tools.dl_cli import dispatch_dl_tool, tool_replace_file_content, tool_write_to_file


class TestDLAuditingSuite(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_syntax_guard_python_valid(self):
        ok, err = validate_syntax("def add(a, b):\n    return a + b\n", "math_util.py")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_syntax_guard_python_invalid(self):
        ok, err = validate_syntax("def add(a, b\n    return a + b\n", "math_util.py")
        self.assertFalse(ok)
        self.assertIn("SyntaxError", err or "")

    def test_syntax_guard_json_valid_and_invalid(self):
        ok_valid, _ = validate_syntax('{"key": "value"}', "config.json")
        self.assertTrue(ok_valid)
        ok_invalid, err = validate_syntax('{"key": "value",}', "config.json")
        self.assertFalse(ok_invalid)
        self.assertIn("JSON SyntaxError", err or "")

    def test_scan_secrets_clean_text(self):
        clean_text = "API_BASE_URL = 'http://127.0.0.1:8080/v1'\n"
        clean, err = scan_secrets_in_text(clean_text, "config.py")
        self.assertTrue(clean)
        self.assertIsNone(err)

    def test_scan_secrets_openai_key(self):
        leaked = "openai_key = 'sk-1234567890abcdef1234567890abcdef12345678'\n"
        clean, err = scan_secrets_in_text(leaked, "config.py")
        self.assertFalse(clean)
        self.assertIn("OpenAI API Key", err or "")

    def test_scan_secrets_github_pat(self):
        leaked = "token = 'ghp_123456789012345678901234567890123456'\n"
        clean, err = scan_secrets_in_text(leaked, "config.py")
        self.assertFalse(clean)
        self.assertIn("GitHub Personal Access Token", err or "")

    def test_write_to_file_guardrails_prevent_broken_write(self):
        bad_code = "def foo():\n    return (\n"
        res = tool_write_to_file({"TargetFile": "bad.py", "CodeContent": bad_code}, self.workspace)
        self.assertIn("SYNTAX ERROR [syntax_guard]", res)
        self.assertFalse((self.workspace / "bad.py").exists())

    def test_write_to_file_guardrails_prevent_secret_write(self):
        secret_code = "token = 'hf_1234567890123456789012345678901234'\n"
        res = tool_write_to_file({"TargetFile": "secret.py", "CodeContent": secret_code}, self.workspace)
        self.assertIn("SECURITY ERROR [scan_secrets]", res)
        self.assertFalse((self.workspace / "secret.py").exists())

    def test_replace_file_content_guardrail_prevents_syntax_break(self):
        (self.workspace / "test.py").write_text("def hello():\n    return 1\n")
        res = tool_replace_file_content(
            {"TargetFile": "test.py", "TargetContent": "return 1", "ReplacementContent": "return ["},
            self.workspace,
        )
        self.assertIn("SYNTAX ERROR [syntax_guard]", res)
        self.assertIn("return 1", (self.workspace / "test.py").read_text())

    def test_system_health_metrics(self):
        stats = get_system_health()
        self.assertIn("ram", stats)
        self.assertIn("swap", stats)
        self.assertIn("vram", stats)
        self.assertGreater(stats["ram"]["total_gb"], 0)

    def test_smart_test_runner_execution(self):
        res = run_smart_tests(workspace=Path("."), target_files=["tools/test_setup_choices.py"])
        self.assertIn("PASSED", res)


if __name__ == "__main__":
    unittest.main()
