#!/usr/bin/env python3
# scan-secrets: fake-fixtures (the keys below are made up to test the scanner)
"""test_dl_auditing.py - Unit tests for D.L. CLI auditing and guardrail suite."""
import os as _os
_os.environ.setdefault("RAY_MEMORY_DIR", "off")   # the shared memory store stays out of these tests

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


class TestGateReadsTheRealPath(unittest.TestCase):
    """The outside-workspace check compared the text with /tmp/ before resolving it, so /tmp/../home/u/.bashrc
    asked nothing; /bin/rm and \\rm got past the rm pattern; a relative ../../x target was never looked at."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()

    def test_asks(self):
        from tools.dl_auditing import classify_command, classify_write
        for cmd in ("echo x > /tmp/../etc/foo", "/bin/rm -rf ~/x", "\\rm -rf ~/x", "cp a ../../../../../../../etc/out",
                    "cp -t ~/.config/systemd/user a.service", "ln -sf -t /usr/local/bin tool",
                    "cp --target-directory=/etc x", "cp -vt /etc x", "install -Dt /etc x", "ln -sft /usr/bin x",
                    "mv --target-directory /etc x",
                    "cp a ~", "mv -t ~ a", 'cp -t "$HOME" x', "cp a ${HOME}/.bashrc", "install x /etc/y",
                    "install -m 644 x /etc/y", "install -m 0755 -o root x /usr/local/bin/x",
                    "echo hi\ninstall x /etc/y", "  install x /etc/y", "{ install x /etc/y; }",
                    "if true; then install x /etc/y; fi", "/usr/bin/install x /etc/y", "env install x /etc/y",
                    "install --mode 644 x /etc/y",
                    "cp " + "-a " * 17 + "x /etc/y", "install " + "-m 6 " * 20 + "x /etc/y",   # padded past the cap
                    # round 10: options after the operands, several sources, a quoted flag, an option's value
                    "cp x -v /etc/y", "cp a b /etc/", 'cp "-a" x /etc/y', "cp -S .bak x /etc/y",
                    "cp -S\\; -a -a -a x /etc/y", "rsync -av src/ /etc/x", "FOO=1 cp a /etc/b",
                    "rm -fr x", "git push origin main -f",
                    # round 11: redirects, comments, wrappers, find -exec, bash -c, attached option values
                    "cp a /etc/b 2>/dev/null", "cp a /etc/b >/dev/null 2>&1", "cp a /etc/b # note",
                    "if cp a /etc/b; then echo ok; fi", "nice -n 5 cp a /etc/b", "time -p cp a /etc/b",
                    "env -i cp a /etc/b", "timeout 5 cp a /etc/b", "xargs cp -t /etc", "find . -exec cp {} /etc/ \\;",
                    'bash -c "cp a /etc/b"', "install -oroot -groot -m644 x /etc/y", "cp -S.bat a /etc/b",
                    "sudo -u root cp a /etc/b", "cp a ~nosuchuser/x", "cp a b\x00c",
                    # round 12: a heredoc body's quotes, >1.log, line continuations, -lc, timeout 5s
                    "cat > n.txt <<EOF\nit's done\nEOF\ncp a /etc/b\necho 'ok'", "cp a /etc/b >1.log",
                    "rsync -av src/ /etc/x \\\n --delete", "cp -t \\\n /etc a", "cp a /etc/b \\\n 2>/dev/null",
                    "bash -lc 'cp a /etc/b'", "timeout 5s install a /etc/b",
                    # round 13: nothing after a heredoc or a here-string is hidden; a body is read line by line
                    "grep -q x <<< \"$v\"\ncp a /etc/b", "SIZE=$((1<<20))\ncp a /etc/b", "bash <<EOF\ncp a /etc/b\nEOF",
                    "cat <<EOF\r\nhi\r\nEOF\r\ncp a /etc/b", "echo x >|/etc/x", "echo x >& /etc/x",
                    # round 14: an exact CRLF delimiter, the delimiter line, continuations, $(...), $'...', c''p
                    "cat <<EOF\nhi\nEOF\r\nit's\nEOF\ncp a /etc/b\n'x'", "x=`cat <<\"cp a /etc/b\"`\ncp a /etc/b",
                    "bash <<'EOF'\nc\\\np a /etc/b\nEOF", "echo $(cp a /etc/b)", "x=$(cp a /etc/b)",
                    "echo $'\\''\ncp a /etc/b\necho '", "c''p a /etc/b", "c\\\np a /etc/b"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(classify_command(cmd, self.ws))
        self.assertIsNotNone(classify_write(Path("/tmp/../home/someone/.bashrc"), self.ws))

    def test_a_long_command_line_is_checked_fast(self):
        # round 4: the -t branch scanned to the end of the line from every cp/mv/ln/install word (7 s on 50 KB)
        import time as _time
        from tools.dl_auditing import classify_command
        for line in ("echo '" + "install it, cp it, " * 2700 + "'", "cp " * 17000,
                     "install " + "-m " * 40, "install " + "-o -g " * 40, "install " + "--mode " * 40,   # round 7
                     "\n" * 16000, ";" * 16000, "do/" * 5000, "sudo -E;" * 2000,                   # round 8
                     "cp -a;" * 8000, "-{install " * 5000, "`install\n- " * 5000, "find " * 10000,   # round 9
                     "curl " * 10000, "wget " * 10000, "cp " + "-a " * 50000, "install -m 6 " * 12000,
                     "rm -" + "f" * 150000 + "1", "git push " * 15000, "cp\n" * 50000,     # round 10
                     "x" * 600000, "python3 -c '" + "print(\"mv\")\n" * 80000 + "'",      # round 11
                     "cp a b " + "${" * 100000, "$(${" * 50000, "<<EOF\n" * 30000):         # round 12
            t0 = _time.monotonic()
            classify_command(line, self.ws)
            self.assertLess(_time.monotonic() - t0, 0.5)

    def test_the_secret_scan_is_fast_on_long_runs(self):
        # round 9: the URL-password and JWT patterns rescanned a long run from every start
        import time as _time
        from tools.dl_auditing import scan_secrets_in_text
        for text in ("x://" * 15000, "-a" * 30000, "sk-eyJ" * 10000):
            t0 = _time.monotonic()
            scan_secrets_in_text(text, "x.txt")
            self.assertLess(_time.monotonic() - t0, 0.5)

    def test_still_free(self):
        from tools.dl_auditing import classify_command
        for cmd in ("echo x > /tmp/a.txt", "echo > /dev/null", "echo e 2> /dev/stderr", "cat a > out.txt",
                    "cp a sub/b", "ls ..", "cp -r ../lib .", "rsync -a ../src/ ./src/",   # into the workspace
                    "pip install requests numpy", "echo ~", "cp ~/a .", "cp a $HOMEDIR_X/x",
                    "pip install foo ~/wheels/bar.whl", "npm install express ../shared", "uv pip install x /opt/w.whl",
                    "go install ./cmd/a ~/go/src/b", "npm-install a /opt/x",     # they only read those paths
                    "pip install " + "--no-deps " * 17, "rsync -av --exclude x src/ dst/", "rm -v x",
                    "git push origin main", "cp a b; ls -t /etc", "cp a b # to /etc/c", "cp a#b c",
                    "cp a b 2>/tmp/err.log", "echo '$(cp a /etc/b)'"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(classify_command(cmd, self.ws))


class TestWiderSecretPatterns(unittest.TestCase):
    """dl_memory's FALLBACK_SECRETS were used only when dl_auditing failed to import, i.e. never: these formats
    passed the memory-page guard, the MCP leak check and the pre-commit hook."""

    SAMPLES = {   # built at run time, so this file itself holds none of them
        "GitLab Token": "glpat-" + "A1b2C3d4E5f6G7h8I9j0K",
        "Google API Key": "AIza" + "Sy" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijklmnop",
        "Stripe Live Key": "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9",
        "npm Token": "npm_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
        "Connection String with Password": "postgres://" + "app:Pa%24%24w0rd2024" + "@db.example.org/app",
    }

    def test_templates_and_stock_defaults_are_not_secrets(self):
        # round 2: these blocked writing and editing ordinary settings files
        from tools.dl_auditing import scan_secrets_in_text
        jwt_io = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0"
                  "IjoxNTE2MjM5MDIyfQ" + ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        for text in ('f"postgresql://{user}:{password}@{host}/{db}"',
                     "postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/app",
                     "amqp://" + "guest:guest@localhost:5672/", "mongodb://" + "root:example@mongo:27017/",
                     "https://" + "user:pass@host", "postgres://" + "app:password123@db/app", jwt_io):
            with self.subTest(text=text):
                self.assertTrue(scan_secrets_in_text(f"url = {text}\n", "settings.py")[0])

    def test_each_is_caught(self):
        from tools.dl_auditing import scan_secrets_in_text
        for label, value in self.SAMPLES.items():
            with self.subTest(label=label):
                ok, err = scan_secrets_in_text(f"value = {value}\n", "notes.md")
                self.assertFalse(ok)
                self.assertIn(label, err)


if __name__ == "__main__":
    unittest.main()
