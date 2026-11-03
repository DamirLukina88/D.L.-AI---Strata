"""The phone relay (/api/phone/*) needs the API key on every endpoint.  Before, status, pending and result let a client
without a key and without an Origin header through (after _authorized() had already sent its 401), so anyone on the
LAN could fake the phone's heartbeat, take Ray's pending phone tool calls, or post fake results.

Run from the repo root: python -m unittest serve.test_phone_bridge_auth
"""
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve.server as server  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KEY = "phone-test-key"  # scan-secrets: fake-fixtures


class PhoneRelayNeedsTheKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tok = ByteTokenizer()
        cls.svc = Service(MockEngine(tok, "ok", max_context=4096), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.svc.api_key = KEY
        cls.httpd = serve(cls.svc, port=0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        server.PHONE_BRIDGE = server.PhoneBridge()           # a fresh relay for each test

    def call(self, method, path, body=None, key=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, {}

    def test_no_key_no_heartbeat(self):
        for method, path in (("GET", "/api/phone/status"), ("POST", "/api/phone/status"),
                             ("GET", "/api/phone/tool/pending")):
            with self.subTest(path=f"{method} {path}"):
                status, _ = self.call(method, path, {} if method == "POST" else None)
                self.assertEqual(status, 401)
        self.assertFalse(server.PHONE_BRIDGE.get_status()["connected"])

    def test_no_key_cannot_take_a_pending_call_or_answer_it(self):
        bridge = server.PHONE_BRIDGE
        bridge.report_heartbeat()
        with bridge.lock:
            bridge.pending_calls["c1"] = {"id": "c1", "tool": "phone_get_2fa_code", "args": {}, "created": 9e12,
                                          "event": __import__("threading").Event(), "result": None, "dispatched": False}
        self.assertEqual(self.call("GET", "/api/phone/tool/pending")[0], 401)
        self.assertFalse(bridge.pending_calls["c1"]["dispatched"])        # still waiting for the real phone
        self.assertEqual(self.call("POST", "/api/phone/tool/result", {"id": "c1", "result": "fake"})[0], 401)
        self.assertIsNone(bridge.pending_calls["c1"]["result"])

    def test_with_the_key_the_phone_works(self):
        self.assertEqual(self.call("POST", "/api/phone/status", {}, key=KEY)[0], 200)
        status, body = self.call("GET", "/api/phone/status", key=KEY)
        self.assertEqual(status, 200)
        self.assertTrue(body["connected"])
        status, body = self.call("GET", "/api/phone/tool/pending", key=KEY)
        self.assertEqual((status, body.get("pending")), (200, None))


if __name__ == "__main__":
    unittest.main()
