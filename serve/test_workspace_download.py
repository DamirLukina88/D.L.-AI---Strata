"""serve/test_workspace_download.py - D.L. AI workspace downloads: streamed, resumable with Range, any file name, and
by single-use ticket for a plain browser navigation (against the mock engine; no GPU).

    python -m unittest serve.test_workspace_download -v
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve import server  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KEY = "test-key-for-downloads"


class WorkspaceDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ws = Path(self.tmp.name).resolve()
        self.patch = mock.patch.object(server, "WORKSPACE_DIR", ws)
        self.patch.start()
        self.big = ws / "big.zip"
        with open(self.big, "wb") as f:             # 300 MB, sparse: no disk used
            f.truncate(300 << 20)
            f.seek(0)
            f.write(b"HEAD")
            f.seek((300 << 20) - 4)
            f.write(b"TAIL")
        self.small = ws / "šibenik ć.txt"
        self.small.write_bytes(b"0123456789")
        tok = server.ByteTokenizer()
        self.svc = server.Service(server.MockEngine(tok, "</think>\n\nok", max_context=4096), tok,
                                  ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.api_key = KEY
        self.httpd = server.serve(self.svc, port=0)
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def get(self, path, headers=None, method="GET", body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def auth(self, extra=None):
        return {"Authorization": f"Bearer {KEY}", **(extra or {})}

    def test_needs_a_credential(self):
        status, _, _ = self.get("/api/workspace/download?file=big.zip")
        self.assertEqual(status, 401)

    def test_whole_file_streams(self):
        status, h, body = self.get("/api/workspace/download?file=big.zip", self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(int(h["Content-Length"]), 300 << 20)
        self.assertEqual(len(body), 300 << 20)
        self.assertEqual((body[:4], body[-4:]), (b"HEAD", b"TAIL"))
        self.assertEqual(h["Accept-Ranges"], "bytes")

    def test_ranges(self):
        status, h, body = self.get("/api/workspace/download?file=big.zip", self.auth({"Range": "bytes=0-99"}))
        self.assertEqual((status, len(body), body[:4]), (206, 100, b"HEAD"))
        self.assertEqual(h["Content-Range"], f"bytes 0-99/{300 << 20}")
        status, h, body = self.get("/api/workspace/download?file=big.zip", self.auth({"Range": "bytes=-4"}))
        self.assertEqual((status, body), (206, b"TAIL"))
        status, h, _ = self.get("/api/workspace/download?file=big.zip",
                                self.auth({"Range": f"bytes={300 << 20}-"}))
        self.assertEqual((status, h["Content-Range"]), (416, f"bytes */{300 << 20}"))

    def test_non_ascii_name(self):
        status, h, body = self.get("/api/workspace/download?file=" + quote(self.small.name), self.auth())
        self.assertEqual((status, body), (200, b"0123456789"))
        self.assertIn("filename*=UTF-8''" + quote(self.small.name), h["Content-Disposition"])
        h["Content-Disposition"].encode("latin-1")         # the header itself stays sendable

    def test_ticket_is_single_use_and_needs_auth(self):
        status, _, _ = self.get("/api/workspace/download-ticket", {"Content-Type": "application/json"}, "POST",
                                json.dumps({"file": self.small.name}).encode())
        self.assertEqual(status, 401)
        status, _, body = self.get("/api/workspace/download-ticket", self.auth({"Content-Type": "application/json"}),
                                   "POST", json.dumps({"file": self.small.name}).encode())
        self.assertEqual(status, 200)
        url = "/" + json.loads(body)["url"]
        self.assertNotIn(KEY, url)
        status, _, body = self.get(url)                     # no key: the ticket is the credential
        self.assertEqual((status, body), (200, b"0123456789"))
        status, _, _ = self.get(url)
        self.assertEqual(status, 403)

    def test_outside_the_workspace(self):
        status, _, _ = self.get("/api/workspace/download?file=../../etc/passwd", self.auth())
        self.assertEqual(status, 404)
        status, _, _ = self.get("/api/workspace/download-ticket", self.auth({"Content-Type": "application/json"}),
                                "POST", json.dumps({"file": "../../etc/passwd"}).encode())
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
