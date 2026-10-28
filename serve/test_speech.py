import os, stat, tempfile, unittest
from pathlib import Path
from serve import speech


class Speech(unittest.TestCase):
    """serve/speech.py with a fake piper that writes a WAV header and records its arguments."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "voices").mkdir()
        for v in ("en_US-hfc_male-medium", "en_US-other"):
            (d / "voices" / f"{v}.onnx").write_bytes(b"")
            (d / "voices" / f"{v}.onnx.json").write_text("{}")
        self.args = d / "args.txt"
        exe = d / "piper"
        exe.write_text(f"#!/bin/sh\necho \"$@\" > {self.args}\ncat > /dev/null\nprintf 'RIFFfakeWAVE'\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.env = {"STRATA_PIPER": str(exe), "STRATA_PIPER_VOICES": str(d / "voices")}

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_synthesize_default_voice_and_speed(self):
        wav = speech.synthesize("Hello there.", speed=2.0, env=self.env)
        self.assertEqual(wav, b"RIFFfakeWAVE")
        args = self.args.read_text()
        self.assertIn("en_US-hfc_male-medium.onnx", args)
        self.assertIn("--length_scale 0.500", args)

    def test_status(self):
        st = speech.get_tts_status(env=self.env)
        self.assertTrue(st["available"])
        self.assertEqual(st["voices"], ["en_US-hfc_male-medium", "en_US-other"])
        self.assertFalse(speech.get_tts_status(env={**self.env, "STRATA_TTS_VOICE": "missing"})["available"])

    def test_refusals(self):
        for text, voice in (("", None), ("x" * (speech.MAX_CHARS + 1), None), ("hi", "../etc"), ("hi", "nope")):
            with self.assertRaises(speech.SpeechError):
                speech.synthesize(text, voice=voice, env=self.env)


if __name__ == "__main__":
    unittest.main()
