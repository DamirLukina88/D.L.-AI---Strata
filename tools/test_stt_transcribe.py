"""tools/test_stt_transcribe.py - Unit tests for local Whisper speech transcription.

Tests:
1. get_stt_status() model detection and capabilities
2. clean_transcript() log & timestamp stripping
3. transcribe_audio() WAV audio transcription
4. transcribe_audio() WebM Opus transcoding and transcription
5. Error handling for empty/corrupt audio
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve.transcribe import (
    clean_transcript,
    get_default_model_path,
    get_stt_status,
    transcribe_audio,
    TranscriptionError,
)


class TestSTTTranscribe(unittest.TestCase):

    def test_clean_transcript_timestamps_and_logs(self):
        raw = (
            "read_audio_data: audio loaded\n"
            "whisper_init_state: kv size = 128 MB\n"
            "[00:00:00.000 --> 00:00:02.000]   Hello world!\n"
            "[00:00:02.000 --> 00:00:04.500]   This is Strata.\n"
        )
        cleaned = clean_transcript(raw)
        self.assertEqual(cleaned, "Hello world! This is Strata.")

    def test_clean_transcript_empty(self):
        self.assertEqual(clean_transcript(""), "")
        self.assertEqual(clean_transcript("   \n\n  "), "")

    def test_stt_status(self):
        status = get_stt_status()
        self.assertIsInstance(status, dict)
        self.assertIn("available", status)
        self.assertIn("engine", status)
        self.assertIn("model", status)
        self.assertIn("ffmpeg", status)
        self.assertTrue(status["ffmpeg"], "ffmpeg should be available on the system")
        if status["available"]:
            self.assertIsNotNone(status["model"])
            self.assertEqual(status["engine"], "whisper-cli")

    def test_transcribe_empty_bytes(self):
        res = transcribe_audio(b"")
        self.assertEqual(res, "")

    def test_transcribe_synthetic_speech_wav(self):
        # Synthesize audio with Piper if model exists
        piper_model = os.path.expanduser("~/.local/share/piper/voices/en_US-lessac-medium.onnx")
        if not os.path.isfile(piper_model):
            self.skipTest("Piper voice model not found for synthetic speech test")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        try:
            phrase = "Hello world from Strata speech recognition."
            proc = subprocess.run(
                ["piper", "--model", piper_model, "--output_file", wav_path],
                input=phrase,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, f"Piper failed: {proc.stderr}")

            with open(wav_path, "rb") as f:
                wav_bytes = f.read()

            result = transcribe_audio(wav_bytes, language="en")
            self.assertTrue(len(result) > 0, "Expected non-empty transcript")
            # Case-insensitive check of core words
            lower = result.lower()
            self.assertTrue("hello" in lower or "world" in lower or "strata" in lower, f"Unexpected transcript: {result}")
        finally:
            if os.path.exists(wav_path):
                os.unlink(wav_path)

    def test_transcribe_synthetic_speech_webm(self):
        piper_model = os.path.expanduser("~/.local/share/piper/voices/en_US-lessac-medium.onnx")
        if not os.path.isfile(piper_model):
            self.skipTest("Piper voice model not found for synthetic speech test")

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = os.path.join(tmpdir, "in.wav")
            webm_path = os.path.join(tmpdir, "out.webm")

            phrase = "Testing speech to text."
            proc = subprocess.run(
                ["piper", "--model", piper_model, "--output_file", wav_path],
                input=phrase,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0)

            # Transcode to WebM Opus
            ff_proc = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", webm_path],
                capture_output=True,
            )
            self.assertEqual(ff_proc.returncode, 0)

            with open(webm_path, "rb") as f:
                webm_bytes = f.read()

            result = transcribe_audio(webm_bytes, language="en-US")
            self.assertTrue(len(result) > 0, "Expected non-empty transcript")
            lower = result.lower()
            self.assertTrue("speech" in lower or "testing" in lower or "text" in lower, f"Unexpected transcript: {result}")


if __name__ == "__main__":
    unittest.main()
