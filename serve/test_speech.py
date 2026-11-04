import json, os, shutil, stat, subprocess, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path
from unittest import mock
from serve import speech
from serve.frontend import ChatTemplate
from serve.server import ByteTokenizer, MockEngine, Service, serve

ROOT = Path(__file__).resolve().parents[1]
RAW_SECOND = 22050 * 2               # a second of the fake piper's 16-bit mono samples
# as piper: a WAV header for the file form, or with --output_raw headerless samples, one second per line of the text
FAKE_PIPER = """#!/bin/sh
echo "$@" > {args}
case " $* " in
  *" --output_raw "*) while IFS= read -r line || [ -n "$line" ]; do head -c 44100 /dev/zero; done ;;
  *) cat > /dev/null; printf 'RIFFfakeWAVE' ;;
esac
"""
FAKE_FFMPEG = """#!/bin/sh
echo "$@" > {args}
cat > {got}
printf 'OggSfake'
"""


def script(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def has_opus():
    exe = shutil.which("ffmpeg")
    return bool(exe) and b"libopus" in subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True).stdout


class Fakes(unittest.TestCase):
    """A fake piper that writes a WAV header and records its arguments, and a fake ffmpeg."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = d = Path(self.tmp.name)
        (d / "voices").mkdir()
        (d / "bin").mkdir()
        for v in ("en_US-hfc_male-medium", "en_US-other"):
            (d / "voices" / f"{v}.onnx").write_bytes(b"")
            (d / "voices" / f"{v}.onnx.json").write_text('{"audio": {"sample_rate": 22050}}')
        self.args = d / "args.txt"
        self.ff_args = d / "ffmpeg-args.txt"
        self.ff_got = d / "ffmpeg-got.raw"
        exe = script(d / "piper", FAKE_PIPER.format(args=self.args))
        script(d / "bin" / "ffmpeg", FAKE_FFMPEG.format(args=self.ff_args, got=self.ff_got))
        self.env = {"STRATA_PIPER": str(exe), "STRATA_PIPER_VOICES": str(d / "voices")}
        self.fake_ff = {**self.env, "PATH": str(d / "bin")}

    def tearDown(self):
        self.tmp.cleanup()


class Speech(Fakes):
    """serve/speech.py"""

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_synthesize_default_voice_and_speed(self):
        wav = speech.synthesize("Hello there.", speed=2.0, env=self.env)
        self.assertEqual(wav, b"RIFFfakeWAVE")
        args = self.args.read_text()
        self.assertIn("en_US-hfc_male-medium.onnx", args)
        self.assertIn("--length_scale 0.500", args)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_wav_runs_piper_as_it_always_did(self):
        self.assertEqual(speech.synthesize("Hello.\n\nAgain.", env=self.env), b"RIFFfakeWAVE")
        model = self.dir / "voices" / "en_US-hfc_male-medium.onnx"
        self.assertEqual(self.args.read_text().split(), ["-q", "-m", str(model), "-f", "-", "--length_scale", "1.000",
                                                         "--sentence_silence", "0.250"])

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_opus_sends_piper_raw_samples_through_ffmpeg(self):
        ogg = speech.synthesize_opus("One line.\n\nAnother line.", speed=2.0, env=self.fake_ff)
        self.assertEqual(ogg, b"OggSfake")
        args = self.args.read_text().split()
        self.assertIn("--output_raw", args)
        self.assertNotIn("-f", args)
        self.assertIn("0.500", args)                      # the pace is the same as for WAV
        self.assertEqual(self.ff_got.stat().st_size, 3 * RAW_SECOND)   # every line, the blank one too
        encode = self.ff_args.read_text()
        for want in ("-f s16le -ar 22050 -ac 1 -i pipe:0", "-c:a libopus", f"-b:a {speech.OPUS_BITRATE}", "-f ogg"):
            self.assertIn(want, encode)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    @unittest.skipUnless(has_opus(), "needs ffmpeg with libopus")
    def test_opus_file_plays_for_every_line(self):
        ogg = speech.synthesize_opus("One line.\n\nAnother line.", env=self.env)     # the real ffmpeg
        self.assertEqual(ogg[:4], b"OggS")
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ar", "22050", "-ac", "1", "pipe:1"],
                             input=ogg, capture_output=True).stdout
        self.assertAlmostEqual(len(pcm) / RAW_SECOND, 3, delta=0.1)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_opus_refusals_come_before_piper_runs(self):
        with self.assertRaisesRegex(speech.SpeechError, "ffmpeg"):
            speech.synthesize_opus("hi", env={**self.env, "PATH": ""})
        (self.dir / "voices" / "en_US-other.onnx.json").write_text("{}")
        with self.assertRaisesRegex(speech.SpeechError, "sample rate"):
            speech.synthesize_opus("hi", voice="en_US-other", env=self.fake_ff)
        for text, voice in (("", None), ("x" * (speech.MAX_CHARS + 1), None), ("hi", "../etc"), ("hi", "nope")):
            with self.assertRaises(speech.SpeechError):
                speech.synthesize_opus(text, voice=voice, env=self.fake_ff)
        self.assertFalse(self.args.exists())

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_opus_failures(self):
        script(self.dir / "piper", "#!/bin/sh\necho broken voice >&2\nexit 3\n")
        with self.assertRaisesRegex(speech.SpeechError, "broken voice"):
            speech.synthesize_opus("hi", env=self.fake_ff)
        script(self.dir / "piper", "#!/bin/sh\nhead -c 44100 /dev/zero\n")
        script(self.dir / "bin" / "ffmpeg", "#!/bin/sh\necho no libopus >&2\nexit 1\n")
        with self.assertRaisesRegex(speech.SpeechError, "no libopus"):
            speech.synthesize_opus("hi", env=self.fake_ff)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_opus_stuck_piper_is_stopped(self):
        script(self.dir / "piper", "#!/bin/sh\nexec sleep 30\n")
        t0 = time.time()
        with self.assertRaisesRegex(speech.SpeechError, "too long"):
            speech.synthesize_opus("hi", env=self.fake_ff, timeout=0.3)
        self.assertLess(time.time() - t0, 5)

    def test_status(self):
        st = speech.get_tts_status(env=self.env)
        self.assertTrue(st["available"])
        self.assertEqual(st["voices"], ["en_US-hfc_male-medium", "en_US-other"])
        self.assertFalse(speech.get_tts_status(env={**self.env, "STRATA_TTS_VOICE": "missing"})["available"])

    def test_refusals(self):
        for text, voice in (("", None), ("x" * (speech.MAX_CHARS + 1), None), ("hi", "../etc"), ("hi", "nope")):
            with self.assertRaises(speech.SpeechError):
                speech.synthesize(text, voice=voice, env=self.env)


@unittest.skipIf(os.name == "nt", "POSIX only")
class Http(Fakes):
    """POST /v1/audio/speech on the real handler."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ, {**self.env, "PATH": self.fake_ff["PATH"] + os.pathsep + os.environ["PATH"]})
        patch.start()
        self.addCleanup(patch.stop)
        tok = ByteTokenizer()
        self.httpd = serve(Service(MockEngine(tok, "hi", max_context=4096), tok,
                                   ChatTemplate(ROOT / "serve/chat_template.jinja")), port=0)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def post(self, **body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/audio/speech",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Content-Type"), e.read()

    def test_wav_stays_the_default(self):
        for body in ({"input": "Hello."}, {"input": "Hello.", "response_format": "wav"}):
            self.assertEqual(self.post(**body), (200, "audio/wav", b"RIFFfakeWAVE"))

    def test_opus_is_an_ogg_file(self):
        self.assertEqual(self.post(input="Hello.", response_format="opus"), (200, "audio/ogg", b"OggSfake"))

    def test_other_formats_are_refused(self):
        status, _, body = self.post(input="Hello.", response_format="mp3")
        self.assertEqual(status, 400)
        self.assertIn(b"wav or opus", body)
        self.assertFalse(self.args.exists())

    def test_opus_without_ffmpeg_is_refused_at_once(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            status, _, body = self.post(input="Hello.", response_format="opus")
        self.assertEqual(status, 400)
        self.assertIn(b"ffmpeg", body)
        self.assertFalse(self.args.exists())


if __name__ == "__main__":
    unittest.main()
