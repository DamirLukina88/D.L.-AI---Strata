"""Ported from upstream 38ad0bcbd and 3e1fcaaf6: every child the server starts gets GGML_NO_BACKTRACE=1 (ggml's abort path
otherwise forks gdb into the dying engine or picture reader), unless STRATA_BACKTRACE asks for the backtrace; and the HTTP
server binds without asking getfqdn for a host name."""

from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serve import images  # noqa: E402
from serve.childenv import quiet_crash_env  # noqa: E402
from serve.server import Server, child_env, vision_env  # noqa: E402


class NoBacktrace(unittest.TestCase):
    def test_helper(self):
        self.assertEqual(quiet_crash_env({})["GGML_NO_BACKTRACE"], "1")
        self.assertEqual(quiet_crash_env({"GGML_NO_BACKTRACE": "0"})["GGML_NO_BACKTRACE"], "0")   # set by hand: kept
        with mock.patch.dict(os.environ, {"STRATA_BACKTRACE": ""}, clear=False):
            self.assertNotIn("GGML_NO_BACKTRACE", quiet_crash_env({"STRATA_BACKTRACE": "1"}))
            self.assertIn("GGML_NO_BACKTRACE", quiet_crash_env({"STRATA_BACKTRACE": "off"}))

    def test_engine_reader_and_image_environments(self):
        env = {k: v for k, v in os.environ.items() if k not in ("GGML_NO_BACKTRACE", "STRATA_BACKTRACE")}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = {"backend": "hip"}
            engine = child_env(cfg)
            self.assertEqual(engine["GGML_NO_BACKTRACE"], "1")
            self.assertEqual(vision_env(cfg, dict(engine))["GGML_NO_BACKTRACE"], "1")
            self.assertEqual(images.image_env({})["GGML_NO_BACKTRACE"], "1")


class BindWithoutLookup(unittest.TestCase):
    def test_no_getfqdn(self):
        from http.server import BaseHTTPRequestHandler
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn called")):
            srv = Server(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            self.assertEqual(srv.server_name, "127.0.0.1")
            self.assertEqual(srv.server_port, srv.server_address[1])
        finally:
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
