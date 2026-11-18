"""With no api_key, anyone who reaches the server may use the model (upstream's choice, with a startup warning), but
Ray's own routes run a shell (/api/code/session), read and write the workspace and reach the phone: from another
computer they need a key.  The test reaches the server through this PC's own LAN address, which is not loopback.

Run from the repo root: python -m unittest serve.test_ray_routes_no_key
"""
import json
import socket
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))              # TEST-NET: nothing is sent, the kernel only picks a route
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


@unittest.skipIf(lan_address() is None, "no non-loopback address on this machine")
class RayRoutesNeedAKeyFromElsewhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tok = ByteTokenizer()
        cls.svc = Service(MockEngine(tok, "ok", max_context=4096), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        cls.httpd = serve(cls.svc, host="0.0.0.0", port=0)
        cls.port = cls.httpd.server_address[1]
        cls.svc.allowed_hosts = ["*"]
        cls.svc.host_names = cls.svc.host_names | {lan_address()}

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, host, path):
        try:
            with urllib.request.urlopen(f"http://{host}:{self.port}{path}", timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            with e:
                return e.code

    def test_from_the_lan_ray_routes_are_refused_the_model_is_not(self):
        lan = lan_address()
        for path in ("/api/workspace/files", "/api/phone/status", "/v1/ray/history?session=dl-ai-code"):
            with self.subTest(path=path):
                self.assertEqual(self.get(lan, path), 401)
        self.assertEqual(self.get(lan, "/v1/models"), 200)

    def test_from_this_pc_they_work_as_before(self):
        self.assertNotEqual(self.get("127.0.0.1", "/api/phone/status"), 401)
        self.assertNotEqual(self.get("127.0.0.1", "/api/workspace/files"), 401)


if __name__ == "__main__":
    unittest.main()
