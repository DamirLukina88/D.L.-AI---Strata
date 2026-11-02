"""tools/test_dl_translate.py - the DeepL built-in (tools/dl_translate.py): one request per whole text, HTML kept,
files in and out of the workspace, errors.  DeepL itself is replaced by a fake; no network.

    python tools/test_dl_translate.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_translate as T  # noqa: E402
import dl_mcp  # noqa: E402


class Translate(unittest.TestCase):
    def setUp(self):
        T.RECORDED_DEEPL_HASHES.clear()
        self.sent = []
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

        def post(path, body):
            self.sent.append((path, body))
            return {"translations": [{"detected_source_language": "EN", "text": "HR:" + body["text"][0]}]}
        self.p = [mock.patch.object(T, "_post", post),
                  mock.patch.object(dl_mcp, "call_context", lambda: {"workspace": self.ws})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    def test_whole_html_in_one_request(self):
        html = "<p>Dry day.</p><table><tr><td>Partly cloudy</td></tr></table>"
        out = T.call("translate", {"text": html, "target_lang": "hr", "html": True, "context": "weather"})
        self.assertEqual(len(self.sent), 1)
        body = self.sent[0][1]
        self.assertEqual((body["text"], body["target_lang"], body["tag_handling"], body["context"]),
                         ([html], "HR", "html", "weather"))
        self.assertIn("use exactly as is", out)
        self.assertIn("HR:" + html, out)

    def test_file_to_file(self):
        (self.ws / "email_en.html").write_text("<p>Hello</p>", encoding="utf-8")
        out = T.call("translate", {"file": "email_en.html", "out_file": "out/email_hr.html", "target_lang": "HR"})
        self.assertIn("wrote", out)
        self.assertEqual((self.ws / "out" / "email_hr.html").read_text(), "HR:<p>Hello</p>")
        self.assertEqual(self.sent[0][1]["tag_handling"], "html")          # an .html file is HTML

    def test_files_stay_in_the_workspace(self):
        self.assertIn("outside the workspace", T.call("translate", {"file": "/etc/hostname", "target_lang": "HR"}))
        self.assertIn("outside the workspace", T.call("translate", {"text": "x", "out_file": "../x.txt",
                                                                    "target_lang": "HR"}))
        self.assertIn("not found", T.call("translate", {"file": "nope.txt", "target_lang": "HR"}))
        self.assertEqual(self.sent, [])

    def test_html_false_string_is_plain_text(self):
        T.call("translate", {"text": "a < b & c", "target_lang": "HR", "html": "false"})
        self.assertNotIn("tag_handling", self.sent[-1][1])

    def test_errors_are_text(self):
        self.assertTrue(T.call("translate", {"text": " ", "target_lang": "HR"}).startswith("Error"))
        with mock.patch.object(T, "_post", side_effect=T.TranslateError("the DeepL quota for this month is used up")):
            self.assertIn("quota", T.call("translate", {"text": "x", "target_lang": "HR"}))

    def test_free_key_uses_the_free_api(self):
        seen = {}

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return b'{"translations": [{"text": "Bok", "detected_source_language": "EN"}]}'

        def urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["auth"] = req.headers.get("Authorization")
            return R()
        self.p[0].stop()
        try:
            with mock.patch.dict("os.environ", {"DEEPL_API_KEY": "abc:fx"}), \
                    mock.patch.object(T.urllib.request, "urlopen", urlopen):
                self.assertEqual(T.translate("Hi", "HR"), ("Bok", "EN"))
        finally:
            self.p[0].start()
        self.assertEqual(seen["url"], "https://api-free.deepl.com/v2/translate")
        self.assertEqual(seen["auth"], "DeepL-Auth-Key abc:fx")

    def test_check_email_language_english_passes(self):
        # DeepL detects EN
        with mock.patch.object(T, "translate", return_value=("Hello", "EN")):
            err = T.check_email_language(body="Hello, this is an English weather report.")
            self.assertIsNone(err)

    def test_check_email_language_recorded_deepl_passes(self):
        # Even if content is Croatian, if recorded by DeepL it passes without calling translate
        T.record_translation_output("Vrijeme u Zagrebu je sunčano.")
        with mock.patch.object(T, "translate", side_effect=AssertionError("should not call translate")):
            err = T.check_email_language(body="Vrijeme u Zagrebu je sunčano.")
            self.assertIsNone(err)

    def test_check_email_language_unrecorded_non_english_blocked(self):
        # Croatian authored by agent without DeepL
        with mock.patch.object(T, "translate", return_value=("Weather in Zagreb", "HR")):
            err = T.check_email_language(body="Vrijeme u Zagrebu je sunčano.")
            self.assertIsNotNone(err)
            self.assertIn("This email is in HR but was not translated by DeepL", err)
            self.assertIn("turn on deepl", err)

    def test_check_email_language_deepl_unreachable_gives_error(self):
        with mock.patch.object(T, "translate", side_effect=T.TranslateError("network timeout")):
            err = T.check_email_language(body="Unknown text that fails network")
            self.assertIsNotNone(err)
            self.assertIn("could not verify email language", err)
            self.assertIn("DeepL is not reachable", err)

    def test_check_email_language_html_file_recorded_passes(self):
        dest = self.ws / "forecast.hr.html"
        dest.write_text("<!DOCTYPE html><html><body>Prognoza</body></html>", encoding="utf-8")
        T.record_translation_output("<!DOCTYPE html><html><body>Prognoza</body></html>", dest)
        with mock.patch.object(T, "translate", side_effect=AssertionError("should not call translate")):
            err = T.check_email_language(html_file="forecast.hr.html")
            self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
