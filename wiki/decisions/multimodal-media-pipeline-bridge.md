---
title: "Multimodal Media Pipeline Bridge"
type: decision
description: "Routes attached images, video keyframes, rendered PDF pages, audio Whisper transcriptions, and blocks raw binaries in D.L. CLI and session daemon"
status: active
tags: [multimodal, vision, media, whisper, ffmpeg, pdftoppm, dl-cli, dl-sessiond]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Multimodal Media Pipeline Bridge

## Summary

2026-10-24: Fixed vision encoder ingestion and expanded multimodal media processing in `tools/dl_cli.py` and `tools/dl_sessiond.py` (`tools/test_dl_images.py`).

Previously, `resolve_file_references()` blindly invoked `p.read_text(encoding="utf-8", errors="replace")` on any `@file` reference. When a user attached an image, video, PDF, or audio file, 50,000+ tokens of raw mangled binary UTF-8 characters were dumped into the prompt inside a code block. Strata's `images_of()` detected zero `image_url` parts, leaving `strata-vision` idle while the model struggled to parse raw binary noise.

## Architecture

The unified media ingestion pipeline inspects file extensions referenced by `@path` (or attached via UI file manager) and routes each modality cleanly:

1. **Images (`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tiff`, `.tif`, `.avif`, `.ppm`, etc.)**:
   - In text: Replaced with `[Image: path]` (with an automatic default description request if no query text was entered).
   - In request payload: Injected as an OpenAI multimodal `image_url` block (`{"type": "image_url", "image_url": {"url": "file:///..."}}`).
   - Processed by Strata's `Vision.normalize()` and embedded by `strata-vision` via 2D M-RoPE ViT.

2. **Video Clips (`.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`)**:
   - Uses `/usr/bin/ffmpeg` and `/usr/bin/ffprobe` to compute duration and extract up to 4 evenly spaced JPEG keyframes into `~/.local/state/dl-ai/media_cache/videos/<hash>/`.
   - In text: `[Video: path (4 frames @ 1.5s, 3.0s, ...)]`.
   - In request payload: Injected as sequential `image_url` parts, allowing the model to visually inspect the temporal sequence.

3. **PDF Documents (`.pdf`)**:
   - Uses `/usr/bin/pdftoppm` to render the first 4 pages into crisp 150 DPI PNGs in `~/.local/state/dl-ai/media_cache/pdfs/<hash>/`.
   - In text: `[PDF: path (N pages rendered)]`.
   - In request payload: Injected as sequential `image_url` parts so the vision encoder reads page layouts, tables, and diagrams.

4. **Audio Recordings (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.aac`, `.opus`)**:
   - Transcribed directly via Strata's local offline Whisper engine at `POST /v1/audio/transcriptions` (`model: ggml-base.bin`).
   - In text: Inlined as `[Audio: path (Whisper transcription)]: <transcribed text>`.

5. **Binary Guards (`.zip`, `.tar`, `.exe`, `.bin`, `.gguf`, `.iso`, etc., and null-byte detection)**:
   - Guarded against context token flooding.
   - Replaced with `[Binary file: path (size) - binary content not inlined]`.

## Verification

- `tools/test_dl_images.py`: 11 unit tests covering images, video sampling, PDF rendering, Whisper audio transcription, markdown export, and binary guards.
- Live verification: Tested on `@/mnt/data/DL-AI-workspace/1f8193922fbf869134b1b7aeb03fd65e.jpg`; model accurately identified the kitten and duckling, and answered breed questions (Maine Coon tabby features).
- Audio endpoint verified: 1000 Hz tone transcribed locally via Whisper as `(beeps)`.
- Zero secrets confirmed with `dl_auditing.scan_secrets_in_text()`.

## Sources

1. User chat requests, 2026-10-24: investigating vision encoder failures with file manager attachments and enabling multi-modal media ingestion.
2. Codebase implementations: `serve/server.py` (`Vision.normalize`, `_audio_transcriptions`), `tools/vision/strata_vision.cpp`, `tools/dl_cli.py`, `tools/dl_sessiond.py`.

