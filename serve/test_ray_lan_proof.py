"""/v1/ray/proof: the Ray Android app's check that its LAN address really is this server.  The app sent the API key in
clear to the LAN address on any Wi-Fi and trusted whatever answered there; now it sends a nonce without a key and uses
the LAN route only if the answer is HMAC-SHA256(api_key, "strata-lan-proof:" + nonce).

Run from the repo root: python -m unittest serve.test_ray_lan_proof
"""
import hashlib
import hmac
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
KEY = "lan-proof-test-key"  # scan-secrets: fake-fixtures
NONCE = "0123456789abcdef" * 2


class LanProof(unittest.TestCase):
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

    def proof(self, nonce=NONCE, peer="192.168.1.20", headers=None):
        return server.ray_lan_proof(KEY, nonce, peer, headers or {})

    def test_a_lan_client_gets_the_proof_without_a_key(self):
        status, body = self.proof()
        self.assertEqual(status, 200)
        want = hmac.new(KEY.encode(), b"strata-lan-proof:" + NONCE.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(body["proof"], want)
        self.assertNotIn(KEY, json.dumps(body))
        self.assertEqual(self.proof(peer="::ffff:10.0.0.5")[0], 200)

    def test_not_through_the_tunnel_or_from_outside(self):
        self.assertEqual(self.proof(peer="127.0.0.1")[0], 403)                  # cloudflared
        self.assertEqual(self.proof(peer="8.8.8.8")[0], 403)
        self.assertEqual(self.proof(headers={"CF-Connecting-IP": "1.2.3.4"})[0], 403)
        self.assertEqual(server.ray_lan_proof("", NONCE, "192.168.1.20", {})[0], 404)

    def test_a_rebinding_name_gets_nothing_an_ip_does(self):
        names = {"localhost", "127.0.0.1"}
        self.assertEqual(server.ray_lan_proof(KEY, NONCE, "192.168.1.20", {"Host": "evil.example:8080"}, names)[0], 403)
        self.assertEqual(server.ray_lan_proof(KEY, NONCE, "192.168.1.20", {"Host": "192.168.1.2:8080"}, names)[0], 200)

    def test_several_keys_give_a_proof_each(self):
        for keys in ("k-one,k-two", ["k-one", "k-two"]):
            with self.subTest(keys=keys):
                status, body = server.ray_lan_proof(keys, NONCE, "192.168.1.20", {})
                self.assertEqual(status, 200)
                want = [hmac.new(k.encode(), b"strata-lan-proof:" + NONCE.encode(), hashlib.sha256).hexdigest()
                        for k in ("k-one", "k-two")]
                self.assertEqual(body["proofs"], want)

    def test_a_bad_nonce_is_refused(self):
        for nonce in ("", "short", "Z" * 40):
            with self.subTest(nonce=nonce):
                self.assertEqual(self.proof(nonce=nonce)[0], 400)

    def test_over_http_from_loopback_is_refused_and_needs_no_key(self):
        req = urllib.request.Request(f"{self.base}{server.RAY_LAN_PROOF_PATH}?nonce={NONCE}")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=10)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)             # not 401: the app asks without its key

if __name__ == "__main__":
    unittest.main()
