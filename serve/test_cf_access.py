"""serve/cf_access.py: Cloudflare Access JWTs are accepted only when signed by the team's key, for this application's
audience, from the team's issuer and inside their time window."""
import base64
import hashlib
import json
import random
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serve import cf_access  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

AUD = "a" * 64
TEAM = "example"
ISS = "https://example.cloudflareaccess.com"
NOW = 1_800_000_000


def _prime(bits, rnd):
    while True:
        n = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(
                pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23)):
            return n


def _keypair(seed):
    rnd = random.Random(seed)
    e = 65537
    while True:
        p, q = _prime(512, rnd), _prime(512, rnd)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk(kid, n, e):
    return {"kid": kid, "kty": "RSA", "alg": "RS256",
            "n": _b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": _b64(e.to_bytes(3, "big"))}


def _sign(n, d, kid, claims, alg="RS256"):
    h = _b64(json.dumps({"alg": alg, "kid": kid}).encode())
    p = _b64(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = cf_access._SHA256_PREFIX + hashlib.sha256(f"{h}.{p}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return f"{h}.{p}.{_b64(pow(int.from_bytes(em, 'big'), d, n).to_bytes(k, 'big'))}"


class AccessJwt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n, cls.e, cls.d = _keypair(1)
        cls.n2, cls.e2, cls.d2 = _keypair(2)

    def setUp(self):
        self.fetches = 0

        def fetch(url):
            self.assertEqual(url, ISS + "/cdn-cgi/access/certs")
            self.fetches += 1
            return {"keys": [_jwk("k1", self.n, self.e)]}
        self.v = cf_access.AccessVerifier(TEAM, [AUD], fetch=fetch, now=lambda: NOW)

    def claims(self, **kw):
        c = {"aud": [AUD], "iss": ISS, "email": "me@example.com", "iat": NOW - 10, "nbf": NOW - 10, "exp": NOW + 600}
        c.update(kw)
        return c

    def test_valid_token(self):
        got = self.v.verify(_sign(self.n, self.d, "k1", self.claims()))
        self.assertEqual(got["email"], "me@example.com")

    def test_keys_are_cached(self):
        tok = _sign(self.n, self.d, "k1", self.claims())
        self.v.verify(tok)
        self.v.verify(tok)
        self.assertEqual(self.fetches, 1)

    def test_rejections(self):
        cases = {
            "other key": _sign(self.n2, self.d2, "k1", self.claims()),
            "unknown kid": _sign(self.n2, self.d2, "k2", self.claims()),
            "other audience": _sign(self.n, self.d, "k1", self.claims(aud=["b" * 64])),
            "other issuer": _sign(self.n, self.d, "k1", self.claims(iss="https://evil.cloudflareaccess.com")),
            "expired": _sign(self.n, self.d, "k1", self.claims(exp=NOW - 120)),
            "not yet valid": _sign(self.n, self.d, "k1", self.claims(nbf=NOW + 120)),
            "no exp": _sign(self.n, self.d, "k1", {k: v for k, v in self.claims().items() if k != "exp"}),
            "alg none": _sign(self.n, self.d, "k1", self.claims(), alg="none"),
            "garbage": "not.a.jwt",
            "empty": "",
        }
        for name, tok in cases.items():
            with self.subTest(name):
                self.assertIsNone(self.v.verify(tok))

    def test_tampered_payload(self):
        h, _, s = _sign(self.n, self.d, "k1", self.claims()).split(".")
        p = _b64(json.dumps(self.claims(email="attacker@example.com")).encode())
        self.assertIsNone(self.v.verify(f"{h}.{p}.{s}"))

    def test_string_aud_and_env(self):
        self.assertIsNotNone(self.v.verify(_sign(self.n, self.d, "k1", self.claims(aud=AUD))))
        self.assertIsNone(cf_access.from_env({"STRATA_CF_ACCESS_AUD": AUD}))
        discover = cf_access.from_env({"STRATA_CF_ACCESS_TEAM": TEAM})
        discover._fetch = lambda url: {"keys": [_jwk("k1", self.n, self.e)]}
        discover._now = lambda: NOW
        self.assertIsNone(discover.verify(_sign(self.n, self.d, "k1", self.claims())))   # discovery accepts nothing
        v = cf_access.from_env({"STRATA_CF_ACCESS_TEAM": TEAM, "STRATA_CF_ACCESS_AUD": f"x, {AUD}"})
        self.assertEqual((v.issuer, v.auds), (ISS, ["x", AUD]))

    def test_token_of(self):
        self.assertEqual(cf_access.token_of({"Cf-Access-Jwt-Assertion": "a.b.c"}), "a.b.c")
        self.assertEqual(cf_access.token_of({"Cookie": "x=1; CF_Authorization=d.e.f"}), "d.e.f")
        self.assertEqual(cf_access.token_of({}), "")

    def test_non_dict_header(self):
        for bad_hdr in (b"[]", b"123", b'"str"', b"null", b"true"):
            h = _b64(bad_hdr)
            p = _b64(json.dumps(self.claims()).encode())
            self.assertIsNone(self.v.verify(f"{h}.{p}.sig"))

    def test_failed_fetch_is_throttled(self):
        now = [NOW]
        calls = [0]

        def failing_fetch(url):
            calls[0] += 1
            raise OSError("network down")

        v = cf_access.AccessVerifier(TEAM, [AUD], fetch=failing_fetch, now=lambda: now[0])
        tok = _sign(self.n, self.d, "k1", self.claims())
        self.assertIsNone(v.verify(tok))
        self.assertEqual(calls[0], 1)
        # Immediate retry within REFETCH_MIN must not trigger another network fetch
        now[0] += 10
        self.assertIsNone(v.verify(tok))
        self.assertEqual(calls[0], 1)
        # After REFETCH_MIN passes, retry is permitted
        now[0] += cf_access.REFETCH_MIN + 1
        self.assertIsNone(v.verify(tok))
        self.assertEqual(calls[0], 2)


class AccessCsrfOriginCheck(unittest.TestCase):
    """When authenticated via Cloudflare Access (cookie/header) rather than an explicit API key,
    browser POSTs with an untrusted Origin header must still be rejected by _foreign_page()."""

    @classmethod
    def setUpClass(cls):
        cls.n, cls.e, cls.d = _keypair(3)

    def _start_server(self):
        tok = ByteTokenizer()
        svc = Service(MockEngine(tok, "</think>\n\nok", max_context=4096), tok,
                      ChatTemplate(ROOT / "serve/chat_template.jinja"))
        svc.api_key = "secret-api-key"
        svc.cf_access = cf_access.AccessVerifier(
            TEAM, [AUD],
            fetch=lambda url: {"keys": [_jwk("k1", self.n, self.e)]},
            now=lambda: NOW,
        )
        return serve(svc, port=0)

    def test_untrusted_origin_with_cf_access_is_rejected(self):
        httpd = self._start_server()
        try:
            port = httpd.server_address[1]
            claims = {"aud": [AUD], "iss": ISS, "email": "me@example.com", "iat": NOW - 10, "nbf": NOW - 10, "exp": NOW + 600}
            tok = _sign(self.n, self.d, "k1", claims)
            body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": False}).encode()

            # 1) Untrusted Origin + CF_Authorization cookie -> 403 Forbidden
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                headers={"Origin": "https://evil.example", "Content-Type": "application/json",
                         "Cookie": f"CF_Authorization={tok}"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            ctx.exception.close()
            self.assertEqual(ctx.exception.code, 403)

            # 2) Same-origin + text/plain Content-Type + CF_Authorization cookie -> 415 Unsupported Media Type
            req_plain = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                headers={"Origin": f"http://127.0.0.1:{port}", "Content-Type": "text/plain",
                         "Cookie": f"CF_Authorization={tok}"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx_plain:
                urllib.request.urlopen(req_plain, timeout=5)
            ctx_plain.exception.close()
            self.assertEqual(ctx_plain.exception.code, 415)

            # 3) Same-origin + application/json + CF_Authorization cookie -> 200 OK
            req_ok = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                headers={"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json",
                         "Cookie": f"CF_Authorization={tok}"},
            )
            with urllib.request.urlopen(req_ok, timeout=5) as r:
                self.assertEqual(r.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_explicit_api_key_bypasses_origin_check(self):
        httpd = self._start_server()
        try:
            port = httpd.server_address[1]
            body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": False}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
                headers={"Origin": "https://app.example", "Content-Type": "application/json",
                         "Authorization": "Bearer secret-api-key"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
