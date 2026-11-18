"""The approval gate and the agent loop with arguments the model gets wrong or aims outside the workspace:
- save_chat wrote any path (an absolute filename, ~) with no card and into the memory store;
- run_command's relative Cwd ran in the process's folder, and ~ was approved as home but ran in "<cwd>/~";
- a list as CommandLine raised a TypeError in approval_reason, which ended the whole request;
- tool_scan_secrets ended on a dangling link.

    cd tools && ../.venv/bin/python -m pytest -q test_dl_boundary_args.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_auditing  # noqa: E402
import dl_boundary  # noqa: E402
import dl_tools_impl  # noqa: E402


class BoundaryArgs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve() / "ws"
        (self.ws / "sub").mkdir(parents=True)

    def test_save_chat_outside_the_workspace_asks(self):
        home = Path.home() / "x-chat"
        self.assertIsNotNone(dl_boundary.approval_reason("save_chat", {"filename": str(home)}, self.ws))
        self.assertIsNotNone(dl_boundary.approval_reason("save_chat", {"filename": "~/x-chat"}, self.ws))
        self.assertIsNone(dl_boundary.approval_reason("save_chat", {"filename": "notes/chat"}, self.ws))
        self.assertIsNone(dl_boundary.approval_reason("save_chat", {}, self.ws))

    def test_save_chat_never_writes_into_the_memory_store(self):
        store = Path(self.tmp.name).resolve() / "store"
        store.mkdir()
        with mock.patch.object(dl_boundary, "memory_store", return_value=store):
            why = dl_boundary.agent_boundary("save_chat", {"filename": str(store / "page")}, self.ws,
                                             {"user_text": "save the chat"})
        self.assertIn("memory store", why or "")

    def test_a_list_command_does_not_raise(self):
        self.assertIsNone(dl_boundary.approval_reason("run_command", {"CommandLine": ["ls", "-la"]}, self.ws))

    def test_cwd_is_the_workspaces(self):
        self.assertEqual(dl_boundary.command_cwd({"Cwd": "sub"}, self.ws), self.ws / "sub")
        self.assertEqual(dl_boundary.command_cwd({"Cwd": "~"}, self.ws), Path.home().resolve())
        out = dl_tools_impl.tool_run_command({"CommandLine": "pwd", "Cwd": "sub"}, self.ws)
        self.assertIn(str(self.ws / "sub"), out)

    def test_scan_secrets_skips_a_dangling_link(self):
        os.symlink(self.ws / "gone", self.ws / ".#lock")
        (self.ws / "a.txt").write_text("hello", encoding="utf-8")
        out = dl_auditing.tool_scan_secrets({}, self.ws)
        self.assertIn("ScanSecrets", out)


class ListenersLeftByACrashedTurn(unittest.TestCase):
    """execute_agent_loop stops what detached commands left listening only when it ends normally; an engine error
    that escaped skipped it, and the next turn's reset of bg_listeners forgot those servers."""

    def test_the_next_turn_stops_them_first(self):
        import dl_cli
        ctx = {"user_text": "hi", "bg_listeners": [("http.server", 8000, 1234, 0.0)]}
        seen = []
        with mock.patch.object(dl_cli, "stop_left_listeners", side_effect=lambda c, e: seen.append(list(c["bg_listeners"]))), \
                mock.patch.object(dl_cli, "chat_turn_in_context", side_effect=RuntimeError("stop here")):
            with self.assertRaises(RuntimeError):
                dl_cli.execute_agent_loop([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
                                          "http://127.0.0.1:9", "", Path(tempfile.gettempdir()),
                                          session_context=ctx)
        self.assertEqual(seen[:1], [[("http.server", 8000, 1234, 0.0)]])


if __name__ == "__main__":
    unittest.main()


class SwitchWorkspaceGate(unittest.TestCase):
    def test_home_or_root_asks_a_project_does_not(self):
        ws = Path(tempfile.gettempdir())
        for target in ("/", "~", str(Path.home()), str(Path.home().parent)):
            with self.subTest(target=target):
                self.assertIsNotNone(dl_boundary.approval_reason("switch_workspace", {"path": target}, ws))
        self.assertIsNone(dl_boundary.approval_reason("switch_workspace", {"path": str(Path.home() / "proj")}, ws))
        for target in ("~/.ssh", "~/.config", "/etc", "/usr/local/bin"):      # round 2: one level down asked nothing
            with self.subTest(target=target):
                self.assertIsNotNone(dl_boundary.approval_reason("switch_workspace", {"path": target}, ws))

    def test_the_export_chat_alias_is_gated_too(self):
        self.assertIsNotNone(dl_boundary.approval_reason("export_chat", {"filename": "~/.config/fish/x.fish"},
                                                         Path(tempfile.gettempdir())))
        self.assertIsNone(dl_boundary.approval_reason("switch_workspace", {"path": "/srv/proj-x"},
                                                      Path(tempfile.gettempdir())))


class SmallChecks(unittest.TestCase):
    def test_a_check_run_through_the_command_alias_counts(self):
        import dl_finish
        rc = dl_finish.RequestChanges(Path(tempfile.gettempdir()))
        rc.before_tool("run_command", {"command": "pytest -q"})
        self.assertEqual(rc.last_check, rc.step)

    def test_smart_tests_pass_only_on_exit_code_zero(self):
        src = (Path(__file__).resolve().parent / "dl_auditing.py").read_text(encoding="utf-8")
        self.assertIn("passed = res.returncode == 0", src)
        self.assertNotIn('"PASSED" in res.stdout or', src)
