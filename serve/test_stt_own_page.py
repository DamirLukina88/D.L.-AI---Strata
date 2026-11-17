"""The web app's speech-to-text upload (app-03-stt.js) is a multipart FormData POST to /v1/audio/transcriptions.
A browser sends Origin on it, and without an API key (an open server, or behind Cloudflare Access where the web app
sends none) /v1's foreign-page check wanted application/json, so every transcription was refused with 415.

Run from the repo root: python -m unittest serve.test_stt_own_page
"""
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = "strata-test-boundary"
BODY = (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.webm\"\r\n"
        f"Content-Type: audio/webm\r\n\r\nnot audio\r\n--{BOUNDARY}--\r\n").encode()


class SpeechUploadFromTheOwnPage(unittest.TestCase):
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

    def post(self, origin):
        req = urllib.request.Request(f"http://{self.host}/v1/audio/transcriptions", method="POST", data=BODY,
                                     headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
                                              "Origin": origin})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status
        except urllib.error.HTTPError as e:
            with e:
                return e.code

    def test_the_own_page_gets_past_the_content_type_check(self):
        self.assertNotIn(self.post(f"http://{self.host}"), (403, 415))   # whatever the transcriber says, not refused

    def test_another_page_is_still_refused(self):
        self.assertIn(self.post("https://evil.example"), (403, 415))
        self.assertEqual(self.post(f"http://localhost:{self.httpd.server_address[1] + 1}"), 415)


if __name__ == "__main__":
    unittest.main()
