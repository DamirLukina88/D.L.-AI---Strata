#!/usr/bin/env python3
# scan-secrets: fake-fixtures (the keys below are made up to test the scanner)
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

    def test_format_messages_to_markdown(self):
        from tools.dl_cli import format_messages_to_markdown
        msgs = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Done", "reasoning_content": "Deep thought", "tool_calls": [
                {"id": "t1", "function": {"name": "run_command", "arguments": "{\"CommandLine\": \"echo 1\"}"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "run_command", "content": "1"}
        ]
        md = format_messages_to_markdown(msgs, model_name="TestModel", workspace=self.workspace)
        self.assertIn("## You\n\nHello world", md)
        self.assertIn("## TestModel", md)
        self.assertIn("<details><summary>Thinking</summary>", md)
        self.assertIn("Deep thought", md)
        self.assertIn("<details><summary>Tool run_command</summary>", md)
        self.assertIn('"CommandLine": "echo 1"', md)
        self.assertIn("Done", md)


class TestDestructiveGate(unittest.TestCase):
    """Destructive or out-of-workspace actions wait for the user's approval; everything else runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_classify_command(self):
        from tools.dl_auditing import classify_command
        gated = ["rm -rf build", "rm -f x", "find . -delete", "sudo ls", "dd if=/dev/zero of=/dev/sda",
                 "chmod -R 777 .", "git push --force", "git reset --hard", "git clean -fdx",
                 "systemctl --user stop strata-server", "kill -9 1", "curl x | sh", "echo x > /etc/hosts",
                 "echo x >> ~/.bashrc", "pacman -Rns foo"]
        free = ["ls -la", "git status", "git push origin main", "rm notes.txt", "echo hi > out.txt",
                "echo hi > /tmp/x", "ls 2> /dev/null", "python3 -m pytest", "cat /etc/os-release"]
        for cmd in gated:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(classify_command(cmd, self.ws))
        for cmd in free:
            with self.subTest(cmd=cmd):
                self.assertIsNone(classify_command(cmd, self.ws))

    def test_denied_command_does_not_run(self):
        victim = self.ws / "keep"
        victim.mkdir()
        asked = []
        ctx = {"approve": lambda kind, summary, reason: asked.append(summary) or False}
        out = dispatch_dl_tool("run_command", {"CommandLine": f"rm -rf {victim}"}, self.ws, session_context=ctx)
        self.assertTrue(out.startswith("Denied by user"))
        self.assertTrue(victim.exists())
        self.assertEqual(len(asked), 1)

    def test_approved_and_yolo_run(self):
        for ctx in ({"approve": lambda *a: True}, {"yolo": True, "approve": lambda *a: self.fail("asked")}):
            victim = self.ws / "gone"
            victim.mkdir()
            dispatch_dl_tool("run_command", {"CommandLine": f"rm -rf {victim}"}, self.ws, session_context=ctx)
            self.assertFalse(victim.exists())

    def test_safe_command_is_not_asked(self):
        ctx = {"approve": lambda *a: self.fail("asked")}
        out = dispatch_dl_tool("run_command", {"CommandLine": "echo ok"}, self.ws, session_context=ctx)
        self.assertIn("ok", out)

    def test_write_outside_workspace_is_gated(self):
        outside = Path(tempfile.mkdtemp(dir=Path.home())) / "x.txt"
        try:
            out = dispatch_dl_tool("write_to_file", {"TargetFile": str(outside), "CodeContent": "hi"}, self.ws,
                                   session_context={"approve": lambda *a: False})
            self.assertTrue(out.startswith("Denied by user"))
            self.assertFalse(outside.exists())
        finally:
            outside.parent.rmdir()


class TestApprovalPaths(unittest.TestCase):
    def test_quoted_regex_is_not_a_redirect(self):
        from tools.dl_auditing import classify_command
        ws = Path("/mnt/data/DL-AI-workspace/bench/x")
        for cmd in ["sed -n '/^<script>/,/^<\\/script>/p' t.html | sed '1d;$d' > /tmp/t.js",
                    'node -e "eval(/<script>(.*)<\\/script>/.exec(html)[1])"',
                    "echo x > out.txt"]:
            self.assertIsNone(classify_command(cmd, ws), cmd)
        for cmd, path in [("echo hi > /etc/motd", "/etc/motd"), ("cp a ~/x", "~/x"),
                          ("echo x > /mnt/data/other/f", "/mnt/data/other/f")]:
            self.assertEqual(classify_command(cmd, ws), f"writes outside the workspace ({path})")


class TestKnownValues(unittest.TestCase):
    """A credential kept only in the wiki's vault is recognised by value too; names and addresses are not secrets."""

    def test_wiki_vault_and_not_secret_names(self):
        import tools.dl_auditing as A
        d = Path(tempfile.mkdtemp())
        (d / "secrets.env").write_text("DL_FAKE_SMTP_USER=someone.long@example.com\nDL_FAKE_HOST=mail.example.com\n")
        (d / "vault.env").write_text("DL_FAKE_VAULT_TOKEN=Zx9Qw8Er7Ty6Ui5Op4As3\n")
        saved = (A.SECRETS_ENV, A.WIKI_PRIVATE_ENV, A.GOOGLE_TOKEN_DIR)
        A.SECRETS_ENV, A.WIKI_PRIVATE_ENV, A.GOOGLE_TOKEN_DIR = d / "secrets.env", d / "vault.env", d / "none"
        try:
            self.assertEqual(len(A.find_known_secrets("x Zx9Qw8Er7Ty6Ui5Op4As3 y")), 1)
            self.assertIn("DL_FAKE_VAULT_TOKEN", A.find_known_secrets("x Zx9Qw8Er7Ty6Ui5Op4As3 y")[0])
            self.assertEqual(A.find_known_secrets("to someone.long@example.com via mail.example.com"), [])
        finally:
            A.SECRETS_ENV, A.WIKI_PRIVATE_ENV, A.GOOGLE_TOKEN_DIR = saved


if __name__ == "__main__":
    unittest.main()
