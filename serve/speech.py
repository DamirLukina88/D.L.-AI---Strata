"""serve/speech.py - local text-to-speech with Piper (POST /v1/audio/speech, OpenAI-compatible).

The web app plays this audio for Ray's voice, so the talking face can follow the real sound (its loudness) instead of
guessing the browser's speech timing, and phones hear the same Piper voice as the PC.  Nothing leaves the PC: the
`piper` program runs on the CPU, one short process per request.

Settings (environment): STRATA_PIPER (the piper program), STRATA_PIPER_VOICES (the folder with <voice>.onnx and
<voice>.onnx.json), STRATA_TTS_VOICE (default en_US-hfc_male-medium, Ray's voice).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

DEFAULT_VOICE = "en_US-hfc_male-medium"
MAX_CHARS = 4000                     # one request; the web app sends sentence-sized chunks
SENTENCE_SILENCE = 0.25              # seconds after each sentence, as speech-dispatcher's Piper had (0.2)
_slots = threading.BoundedSemaphore(2)


class SpeechError(Exception):
    """Raised when speech cannot be made; the message is safe to show."""


def piper_path(env=None) -> str | None:
    env = os.environ if env is None else env
    for p in (env.get("STRATA_PIPER"), shutil.which("piper"), os.path.expanduser("~/.local/bin/piper")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def voices_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("STRATA_PIPER_VOICES") or os.path.expanduser("~/.local/share/piper/voices"))


def voices(env=None) -> list[str]:
    d = voices_dir(env)
    try:
        return sorted(p.name[:-5] for p in d.glob("*.onnx") if (d / (p.name + ".json")).is_file())
    except OSError:
        return []


def default_voice(env=None) -> str:
    env = os.environ if env is None else env
    return env.get("STRATA_TTS_VOICE") or DEFAULT_VOICE


def get_tts_status(env=None) -> dict:
    have = voices(env)
    voice = default_voice(env)
    return {"available": bool(piper_path(env) and voice in have), "engine": "piper", "voice": voice, "voices": have}


def synthesize(text: str, voice: str | None = None, speed: float = 1.0, env=None, timeout: float = 60) -> bytes:
    """WAV bytes (16-bit mono, the voice's own rate) for `text`; `speed` 1.0 is the voice's normal pace."""
    text = (text or "").strip()
    if not text:
        raise SpeechError("no text to speak")
    if len(text) > MAX_CHARS:
        raise SpeechError(f"text is longer than {MAX_CHARS} characters; send it in parts")
    voice = voice or default_voice(env)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", voice) or voice not in voices(env):
        raise SpeechError(f"unknown voice {voice!r}")
    exe = piper_path(env)
    if not exe:
        raise SpeechError("piper is not installed (set STRATA_PIPER)")
    try:
        speed = min(3.0, max(0.3, float(speed or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    model = voices_dir(env) / f"{voice}.onnx"
    cmd = [exe, "-q", "-m", str(model), "-f", "-", "--length_scale", f"{1 / speed:.3f}",
           "--sentence_silence", str(SENTENCE_SILENCE)]
    with _slots:
        try:
            r = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SpeechError("piper took too long") from None
        except OSError as e:
            raise SpeechError(f"piper could not start: {e}") from None
    if r.returncode != 0 or r.stdout[:4] != b"RIFF":
        raise SpeechError(f"piper failed: {r.stderr.decode('utf-8', 'replace').strip()[:200] or r.returncode}")
    return r.stdout
