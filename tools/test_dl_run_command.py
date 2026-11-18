"""run_command (tools/dl_tools_impl.py): a child left in the background without a redirect kept the output pipe open,
so the call waited the whole 120 s and said only "timed out"; on a timeout only the shell was killed (the rest of
`a && b` or a pipeline ran on) and what had been printed was thrown away.

    cd tools && ../.venv/bin/python -m pytest -q test_dl_run_command.py
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_tools_impl as impl  # noqa: E402


class RunCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)

    def run_cmd(self, cmd, timeout=5.0):
        with mock.patch.object(impl, "RUN_COMMAND_TIMEOUT_S", timeout):
            return impl.tool_run_command({"CommandLine": cmd}, self.ws)

    def test_a_background_child_does_not_hold_the_call(self):
        t0 = time.monotonic()
        out = self.run_cmd("sleep 3 & echo started", timeout=10)
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertIn("started", out)
        self.assertIn("exited with code 0", out)

    def test_a_timeout_keeps_the_output_and_ends_the_group(self):
        mark = self.ws / "ran-on"
        out = self.run_cmd(f"echo before; sleep 2 && touch {mark}", timeout=0.5)
        self.assertIn("before", out)
        self.assertIn("timed out", out)
        time.sleep(2.5)
        self.assertFalse(mark.exists(), "the rest of `a && b` ran on after the timeout")

    def test_exit_code_and_stderr(self):
        out = self.run_cmd("echo out; echo err >&2; exit 3")
        self.assertIn("out", out)
        self.assertIn("Stderr:\nerr", out)
        self.assertIn("exited with code 3", out)


if __name__ == "__main__":
    unittest.main()


class ReplaceFileContent(unittest.TestCase):
    """replace_file_content read with universal newlines and errors="replace": a CRLF file came back LF, a byte that
    was not UTF-8 became U+FFFD, and an empty TargetContent put the replacement at the top of the file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)

    def edit(self, data: bytes, target, repl):
        p = self.ws / "f.txt"
        p.write_bytes(data)
        out = impl.tool_replace_file_content({"TargetFile": str(p), "TargetContent": target,
                                              "ReplacementContent": repl}, self.ws)
        return out, p.read_bytes()

    def test_crlf_stays_crlf(self):
        out, data = self.edit(b"line1\r\nline2\r\nline3\r\n", "line2\nline3", "LINE2\nLINE3")
        self.assertIn("Successfully", out)
        self.assertEqual(data, b"line1\r\nLINE2\r\nLINE3\r\n")

    def test_lf_stays_lf(self):
        out, data = self.edit(b"a\nb\n", "b", "B")
        self.assertEqual(data, b"a\nB\n")

    def test_not_utf8_is_refused_untouched(self):
        out, data = self.edit(b"caf\xe9\nx\n", "x", "y")
        self.assertIn("not UTF-8", out)
        self.assertEqual(data, b"caf\xe9\nx\n")

    def test_empty_target_is_refused(self):
        out, data = self.edit(b"hello\n", "", "X")
        self.assertIn("empty", out)
        self.assertEqual(data, b"hello\n")


class Context7Call(unittest.TestCase):
    """call_context7_mcp_raw read the server's stdout with no deadline (a hung server held the turn) and left the
    process unreaped."""

    def test_a_silent_server_times_out_and_is_ended(self):
        procs = []
        real = impl.subprocess.Popen

        def popen(*a, **k):
            procs.append(real(*a, **k))
            return procs[-1]
        with mock.patch.object(impl, "CONTEXT7_CMD", [sys.executable, "-c", "import time; time.sleep(30)"]), \
                mock.patch.object(impl, "CONTEXT7_TIMEOUT_S", 0.5), mock.patch.object(impl.subprocess, "Popen", popen):
            t0 = time.monotonic()
            out = impl.call_context7_mcp_raw("resolve-library-id", {"libraryName": "x"})
        self.assertLess(time.monotonic() - t0, 5)
        self.assertIn("no answer", out)
        self.assertIsNotNone(procs[0].poll())

    def test_an_answer_is_read(self):
        reply = '{"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "docs here"}]}}'
        script = f"import sys\nfor i, line in enumerate(sys.stdin):\n    if i == 1:\n        print({reply!r}, flush=True)\n"
        with mock.patch.object(impl, "CONTEXT7_CMD", [sys.executable, "-c", script]):
            self.assertEqual(impl.call_context7_mcp_raw("get-library-docs", {}), "docs here")


class ViewFileImage(unittest.TestCase):
    """view_file said "shown to you as an image" for a picture outside the workspace, which is never attached."""

    def test_inside_is_shown_outside_says_so(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ws, other = Path(a), Path(b)
            (ws / "in.png").write_bytes(b"\x89PNG")
            (other / "out.png").write_bytes(b"\x89PNG")
            with mock.patch.dict(impl.os.environ, {"STRATA_WORKSPACE_DIR": ""}):
                self.assertIn("shown to you as an image", impl.tool_view_file({"AbsolutePath": str(ws / "in.png")}, ws))
                out = impl.tool_view_file({"AbsolutePath": str(other / "out.png")}, ws)
        self.assertIn("not shown", out)
        self.assertNotIn("[[image:", out)
