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
import unicodedata
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


def clean_for_speech(text: str) -> str:
    """Prepares text for natural speech synthesis: removes emojis, pictograms, code blocks,
    markdown formatting, and translates numbers/units to plain spoken words."""
    if not text:
        return ""
    # 1. Remove thinking / reasoning blocks
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)<think>.*$", "", text)

    # 2. Fenced code blocks
    text = re.sub(r"(?m)(?:^|\n)```[^\n`]*\n[\s\S]*?(?:^|\n)```[ \t]*(?:\n|$)", " [Code block omitted.] ", text)
    text = re.sub(r"(?m)(?:^|\n)```[^\n`]*\n[\s\S]*$", " [Code block omitted.] ", text)

    # 3. Strip Markdown Headings (# Header)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)

    # 4. Strip Bold and Italics
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)

    # 5. Strip Blockquotes (> quote)
    text = re.sub(r"(?m)^>\s*", "", text)

    # 6. Strip List bullets and numbers
    text = re.sub(r"(?m)^[\s]*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^[\s]*\d+\.\s+", "", text)

    # 7. Strip inline code (`code`)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # 8. Convert markdown links [Label](url) to just Label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # 9. Strip bare URLs
    text = re.sub(r"https?://[^\s]+", "link", text)

    # 10. Strip horizontal rules
    text = re.sub(r"(?m)^[-*_]{3,}\s*$", "", text)

    # 11. Currency, percentages, temperatures
    text = re.sub(r"\$(\d+(?:\.\d+)?)", r"\1 dollars", text)
    text = re.sub(r"(\d+)\s*%", r"\1 percent", text)
    text = re.sub(r"%", " percent ", text)
    text = re.sub(r"(?i)(\d+)\s*°\s*C\b", r"\1 degrees Celsius", text)
    text = re.sub(r"(?i)(\d+)\s*°\s*F\b", r"\1 degrees Fahrenheit", text)
    text = re.sub(r"°", " degrees ", text)
    text = re.sub(r"~(\d+)", r"about \1", text)

    # 12. Translate speech-friendly symbols
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"->|→|=>|⇒", ", ", text)
    text = re.sub(r"\s*\+\s*", " plus ", text)
    text = re.sub(r"\s*=\s*", " equals ", text)

    # 13. Strip emojis, pictograms, variation selectors, skin tone modifiers
    chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        cp = ord(ch)
        # So: Symbol other (emojis, pictograms)
        # Sk: Symbol modifier
        if cat in ("So", "Sk") or cp in (0xFE0E, 0xFE0F, 0x200D) or (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF):
            continue
        chars.append(ch)
    text = "".join(chars)

    # 14. Strip technical punctuation and symbols
    text = re.sub(r"[~|^\\<>/#*_§©®™•●■◆▪▫◦★☆✓✔✕✖✗]", " ", text)

    # 15. Replace parentheses with commas
    text = re.sub(r"\(([^)]+)\)", r", \1, ", text)

    # 16. Normalize dashes
    text = re.sub(r"\s*[\u2012\u2013\u2014\u2015\u2212]\s*", ", ", text)

    # 17. Collapse duplicate whitespace and commas
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(\s*,)+", ",", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def synthesize(text: str, voice: str | None = None, speed: float = 1.0, env=None, timeout: float = 60) -> bytes:
    """WAV bytes (16-bit mono, the voice's own rate) for `text`; `speed` 1.0 is the voice's normal pace."""
    text = clean_for_speech(text)
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
           "--sentence_silence", f"{SENTENCE_SILENCE / speed:.3f}"]   # pauses follow the pace
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
