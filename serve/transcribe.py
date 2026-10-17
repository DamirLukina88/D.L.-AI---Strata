"""serve/transcribe.py - local speech-to-text audio transcription via whisper.cpp / whisper.

Provides OpenAI-compatible audio transcription (POST /v1/audio/transcriptions)
running 100% locally on the user's PC with zero cloud connections.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class TranscriptionError(Exception):
    """Raised when audio transcription fails."""
    pass


def get_default_model_path() -> str | None:
    """Finds the best available local whisper model."""
    candidates = [
        os.path.expanduser("~/.local/share/whisper/models/ggml-base.bin"),
        os.path.expanduser("~/.local/share/whisper/models/ggml-tiny.bin"),
        os.path.expanduser("~/.local/share/whisper/models/ggml-small.bin"),
        os.path.expanduser("~/.cache/whisper/ggml-base.bin"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def get_stt_status() -> dict:
    """Returns the local STT capability status."""
    whisper_cli = shutil.which("whisper-cli")
    ffmpeg = shutil.which("ffmpeg")
    model_path = get_default_model_path()
    has_python_whisper = bool(shutil.which("whisper"))

    available = bool(ffmpeg and (whisper_cli and model_path or has_python_whisper))
    return {
        "available": available,
        "engine": "whisper-cli" if (whisper_cli and model_path) else ("openai-whisper" if has_python_whisper else None),
        "model": os.path.basename(model_path) if model_path else None,
        "ffmpeg": bool(ffmpeg),
    }


def clean_transcript(text: str) -> str:
    """Cleans whisper-cli standard output of runtime logs and timestamps."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip engine / miniaudio log lines
        if line.startswith("read_audio_data:") or line.startswith("load_backend:") or line.startswith("whisper_"):
            continue
        # Strip timestamps in brackets if present e.g. [00:00:00.000 --> 00:00:02.000]
        line = re.sub(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]", "", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def transcribe_audio(
    audio_bytes: bytes,
    language: str | None = None,
    prompt: str | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Transcribes raw audio bytes (WebM, OGG, WAV, MP3, etc.) using local Whisper.

    Args:
        audio_bytes: Binary audio payload.
        language: Language code (e.g. 'en', 'en-US', 'de', 'hr') or None/'auto'.
        prompt: Optional initial prompt for transcription context.
        timeout_s: Maximum execution duration in seconds.

    Returns:
        Transcribed plain text string.
    """
    if not audio_bytes:
        return ""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise TranscriptionError("ffmpeg is not installed on the system; required for audio transcoding")

    whisper_cli = shutil.which("whisper-cli")
    model_path = get_default_model_path()

    with tempfile.TemporaryDirectory(prefix="strata_stt_") as tmpdir:
        raw_path = os.path.join(tmpdir, "input.raw")
        wav_path = os.path.join(tmpdir, "converted.wav")

        with open(raw_path, "wb") as f:
            f.write(audio_bytes)

        # 1. Transcode input audio to standard 16kHz mono 16-bit PCM WAV via ffmpeg
        ff_cmd = [
            ffmpeg, "-y", "-i", raw_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            wav_path,
        ]
        try:
            ff_proc = subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10.0)
            if ff_proc.returncode != 0:
                err_msg = ff_proc.stderr.decode("utf-8", errors="ignore").strip()
                raise TranscriptionError(f"ffmpeg conversion failed: {err_msg[:200]}")
        except subprocess.TimeoutExpired:
            raise TranscriptionError("ffmpeg audio transcoding timed out")

        # Normalize language parameter (e.g. 'en-US' -> 'en')
        lang_code = None
        if language and language.strip() and language.strip().lower() != "auto":
            lang_code = language.strip().split("-")[0].split("_")[0].lower()

        # 2. Transcribe via whisper-cli (C++ engine) if model exists
        if whisper_cli and model_path:
            cmd = [whisper_cli, "-m", model_path, "-f", wav_path, "-nt", "-np"]
            if lang_code:
                cmd.extend(["-l", lang_code])
            if prompt:
                cmd.extend(["--prompt", prompt])

            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s, text=True)
                if proc.returncode != 0:
                    err_msg = proc.stderr.strip()
                    raise TranscriptionError(f"whisper-cli error: {err_msg[:200]}")
                return clean_transcript(proc.stdout)
            except subprocess.TimeoutExpired:
                raise TranscriptionError("whisper-cli transcription timed out")

        # 3. Fallback to /usr/bin/whisper (Python CLI)
        py_whisper = shutil.which("whisper")
        if py_whisper:
            cmd = [py_whisper, wav_path, "--output_dir", tmpdir, "--output_format", "txt"]
            if lang_code:
                cmd.extend(["--language", lang_code])
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s, text=True)
                txt_out = os.path.join(tmpdir, "converted.txt")
                if os.path.exists(txt_out):
                    with open(txt_out, "r", encoding="utf-8") as f:
                        return f.read().strip()
                return clean_transcript(proc.stdout)
            except subprocess.TimeoutExpired:
                raise TranscriptionError("whisper command timed out")

        raise TranscriptionError("No local Whisper engine or model found on the system")
