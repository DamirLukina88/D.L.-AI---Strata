"""@file references: pictures, video frames, PDF pages, audio, and what is safe to inline.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
try:
    from .dl_common import (
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_API_KEY,
    DEFAULT_URL,
    cli as _cli,
    dl_mcp,
)
except ImportError:
    from dl_common import (
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_API_KEY,
    DEFAULT_URL,
    cli as _cli,
    dl_mcp,
)
try:
    from .dl_prompt import voice_note, with_now
except ImportError:
    from dl_prompt import voice_note, with_now


SENSITIVE_FILE_NAMES = {
    ".env", ".envrc", ".netrc", "_netrc", ".pgpass", ".htpasswd",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "identity",
    "credentials", "shadow", ".git-credentials", ".npmrc", ".pypirc",
}


SENSITIVE_EXTENSIONS = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".asc", ".gpg", ".kdbx",
}


SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker"}


def is_sensitive_file(p: Path) -> bool:
    """Heuristically flag paths that typically hold credentials or private keys."""
    name = p.name.lower()
    if name in SENSITIVE_FILE_NAMES or p.suffix.lower() in SENSITIVE_EXTENSIONS:
        return True
    if name.startswith(".env."):
        return True
    return any(part.lower() in SENSITIVE_DIRS for part in p.parts)


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".avif",
    ".ppm", ".pgm", ".pbm", ".pnm", ".ico", ".tga"
}


ATTACHED_IMAGE_LABEL = "Attached image, shown to you below"


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus"}


PDF_EXTENSIONS = {".pdf"}


BINARY_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".img",
    ".gguf", ".safetensors", ".pt", ".onnx",
    ".pyc", ".pyo", ".class", ".o", ".a",
    ".db", ".sqlite", ".sqlite3"
}


MEDIA_CACHE_DIR = Path.home() / ".local" / "state" / "dl-ai" / "media_cache"


def _sample_video_frames(video_path: Path, max_frames: int = 4) -> list[tuple[float, Path]]:
    """Extracts up to max_frames evenly spaced JPEG keyframes from a video using ffmpeg."""
    try:
        dur_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
        dur_str = subprocess.check_output(dur_cmd, timeout=5).decode().strip()
        duration = float(dur_str) if dur_str else 0.0
    except Exception:
        duration = 0.0

    if duration <= 0:
        return []

    vhash = hashlib.sha256(str(video_path.resolve()).encode()).hexdigest()[:16]
    out_dir = MEDIA_CACHE_DIR / "videos" / vhash
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    step = duration / (max_frames + 1)
    for i in range(1, max_frames + 1):
        ts = round(i * step, 2)
        out_f = out_dir / f"frame_{i}.jpg"
        if not out_f.is_file() or out_f.stat().st_size == 0:
            cmd = ["ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path),
                   "-vframes", "1", "-q:v", "2", str(out_f)]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)
            except Exception:
                continue
        if out_f.is_file() and out_f.stat().st_size > 0:
            frames.append((ts, out_f))
    return frames


def _render_pdf_pages(pdf_path: Path, max_pages: int = 4) -> list[Path]:
    """Renders the first max_pages of a PDF into PNG images at 150 DPI using pdftoppm."""
    phash = hashlib.sha256(str(pdf_path.resolve()).encode()).hexdigest()[:16]
    out_dir = MEDIA_CACHE_DIR / "pdfs" / phash
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = out_dir / "page"
    existing = sorted(out_dir.glob("page-*.png"))
    if not existing:
        cmd = ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", str(max_pages),
               str(pdf_path), str(prefix)]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=True)
        except Exception:
            pass
        existing = sorted(out_dir.glob("page-*.png"))
    return existing[:max_pages]


def _transcribe_audio_file(audio_path: Path, url: str = DEFAULT_URL, api_key: str = DEFAULT_API_KEY) -> str:
    """Transcribes an audio file using Strata's local Whisper endpoint (POST /v1/audio/transcriptions)."""
    try:
        raw_bytes = audio_path.read_bytes()
        payload = {"file": base64.b64encode(raw_bytes).decode("ascii")}
        endpoint = f"{url.rstrip('/')}/v1/audio/transcriptions"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {api_key}"} if api_key else {})
            }
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
            return (data.get("text") or "").strip()
    except Exception as e:
        return f"[Audio transcription unavailable: {e}]"


def resolve_file_references(prompt: str, workspace: Path) -> str:
    """Inlines text file references into markdown code blocks. Media references (images,
    videos, PDFs, audio, binary) are safely handled and never dumped as raw binary bytes."""
    pattern = r"@([a-zA-Z0-9_\-\.\/]+)"
    matches = list(re.finditer(pattern, prompt))
    if not matches:
        return prompt

    offset = 0
    new_prompt = prompt
    for m in matches:
        fpath_str = m.group(1)
        p = (workspace / fpath_str).resolve()
        if not p.is_file():
            p = Path(fpath_str).resolve()
        if p.is_file():
            if is_sensitive_file(p):
                sys.stderr.write(f"{C_RED}Blocked sensitive file injection: @{fpath_str} (credentials/private key guarded){C_RESET}\n")
                continue
            ext = p.suffix.lower()
            rel_path = p.relative_to(workspace) if p.is_relative_to(workspace) else p

            if ext in IMAGE_EXTENSIONS:
                replacement = f"[Image: {rel_path}]"
            elif ext in VIDEO_EXTENSIONS:
                frames = _cli()._sample_video_frames(p, max_frames=4)
                if frames:
                    ts_info = ", ".join(f"{t}s" for t, _ in frames)
                    replacement = f"[Video: {rel_path} ({len(frames)} frames @ {ts_info})]"
                else:
                    replacement = f"[Video: {rel_path}]"
            elif ext in PDF_EXTENSIONS:
                pages = _cli()._render_pdf_pages(p, max_pages=4)
                replacement = f"[PDF: {rel_path} ({len(pages)} page{'s' if len(pages)>1 else ''} rendered)]" if pages else f"[PDF: {rel_path}]"
            elif ext in AUDIO_EXTENSIONS:
                transcript = _cli()._transcribe_audio_file(p)
                replacement = f"\n\n[Audio: {rel_path} (Whisper transcription)]:\n{transcript}\n\n"
            elif ext in BINARY_EXTENSIONS:
                sz = p.stat().st_size
                sz_str = f"{sz / (1024*1024):.1f} MB" if sz > 1024*1024 else f"{sz / 1024:.1f} KB"
                replacement = f"[Binary file: {rel_path} ({sz_str}) - binary content not inlined]"
            else:
                try:
                    raw_head = p.read_bytes()[:1024]
                    if b"\x00" in raw_head:
                        replacement = f"[Binary file: {rel_path} - binary content not inlined]"
                    else:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        replacement = f"\n\n```file:{rel_path}\n{content}\n```\n"
                except Exception as e:
                    sys.stderr.write(f"{C_YELLOW}Warning: Could not read @{fpath_str}: {e}{C_RESET}\n")
                    continue

            start, end = m.start() + offset, m.end() + offset
            new_prompt = new_prompt[:start] + replacement + new_prompt[end:]
            offset += len(replacement) - (end - start)
    return new_prompt


# A tool that hands the model a picture puts [[image: <path in the workspace>]] in its result (the phone's photo
# tools; view_file on an image).  Only these tools may, and only image files inside the workspace count, so a fetched
# web page or another tool's text can't make the model read other files
IMAGE_RESULT_TOOLS = ("phone_camera_snap", "phone_get_last_photo", "phone_get_gallery_image", "view_file",
                      "browser_take_screenshot")


IMAGE_MARKER = re.compile(r"\[\[image:\s*([^\]\n]+?)\s*\]\]")


def tool_result_images(tool_name: str, result: str, workspace: Path) -> list[str]:
    """file:// URLs of the images a tool's result points at, from the allowed tools only (see IMAGE_RESULT_TOOLS).
    A relative path is looked up in the current project folder, then in the server's workspace root."""
    if not any(tool_name == t or tool_name.endswith("__" + t) for t in IMAGE_RESULT_TOOLS):
        return []
    roots = [Path(workspace).resolve()]
    env_root = os.environ.get("STRATA_WORKSPACE_DIR")
    if env_root:
        roots.append(Path(env_root).expanduser().resolve())
    if dl_mcp is not None and tool_name.endswith("__browser_take_screenshot"):
        roots.append(Path(dl_mcp.IMAGE_DIR).resolve())        # where the registry saved the screenshot
    urls = []
    for raw in IMAGE_MARKER.findall(result or ""):
        for root in roots:
            p = (root / raw.strip()).resolve()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS and (p == root or root in p.parents):
                urls.append(f"file://{p}")
                break
    return urls


def resolve_prompt_and_images(prompt: str, workspace: Path) -> tuple[str, list[str]]:
    """Resolves @file references, inlining text files, sampling video frames, rendering PDF
    pages, transcribing audio, and extracting all valid visual image paths for strata-vision."""
    pattern = r"@([a-zA-Z0-9_\-\.\/]+)"
    matches = list(re.finditer(pattern, prompt))
    if not matches:
        return prompt, []

    offset = 0
    new_prompt = prompt
    images: list[str] = []
    for m in matches:
        fpath_str = m.group(1)
        p = (workspace / fpath_str).resolve()
        if not p.is_file():
            p = Path(fpath_str).resolve()
        if p.is_file():
            if is_sensitive_file(p):
                sys.stderr.write(f"{C_RED}Blocked sensitive file injection: @{fpath_str} (credentials/private key guarded){C_RESET}\n")
                continue
            ext = p.suffix.lower()
            rel_path = p.relative_to(workspace) if p.is_relative_to(workspace) else p

            if ext in IMAGE_EXTENSIONS:
                # the model is told the picture is already in front of it (2026-11-15: Ray ran exiftool, magick,
                # xdg-open and a web server on an attached photo before answering it)
                replacement = f"[{ATTACHED_IMAGE_LABEL}: {rel_path}]"
                images.append(f"file://{p.resolve()}")
            elif ext in VIDEO_EXTENSIONS:
                frames = _cli()._sample_video_frames(p, max_frames=4)
                if frames:
                    ts_info = ", ".join(f"{t}s" for t, _ in frames)
                    replacement = f"[Video: {rel_path} ({len(frames)} frames @ {ts_info})]"
                    for _, frame_p in frames:
                        images.append(f"file://{frame_p.resolve()}")
                else:
                    replacement = f"[Video: {rel_path}]"
            elif ext in PDF_EXTENSIONS:
                pages = _cli()._render_pdf_pages(p, max_pages=4)
                if pages:
                    replacement = f"[PDF: {rel_path} ({len(pages)} page{'s' if len(pages)>1 else ''} rendered)]"
                    for page_p in pages:
                        images.append(f"file://{page_p.resolve()}")
                else:
                    replacement = f"[PDF: {rel_path}]"
            elif ext in AUDIO_EXTENSIONS:
                transcript = _cli()._transcribe_audio_file(p)
                replacement = f"\n\n[Audio: {rel_path} (Whisper transcription)]:\n{transcript}\n\n"
            elif ext in BINARY_EXTENSIONS:
                sz = p.stat().st_size
                sz_str = f"{sz / (1024*1024):.1f} MB" if sz > 1024*1024 else f"{sz / 1024:.1f} KB"
                replacement = f"[Binary file: {rel_path} ({sz_str}) - binary content not inlined]"
            else:
                try:
                    raw_head = p.read_bytes()[:1024]
                    if b"\x00" in raw_head:
                        replacement = f"[Binary file: {rel_path} - binary content not inlined]"
                    else:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        replacement = f"\n\n```file:{rel_path}\n{content}\n```\n"
                except Exception as e:
                    sys.stderr.write(f"{C_YELLOW}Warning: Could not read @{fpath_str}: {e}{C_RESET}\n")
                    continue

            start, end = m.start() + offset, m.end() + offset
            new_prompt = new_prompt[:start] + replacement + new_prompt[end:]
            offset += len(replacement) - (end - start)
    return new_prompt, images


def build_user_message_content(prompt: str, workspace: Path, voice: bool = False,
                               thinking: bool = True, device: str = "") -> str | list[dict]:
    """Builds user message content. If attached images (or sampled video frames / PDF pages) exist,
    produces an OpenAI-compatible multimodal parts list (text + image_url blocks) for strata-vision;
    otherwise returns a formatted text string.  A spoken prompt gets voice_note(thinking)."""
    resolved_prompt, images = resolve_prompt_and_images(prompt, workspace)
    clean_user_text = re.sub(r"\[(Attached image[^:\]]*|Image|Video|PDF|Binary file):[^\]]*\]", "", resolved_prompt).strip()
    if images and not clean_user_text:
        resolved_prompt = f"{resolved_prompt.strip()}\nDescribe this media and identify its key elements."

    base_text = with_now(resolved_prompt, device) + (f"\n\n{voice_note(thinking)}" if voice else "")
    if not images:
        return base_text

    parts: list[dict] = [{"type": "text", "text": base_text}]
    for img_url in images:
        parts.append({"type": "image_url", "image_url": {"url": img_url}})
    return parts
