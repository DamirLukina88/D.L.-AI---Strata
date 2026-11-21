"""Per-model settings profiles (dl_profile.py): which file is read, the order of the layers, and the per-request sync."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import dl_cli
import dl_context
import dl_profile


def _write(folder, name, settings, raw=None):
    p = folder / f"{name}.json"
    p.write_text(raw if raw is not None else json.dumps({"note": "test", "settings": settings}), encoding="utf-8")
    return p


def _folder():
    return dl_profile.profiles_dir()


def _health_server(model):
    state = {"model": model}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok", "model": state["model"], "max_context": 32768}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


class ProfileTests(unittest.TestCase):
    """Runs under pytest and under `python -m unittest` (tools/run_tests.sh), which does not load conftest.py: each
    test gets its own empty profile folder and no profile in use."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        folder = Path(self._tmp.name)
        self._patches = [mock.patch.object(dl_profile, "profiles_dir", lambda: folder)]
        twin = __import__("sys").modules.get("tools.dl_profile")
        if twin is not None and twin is not dl_profile:
            self._patches.append(mock.patch.object(twin, "profiles_dir", lambda: folder))
        for pt in self._patches:
            pt.start()
        dl_profile.reset()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        for pt in self._patches:
            pt.stop()
        dl_profile.reset()
        self._tmp.cleanup()


    def test_no_profile_gives_code_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DL_NUDGE_AT", None)
            assert dl_profile.env("DL_NUDGE_AT", "12") == "12"
            assert dl_profile.tuned("DL_NUDGE_AT", 12) == 12
            assert dl_profile.switch("DL_LOOP_GUARD") is True


    def test_model_profile_over_default_profile(self):
        f = _folder()
        _write(f, "_default", {"DL_NUDGE_AT": 10, "DL_ADVISOR": True})
        _write(f, "qwen-a", {"DL_NUDGE_AT": 14})
        os.environ.pop("DL_NUDGE_AT", None)
        os.environ.pop("DL_ADVISOR", None)
        assert dl_profile.use_model("qwen-a") is True
        assert dl_profile.tuned("DL_NUDGE_AT", 12) == 14
        assert dl_profile.env("DL_ADVISOR") == "1"
        dl_profile.use_model("other-model")                     # no file of its own: only the base layer
        assert dl_profile.tuned("DL_NUDGE_AT", 12) == 10


    def test_environment_wins_over_profile(self):
        _write(_folder(), "m", {"DL_LOOP_GUARD": False, "DL_PATCH_AT": 30})
        dl_profile.use_model("m")
        with mock.patch.dict(os.environ, {"DL_LOOP_GUARD": "1", "DL_PATCH_AT": "18"}):
            assert dl_profile.switch("DL_LOOP_GUARD") is True
            assert dl_profile.tuned("DL_PATCH_AT", 18) == 18
        os.environ.pop("DL_LOOP_GUARD", None)
        assert dl_profile.switch("DL_LOOP_GUARD") is False


    def test_patched_constant_wins_without_profile(self):
        os.environ.pop("DL_NUDGE_AT", None)
        assert dl_profile.tuned("DL_NUDGE_AT", 3) == 3


    def test_file_name_and_bad_files(self):
        assert dl_profile.file_for("a/b c:d").name == "a_b_c_d.json"
        f = _folder()
        _write(f, "broken", None, raw="{not json")
        dl_profile.use_model("broken")
        assert dl_profile.active()["settings"] == {}
        assert "broken.json" in dl_profile.active()["error"]
        _write(f, "odd", {"NOT_DL": 1, "DL_X": None, "DL_Y": 2.5})
        dl_profile.use_model("odd")
        assert dl_profile.active()["settings"] == {"DL_Y": "2.5"}
        assert dl_profile.tuned("DL_Y", 7) == 7                  # an int setting the profile cannot give keeps the default
        assert dl_profile.tuned("DL_Y", 7.0, float) == 2.5


    def test_edited_file_is_read_again(self):
        f = _folder()
        p = _write(f, "m2", {"DL_MAX_TURNS": 40})
        dl_profile.use_model("m2")
        assert dl_profile.tuned("DL_MAX_TURNS", 40) == 40
        p.write_text(json.dumps({"settings": {"DL_MAX_TURNS": 25}}), encoding="utf-8")
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert dl_profile.use_model("m2") is True
        assert dl_profile.tuned("DL_MAX_TURNS", 40) == 25


    def test_router_mode_reads_profile(self):
        import dl_router
        os.environ.pop("DL_EFFORT_ROUTER_MODE", None)
        os.environ.pop("DL_ROUTER_MODE", None)
        os.environ.pop("DL_SEMANTIC_ROUTER", None)
        _write(_folder(), "r", {"DL_EFFORT_ROUTER_MODE": "hybrid"})
        dl_profile.use_model("r")
        assert dl_router.router_mode(subsystem="effort") == "hybrid"
        dl_profile.use_model("nothing")
        assert dl_router.router_mode(subsystem="effort") == "rules"


    def test_sync_follows_the_served_model_and_forgets_context_size(self):
        f = _folder()
        _write(f, "qwen-x", {"DL_NUDGE_AT": 9})
        _write(f, "hy4-x", {"DL_NUDGE_AT": 20})
        srv, state = _health_server("qwen-x")
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        notes = []
        try:
            os.environ.pop("DL_NUDGE_AT", None)
            dl_context.sync_model_profile(url, "", notes.append)
            assert dl_profile.active()["model"] == "qwen-x" and dl_profile.tuned("DL_NUDGE_AT", 12) == 9
            dl_context._ctx_cache[url] = 65536
            state["model"] = "hy4-x"
            dl_context.sync_model_profile(url, "", notes.append)
            assert dl_profile.tuned("DL_NUDGE_AT", 12) == 20
            assert url not in dl_context._ctx_cache
            assert len(notes) == 1 and "hy4-x" in notes[-1]["text"]     # the first load posts nothing; the switch does
            dl_context.sync_model_profile(url, "", notes.append)   # nothing changed: no new notice
            assert len(notes) == 1
        finally:
            srv.shutdown()
            dl_context._ctx_cache.pop(url, None)


    def test_sync_keeps_profile_when_server_is_down(self):
        _write(_folder(), "kept", {"DL_PATCH_AT": 5})
        dl_profile.use_model("kept")
        dl_context.sync_model_profile("http://127.0.0.1:9", "", None)
        assert dl_profile.active()["model"] == "kept"


    def test_environment_general_name_beats_profile_specific_name(self):
        import dl_router
        _write(_folder(), "g", {"DL_MCP_ROUTER_MODE": "rules", "DL_EFFORT_ROUTER_MODE": "hybrid"})
        dl_profile.use_model("g")
        with mock.patch.dict(os.environ, {"DL_ROUTER_MODE": "model2vec"}, clear=True):
            self.assertEqual(dl_router.router_mode(subsystem="mcp"), "model2vec")
            self.assertEqual(dl_router.router_mode(subsystem="effort"), "model2vec")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(dl_router.router_mode(subsystem="mcp"), "rules")
            self.assertEqual(dl_router.router_mode(subsystem="effort"), "hybrid")

    def test_status_line_does_not_switch_the_profile(self):
        f = _folder()
        _write(f, "in-use", {"DL_NUDGE_AT": 9})
        _write(f, "served", {"DL_NUDGE_AT": 20, "DL_PATCH_AT": 30})
        dl_profile.use_model("in-use")
        line = dl_profile.describe("served")
        self.assertIn("served (served.json, 2 settings)", line)
        self.assertEqual(dl_profile.active()["model"], "in-use")
        self.assertTrue(dl_profile.use_model("served"))      # so the next request's sync still sees the swap

    def test_whole_number_written_as_float(self):
        _write(_folder(), "f", {"DL_NUDGE_AT": 14.0, "DL_PATCH_AT": "20.0", "DL_MAX_TURNS": 2.5})
        dl_profile.use_model("f")
        self.assertEqual(dl_profile.tuned("DL_NUDGE_AT", 12), 14)
        self.assertEqual(dl_profile.tuned("DL_PATCH_AT", 18), 20)
        self.assertEqual(dl_profile.tuned("DL_MAX_TURNS", 40), 40)

    def test_flat_and_package_copies_share_one_state(self):
        assert dl_cli.dl_profile._STATE is dl_profile._STATE
        assert dl_context.dl_profile._STATE is dl_profile._STATE


if __name__ == "__main__":
    unittest.main()
