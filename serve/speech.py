"""serve/speech.py - local text-to-speech with Piper (POST /v1/audio/speech, OpenAI-compatible).

The web app plays this audio for Ray's voice, so the talking face can follow the real sound (its loudness) instead of
guessing the browser's speech timing, and phones hear the same Piper voice as the PC.  Nothing leaves the PC: the
`piper` program runs on the CPU, one short process per request.  WAV is the default; the phone asks for Ogg Opus
(ffmpeg), about a tenth of the size, so a long answer doesn't spend seconds on mobile data.

Settings (environment): STRATA_PIPER (the piper program), STRATA_PIPER_VOICES (the folder with <voice>.onnx and
<voice>.onnx.json), STRATA_TTS_VOICE (default en_US-hfc_male-medium, Ray's voice).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from pathlib import Path

DEFAULT_VOICE = "en_US-hfc_male-medium"
MAX_CHARS = 4000                     # one request; the web app sends sentence-sized chunks
SENTENCE_SILENCE = 0.25              # seconds after each sentence, as speech-dispatcher's Piper had (0.2)
# Ogg Opus settings, measured on 42 s of Ray's voice (2026-11-04): 212 KB against 1.8 MB of WAV.  At about 200 KB this
# is 1.0-1.2 dB from the original in every Bark band; effort 10 at 40k is 0.2 dB closer below 2.7 kHz but 1.6-2.3 dB off
# above it, where consonants are and where Ray's pitch moves more of his voice.  The "voip" mode was further off
OPUS_BITRATE = "32k"
OPUS_EFFORT = "5"
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


def ffmpeg_path(env=None) -> str | None:
    env = os.environ if env is None else env
    return shutil.which("ffmpeg", path=env.get("PATH"))


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


def _piper_command(text: str, voice: str | None, speed: float, env, output: list) -> tuple:
    """(the piper command writing to `output`, its input, the voice's model); SpeechError when it can't be run."""
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
    cmd = [exe, "-q", "-m", str(model), *output, "--length_scale", f"{1 / speed:.3f}",
           "--sentence_silence", f"{SENTENCE_SILENCE / speed:.3f}"]   # pauses follow the pace
    return cmd, text.encode("utf-8"), model


def synthesize(text: str, voice: str | None = None, speed: float = 1.0, env=None, timeout: float = 60) -> bytes:
    """WAV bytes (16-bit mono, the voice's own rate) for `text`; `speed` 1.0 is the voice's normal pace.  Piper writes
    one WAV per line of `text`, one after the other, and players stop at the end of the first."""
    cmd, data, _ = _piper_command(text, voice, speed, env, ["-f", "-"])
    with _slots:
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SpeechError("piper took too long") from None
        except OSError as e:
            raise SpeechError(f"piper could not start: {e}") from None
    if r.returncode != 0 or r.stdout[:4] != b"RIFF":
        raise SpeechError(f"piper failed: {r.stderr.decode('utf-8', 'replace').strip()[:200] or r.returncode}")
    return r.stdout


def synthesize_opus(text: str, voice: str | None = None, speed: float = 1.0, env=None, timeout: float = 60) -> bytes:
    """Ogg Opus bytes for `text`, for mobile data.  Piper's raw samples go straight into ffmpeg, so every line of `text`
    is in the file (raw has no WAV per line) and the encoding runs while Piper speaks (42 s of speech: 40 ms on top of
    Piper, against 150 ms after it)."""
    cmd, data, model = _piper_command(text, voice, speed, env, ["--output_raw"])
    ffmpeg = ffmpeg_path(env)
    if not ffmpeg:
        raise SpeechError("opus needs ffmpeg, which is not installed")
    try:
        rate = int(json.loads(model.with_name(model.name + ".json").read_text(encoding="utf-8"))["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise SpeechError(f"the voice's sample rate is unknown: {e!r}") from None
    encode = [ffmpeg, "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0", "-c:a", "libopus",
              "-b:a", OPUS_BITRATE, "-application", "audio", "-compression_level", OPUS_EFFORT, "-f", "ogg", "pipe:1"]
    # the text comes from a file: a pipe could wait on piper while piper waits on ffmpeg
    with _slots, tempfile.TemporaryFile() as said:
        said.write(data)
        said.seek(0)
        try:
            piper = subprocess.Popen(cmd, stdin=said, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise SpeechError(f"piper could not start: {e}") from None
        with piper:
            try:
                r = subprocess.run(encode, stdin=piper.stdout, capture_output=True, timeout=timeout)
                piper.stdout.close()                          # piper can't wait on an ffmpeg that stopped
                piper.wait(timeout=5)
                problem = piper.stderr.read() + r.stderr
            except subprocess.TimeoutExpired:
                raise SpeechError("piper took too long") from None
            except OSError as e:
                raise SpeechError(f"ffmpeg could not start: {e}") from None
            finally:
                piper.kill()                                  # nothing when it has ended
    if piper.returncode != 0 or r.returncode != 0 or r.stdout[:4] != b"OggS":
        raise SpeechError(f"opus failed: {problem.decode('utf-8', 'replace').strip()[:200] or r.returncode}")
    return r.stdout
