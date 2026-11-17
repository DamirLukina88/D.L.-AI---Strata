"""serve/server.py - plan v0.3 P8: OpenAI and Anthropic endpoints over any engine that maps token ids to tokens.

    python -m serve.server --engine mock --port 8095            (a scripted engine, for clients and tests)
    python -m serve.server --engine strata --config strata.json --port 8080   (the real engine, resident)

Endpoints: POST /v1/chat/completions (OpenAI, stream and non-stream), POST /v1/messages (Anthropic, stream and
non-stream), GET /v1/models, GET /models, GET /props, GET /slots, GET /health, GET /mcp. One sequence at a time behind a FIFO (plan: one resident sequence).
Image generation (optional, when the config has an "images" section): POST /v1/images/generations (OpenAI's shape,
plus seed and steps) runs stable-diffusion.cpp's sd-cli for Qwen-Image-2.1-Turbo, one job at a time on the GPU the
text engine uses (serve/images.py).
Tools from MCP servers (serve/mcp.py, `"mcp_servers"` in the config or --mcp-config) are offered only to requests that
ask for them with `"strata_mcp": true` - the web app does; other clients see exactly the API they always saw.
Images (optional, when the config has a "vision" entry): OpenAI image_url parts and Anthropic image blocks (base64
data, http(s) URLs or local file paths) go through `strata-vision` (the model's mmproj file) and reach the engine as
embeddings (`GENI`).  JPEG/PNG/BMP/GIF go straight in; WebP, TIFF, AVIF, ... (agents like omp send WebP) are
converted to PNG first with Pillow.
Requests whose prompt plus max tokens exceed the engine's context are REJECTED with 400, never truncated.
An unset (or 0, or -1) max tokens means "unlimited": whatever the prompt leaves of the context.

The engine boundary is `Engine.generate(prompt_ids, max_new, sampling, cancel) -> iterator of token ids`.
`StrataEngine` keeps one `strata --serve` process resident (weights, expert arena and VRAM tier load once) and
talks to it over stdin/stdout; `MockEngine` is a scripted stand-in that makes every API path testable without a GPU.
"""
from __future__ import annotations

import argparse
import contextlib
import collections
import base64
import hashlib
import hmac
import codecs
import ctypes
import json
import math
import mimetypes
import os
import queue
import re
import select
import signal
import socket
import socketserver
import struct
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Iterator, Protocol
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))   # run as a script (run-<model>.bat) as well as a module

if __name__ == "__main__":
    # run as a script or with -m: load the real module first, so the moved code and this entry point share their names
    import importlib
    raise SystemExit(importlib.import_module("serve.server").main())
if __name__ == "server":
    # imported as a flat module (serve/ on sys.path): be serve.server, so a patch on it reaches the split modules
    import importlib
    sys.modules[__name__] = importlib.import_module("serve.server")

from serve.frontend import (THINK_END, ChatTemplate, Event, OutputParser, anthropic_to_messages,  # noqa: E402
                            forced_call, images_of, literal_tags, mark_think_literals, openai_to_messages, require_messages,
                            tool_choice_of, unmark_think_literals)
from serve.mcp import McpCancelled, hub_from_config  # noqa: E402
from serve import runconfig  # noqa: E402
from serve import cf_access  # noqa: E402
from serve import logit_bias as bias_api  # noqa: E402
from serve.childenv import quiet_crash_env  # noqa: E402
from serve.winjob import contain  # noqa: E402
from serve.structured import StructuredOutputError, prepare_format, validated_json  # noqa: E402
from serve import responses as responses_api  # noqa: E402
from serve.responses import ResponsesError, error_body as responses_error_body  # noqa: E402
from serve import images as images_api  # noqa: E402

# The code below was split into serve/*.py modules; every name is re-exported here because the importers
# (tests, tools, the SYCL wrapper) use `serve.server.<name>`.
from serve.errors import (  # noqa: E402,F401
    ClientGone,
    EngineDied,
    EngineNonFinite,
    EngineSilent,
    EngineStarting,
    EngineStuck,
    GpuBusy,
    ModelBusy,
    SessionRefused,
)
from serve.tunables import (  # noqa: E402,F401
    ANSWER_RESERVE_MIN,
    ANSWER_ROOM_MIN_CAP,
    CTX_SLACK,
    EFFORT_TEXT,
    EFFORT_TURN,
    ENGINE_CANCEL_S,
    ENGINE_READY_S,
    ENGINE_SILENCE_S,
    ENGINE_STALL_S,
    HIGH_EFFORT,
    KEEPALIVE_S,
    LOOPBACK_NAMES,
    LOOP_CHECK_EVERY,
    LOOP_COVERAGE,
    LOOP_HISTORY_WORDS,
    LOOP_TAIL_CHARS,
    LOOP_TAIL_PERIOD,
    LOW_EFFORT,
    MAX_START_WAIT,
    PP_CHUNK_MAX,
    PP_FLOOR_TOK_S,
    PP_SLACK,
    QUEUE_BEAT_S,
    RATE_MIN_SPAN_S,
    RATE_WINDOW_S,
    REASONING_CLOSE,
    REASONING_WRAP_UP,
    REPEAT_STOP_TOKENS,
    SESSION_WAIT_MAX_S,
    STALL_CPU_EPS_S,
    STALL_IO_EPS_B,
    STREAM_WRITE_TIMEOUT_S,
    VISION_ENCODE_S,
    VISION_READY_S,
    VISION_START,
    _timeout_env,
    batch_slots_on,
    calculate_start_wait,
    died_note,
    engine_frozen,
    focused_recovery_prompt,
    reasoning_repeat_coverage,
)
from serve.ray_phone import (  # noqa: E402,F401
    PHONE_BRIDGE,
    PHONE_CLIPBOARD_PATH,
    PHONE_DOWNLOAD_PATH,
    PHONE_PENDING_PATH,
    PHONE_RESULT_PATH,
    PHONE_SENSORS_STREAM_PATH,
    PHONE_UPLOAD_PATH,
    PhoneBridge,
    _download_tickets,
    _download_tickets_lock,
    is_phone_photo,
    new_download_ticket,
    safe_workspace_path,
    take_download_ticket,
)
from serve.engine_args import (  # noqa: E402,F401
    PARALLEL_MAX,
    _dir_writable,
    child_env,
    combined_embeddings_path,
    effort_end_args,
    engine_args,
    engine_binary,
    engine_silence_s,
    gpu_list,
    gpu_speed_scores,
    gpu_vram_mib,
    hip_env_guard,
    hip_speed_scores,
    hip_visible,
    layer_split_of,
    layer_split_value,
    learned_profile_args,
    listen_problem,
    ordered_gpus,
    parallel_args,
    popen,
    profile_shape,
    vision_env,
    write_temporary,
)
from serve.engine import (  # noqa: E402,F401
    ConvCacheLog,
    DEGRADED_HEADROOM_GIB,
    DEGRADED_START,
    DRAFT_HEAD_FAIL,
    DRAFT_HEAD_HINT,
    ENGINE_REQUEST,
    EOS_IDS,
    Engine,
    FATAL_PREFIXES,
    MockEngine,
    STALL_LOG,
    START_RETRIES,
    StrataEngine,
    TRANSIENT_START_MARKS,
    _BTRACE,
    _WIN_CRASH,
    _echoing,
    btrace,
    conversation_cache_view,
    conversation_slots,
    cpu_isa_words,
    degraded_start,
    echo_requests,
    end_leftover_engines,
    engine_crashed,
    engine_exit_words,
    experts_loading_words,
    log_stall,
    mem_available_gib,
    narrate_start,
    start_exit_note,
    start_failure_hint,
    start_log_marks,
    start_log_tail,
    transient_start_failure,
    unload_wait,
)
from serve.vision import (  # noqa: E402,F401
    IMAGE_URL_MAX,
    Vision,
    _VISION_ARCH_SIGNS,
    network_path,
    vision_log_tail,
    vision_start_error,
)
from serve.textcore import (  # noqa: E402,F401
    ByteTokenizer,
    Detokenizer,
    OPENAI_MAX_STOP,
    StopMatcher,
    _WIN_DEVICES,
    load_tokenizer_from_path,
    slot_filename_problem,
    slot_save_dir,
    stop_strings,
)
from serve.request_stats import (  # noqa: E402,F401
    add_carry,
    answer_speed,
    carry_leg,
    prefill_leg_stats,
    prompt_tokens_seen,
    request_stats,
    request_timings,
)
from serve.service import (  # noqa: E402,F401
    Service,
    _debug_req,
    _dump_claude_prompt,
    run_with_mcp,
)
from serve.api_formats import (  # noqa: E402,F401
    PP_DONE_TAIL,
    _is_json,
    anthropic_collect,
    anthropic_events,
    openai_chunks,
    openai_collect,
    prompt_progress,
    structured_chunks,
)
from serve.http_security import (  # noqa: E402,F401
    DESKTOP_FREE_MIB,
    DESKTOP_RESERVE_MIB,
    _is_ip,
    _name_in,
    allowed_hosts_of,
    api_key_of,
    desktop_vram_note,
    host_allowed,
    host_name,
    host_names_for,
    key_list,
    key_matches,
    lan_addresses,
    linux_desktop,
    origin_allowed,
    origins_of,
    warn_budget_over_ram,
    warn_tight_ram,
)
from serve.config import (  # noqa: E402,F401
    FAMILY_MODEL_NAMES,
    SAMPLING_ALIASES,
    SHARED_KEYS,
    check_request_sampling,
    clean_shared_defaults,
    default_model_name,
    lift_reasoning_effort_arg,
    sampling_defaults_from_config,
    start_replicas,
)


IM_END = "<|im_end|>"


IMAGE_PAD = "<|image_pad|>"


WORKSPACE_DIR = Path(os.environ.get("STRATA_WORKSPACE_DIR", str(Path.cwd() / "workspace"))).resolve()


WORKSPACE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


WORKSPACE_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".pyi", ".ipynb", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".json", ".jsonl", ".csv", ".tsv", ".log",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml", ".html", ".htm",
    ".css", ".scss", ".less", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".cu",
    ".cuh", ".rs", ".go", ".java", ".kt", ".kts", ".swift", ".rb", ".php", ".pl", ".lua",
    ".r", ".jl", ".scala", ".sql", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".diff", ".patch", ".dockerfile", ".gitignore", ".proto", ".graphql"
}


SESSIOND_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "dl-ai" / "sessiond.sock"


# ------------------------------------------------------------------------------------------------ HTTP
CHUNKED_BODY_MAX = 256 << 20                # #893: the most a Transfer-Encoding: chunked body may hold (read into memory)


def body_limit() -> int:
    """The most a request body may hold, in bytes (read into memory): 256 MiB, which is a million-token conversation
    with room to spare; STRATA_MAX_BODY_MIB changes it (0 or an unreadable value: the default).  A larger one is
    answered 413 before it is read (a Content-Length of 10 TB used to be read until the client gave up)."""
    try:
        mib = int(os.environ.get("STRATA_MAX_BODY_MIB", "0"))
    except ValueError:
        mib = 0
    return mib << 20 if mib > 0 else CHUNKED_BODY_MAX


class BadBody(Exception):
    """A request body that cannot be read (a malformed or oversized chunked body): the status and the sentence."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"                       # SSE ends by closing the connection

        record = None                                       # #332: this request's monitor record, if kept
        watch_done = None                                   # #430 #431: stops this request's disconnect watcher
        body_read = False                                   # whether a handler took this request's body
        DRAIN_SECONDS = 5                                   # the longest an unread body is read and dropped

        def log_message(self, fmt, *args):
            pass

        def handle_one_request(self):
            self.answer_started = False
            super().handle_one_request()
            self._drain_body()

        def send_response(self, code, message=None):
            self.answer_started = True                 # a malformed-request answer can only replace one not yet begun
            super().send_response(code, message)

        def _chunked(self) -> bool:
            """#893: a body sent as Transfer-Encoding: chunked (a relay or proxy that does not buffer it).  By RFC 9112
            it wins over a Content-Length."""
            te = self.headers.get("Transfer-Encoding", "") or ""
            return te.split(",")[-1].strip().lower() == "chunked"

        def _read_chunked(self, limit: int, keep: bool = True, deadline: float | None = None) -> bytes:
            """Decode a chunked body: at most `limit` bytes (BadBody 413 beyond it - the size is checked before a chunk
            is read, so a huge announced chunk is never allocated), BadBody 400 for a malformed one.  keep=False reads
            and drops it (the drain); `deadline` (monotonic) ends the read early."""
            parts, total = [], 0
            while True:
                if deadline is not None:
                    wait = deadline - time.monotonic()
                    if wait <= 0:
                        return b"".join(parts)
                    self.connection.settimeout(wait)
                line = self.rfile.readline(1025)
                if not line.endswith(b"\n"):
                    raise BadBody(400, "malformed chunked request body")
                try:
                    size = int(line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    raise BadBody(400, "malformed chunk size in the request body") from None
                if size < 0:
                    raise BadBody(400, "malformed chunk size in the request body")
                if size == 0:
                    for _ in range(64):                       # the trailers, including the final blank line
                        trailer = self.rfile.readline(8193)
                        if trailer == b"\r\n":
                            return b"".join(parts)
                        if not trailer.endswith(b"\r\n"):
                            raise BadBody(400, "malformed or incomplete chunked request trailers")
                    raise BadBody(400, "too many chunked request trailers")
                total += size
                if total > limit:
                    self.close_connection = True
                    raise BadBody(413, f"the request body is larger than {limit >> 20} MiB")
                left = size
                while left > 0:
                    piece = self.rfile.read(min(left, 1 << 20))
                    if not piece:
                        raise BadBody(400, "the chunked request body ended early")
                    left -= len(piece)
                    if keep:
                        parts.append(piece)
                if self.rfile.read(2) != b"\r\n":
                    raise BadBody(400, "malformed chunked request body")

        def _body(self) -> bytes:
            self.body_read = True
            limit = body_limit()
            if self._chunked():
                return self._read_chunked(limit)
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                raise BadBody(400, "invalid Content-Length") from None
            if length < 0:
                raise BadBody(400, "invalid Content-Length")
            if length > limit:
                self.close_connection = True               # the body is not read: the connection ends with the answer
                raise BadBody(413, f"the request body is larger than {limit >> 20} MiB "
                                   "(STRATA_MAX_BODY_MIB raises the limit)")
            return self.rfile.read(length)

        def _drain_body(self):
            """An answer sent before the body was read (a 401, a 403, /load, a method with no handler) must not close
            the connection on unread bytes: the close then sends a reset, and a client that sends its body after the
            headers (http.client, urllib, requests) gets a connection error instead of the answer.  So the body is
            read and dropped here, once, after an answer, in pieces so that its size is never held in memory.  What
            has not arrived DRAIN_SECONDS later is left unread: the limit is time, so that a conversation of many
            megabytes, at any speed the client has, still gets its answer."""
            headers = getattr(self, "headers", None)
            if self.body_read or headers is None:
                return
            if self._chunked():
                try:
                    self._read_chunked(body_limit(), keep=False, deadline=time.monotonic() + self.DRAIN_SECONDS)
                except (BadBody, OSError):
                    self.close_connection = True
                return
            try:
                left = int(headers.get("Content-Length", 0))
            except ValueError:
                return
            if left <= 0:
                return
            deadline = time.monotonic() + self.DRAIN_SECONDS
            try:
                while left > 0 and (wait := deadline - time.monotonic()) > 0:
                    self.connection.settimeout(wait)         # a client that never sends what it announced
                    piece = self.rfile.read1(min(left, 1 << 20))   # one socket read: read() would wait for it all
                    if not piece:
                        break
                    left -= len(piece)
            except OSError:
                pass

        def parse_request(self):
            """Without an API key, every request (any method) first passes the Host check: DNS rebinding protection
            (host_allowed).  With a key a rebinding page cannot authenticate, so the check is skipped: tunnels and
            proxies that pass their own name on keep working."""
            if not super().parse_request():
                return False
            host = self.headers.get("Host")
            if svc.api_key or host_allowed(host, svc.host_names, "*" in svc.allowed_hosts):
                return True
            print(f"[strata] refused a request for Host {host!r} from {self.client_address[0]}: not a name this server "
                  f"answers to (add it to \"allowed_hosts\" in the config or STRATA_ALLOWED_HOSTS, or set an API key)",
                  flush=True)
            self._json(403, {"error": {"type": "forbidden", "message":
                             f"Host {host!r} is not allowed (DNS rebinding protection). Reaching Strata under this "
                             f"name on purpose? Add it to \"allowed_hosts\" in the config (strata-<model>.json) or to "
                             f"the STRATA_ALLOWED_HOSTS environment variable, or set an API key (\"api_key\"), which "
                             f"turns this check off"}})
            return False

        def _foreign_page(self) -> bool:
            """Without an explicit API key (for example when open, or when authenticated by an ambient Cloudflare
            Access cookie), a /v1 POST from a browser page of another site (any site can POST text/plain there
            without a CORS preflight) would burn GPU time: an Origin header must name an allowed page, and then
            the body must be JSON.  No Origin (curl, the SDKs, other servers) or an explicit API key: any content
            type, as before."""
            origin = self.headers.get("Origin")
            if not origin or self._given_key():
                return False
            if not origin_allowed(origin, self.headers.get("Host"), svc.host_names,
                                  [*svc.trusted_origins, *svc.cors_origins]):
                print(f"[strata] refused an API request from the web page {origin!r} (no API key; add its host to "
                      f"\"allowed_hosts\" or its origin to \"cors_origins\" in the config)", flush=True)
                self._json(403, {"error": {"type": "forbidden", "message":
                                 f"web pages of {origin} may not use this server without an API key; set \"api_key\", "
                                 f"or add the page's host to \"allowed_hosts\" (or its origin to \"cors_origins\") "
                                 f"in the config"}})
                return True
            ctype = self.headers.get("Content-Type", "")
            # the web app's own speech-to-text upload is a FormData (multipart): from Strata's own page (or a trusted
            # origin) it is the user's, not a cross-site POST, and behind Cloudflare Access no key is sent
            if self.path.split("?", 1)[0] == "/v1/audio/transcriptions" and \
                    ctype.startswith("multipart/form-data") and not self._foreign_origin():
                return False
            if not ctype.startswith("application/json"):
                self._json(415, {"error": {"message": "send application/json"}})
                return True
            return False

        def end_headers(self):
            # HTTP/1.0 without keep-alive: the server closes the connection after every response.  Say so, or a
            # client that pools connections (.NET's SocketsHttpHandler) can put its next request on this socket
            # before the close reaches it, and that request fails with "response ended prematurely" without the
            # server ever reading it (a .NET agent app, 2026-10-03: 25 of ~1000 requests, 1-24 ms after the previous answer).
            self.send_header("Connection", "close")
            super().end_headers()

        def _watch_client(self, cancel: threading.Event) -> None:
            """#430 #431: cancel the request as soon as its client hangs up.  A non-streamed request writes nothing
            until it ends, and a streamed one only a keep-alive per prompt chunk (and the first write after a hang-up
            usually still succeeds), so a dropped request kept the engine busy until its answer or the whole prompt
            was done.  Every 0.5 s: the socket readable with nothing to read (EOF) means the client closed it.  A
            request is HTTP/1.0 and fully read here, so no later bytes are expected - data is not a hang-up."""
            done = self.watch_done = threading.Event()
            sock = self.connection

            def watch():
                while not done.wait(0.5) and not cancel.is_set():
                    try:
                        readable, _, _ = select.select([sock], [], [], 0)
                        gone = bool(readable) and sock.recv(1, socket.MSG_PEEK) == b""
                    except (ConnectionError, TimeoutError):
                        gone = True
                    except (OSError, ValueError):            # the socket was closed here: the request has ended
                        return
                    if gone:
                        self._note(outcome="disconnected")
                        cancel.set()
                        return

            threading.Thread(target=watch, daemon=True, name="strata-client-watch").start()

        def _note(self, **values):
            """#332: what the monitor shows about this request (nothing when the monitor is off)."""
            if self.record is not None:
                with svc.status_lock:
                    self.record.update(values)

        def _cors(self):
            """#321: CORS headers for an API path (/v1/*) and an origin the config lists in cors_origins - nothing
            otherwise, so a browser keeps every other page away from the API, /settings, /unload and the MCP tools."""
            if not svc.cors_origins or not self.path.split("?")[0].startswith("/v1/"):
                return
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if "*" in svc.cors_origins:
                allow = "*"
            elif origin and origin in svc.cors_origins:
                allow = origin
                self.send_header("Vary", "Origin")
            else:
                return
            self.send_header("Access-Control-Allow-Origin", allow)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            # the headers the preflight asks for (SDKs add their own; "*" does not cover Authorization)
            asked = self.headers.get("Access-Control-Request-Headers")
            self.send_header("Access-Control-Allow-Headers",
                             asked or "Authorization, Content-Type, x-api-key, anthropic-version, anthropic-beta")
            self.send_header("Access-Control-Max-Age", "600")

        def do_OPTIONS(self):
            # a CORS preflight: no credentials come with it, so no API key; the headers only for cors_origins
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _json(self, code, obj, headers=None):
            if self.record is not None:
                with svc.status_lock:
                    self.record["http_status"] = code
                    raw = json.dumps(obj, ensure_ascii=False, indent=2)
                    self.record.update(response=raw[:262144], response_truncated=len(raw) > 262144)
                    for key in ("error", "usage", "timings"):
                        if key in obj:
                            self.record[key] = obj[key]
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, str(v))
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file_download(self, target: Path):
            size = target.stat().st_size
            start, end = 0, size - 1
            rng = self.headers.get("Range", "")
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
            partial = bool(m and (m.group(1) or m.group(2)))
            if partial:
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:                                       # bytes=-N: the last N bytes
                    start = max(size - int(m.group(2)), 0)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            ascii_name = target.name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
            try:
                f = open(target, "rb")
            except OSError as e:
                self._json(500, {"error": {"message": f"download failed: {e}"}})
                return
            with f:
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Disposition",
                                 f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(target.name)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                if self.command == "HEAD":
                    return
                f.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True       # the browser cancelled or paused: it resumes with Range

        def _access_claims(self) -> dict | None:
            """D.L. AI: the Cloudflare Access login of this request, when Access is configured and the request came
            through the local tunnel connector (cloudflared connects from loopback)."""
            verifier = getattr(svc, "cf_access", None)
            if verifier is None or self.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                return None
            tok = cf_access.token_of(self.headers)
            return verifier.verify(tok) if tok else None

        def _given_key(self) -> bool:
            if not svc.api_key:
                return False
            auth = self.headers.get("Authorization", "")
            given = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("x-api-key", "")
            return key_matches(given, svc.api_key)

        def _authorized(self) -> bool:
            if not svc.api_key or self._given_key() or self._access_claims() is not None:
                return True
            self._json(401, {"error": {"type": "authentication_error", "message": "missing or wrong API key"}})
            return False

        def _session_events(self, name: str):
            """D.L. AI Code tab: the shared CLI session's live events (tools/dl_sessiond.py) as Server-Sent Events.
            The page reads it with fetch (EventSource cannot send the API key on the LAN)."""
            conn = socket.socket(socket.AF_UNIX)
            try:
                conn.connect(str(SESSIOND_SOCKET))
                conn.sendall((json.dumps({"op": "attach", "session": name}) + "\n").encode())
            except OSError as e:
                conn.close()
                self._json(503, {"error": {"message": f"the CLI session daemon is not running ({e}): "
                                                      "systemctl --user start dl-ai-sessiond"}})
                return
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            buf = b""
            try:
                while True:
                    ready, _, _ = select.select([conn], [], [], 15)
                    if not ready:
                        self.wfile.write(b": ping\n\n")         # keeps proxies (Cloudflare) from closing it
                        self.wfile.flush()
                        continue
                    data = conn.recv(65536)
                    if not data:
                        self.wfile.write(b"event: gone\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    if lines:
                        self.wfile.write(b"".join(b"data: " + ln + b"\n\n" for ln in lines if ln))
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                conn.close()

        def _device(self, origin: str) -> str:
            """Where a Code tab prompt was typed, for "play music" (the phone's or the PC's tools): the Ray app is
            the phone; a browser on this PC itself (localhost, not through the tunnel) is the PC; anything else
            (another computer, through the domain or the LAN) is "remote", and Ray asks where to play."""
            if origin.startswith("ray-android"):
                return "phone"
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            local = self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
            if local and host in ("localhost", "127.0.0.1", "::1") and not self.headers.get("Cf-Connecting-Ip"):
                return "pc"
            return "remote"

        def _session_op(self, msg: dict) -> dict:
            conn = socket.socket(socket.AF_UNIX)
            conn.settimeout(30)
            try:
                conn.connect(str(SESSIOND_SOCKET))
                conn.sendall((json.dumps(msg) + "\n").encode())
                return json.loads(conn.makefile("rb").readline() or b"{}")
            finally:
                conn.close()

        def do_GET(self):
            raw_path = self.path.split("?")[0]
            if raw_path == "/api/whoami":
                # D.L. AI: which credential this browser has - the web app hides the API key field behind Access
                claims = self._access_claims()
                if claims is not None:
                    self._json(200, {"auth": "cf-access", "email": claims.get("email", "")})
                elif not svc.api_key:
                    self._json(200, {"auth": "none"})
                else:
                    auth = self.headers.get("Authorization", "")
                    given = auth[7:].strip() if auth.lower().startswith("bearer ") else self.headers.get("x-api-key", "")
                    self._json(200, {"auth": "key" if given and key_matches(given, svc.api_key) else "required"})
                return
            path = raw_path.rstrip("/")
            if path in ("/favicon.ico", "/favicon.svg"):
                icon_file = ROOT / "serve" / "web" / ("favicon.ico" if path == "/favicon.ico" else "favicon.svg")
                if icon_file.is_file():
                    body = icon_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon" if path == "/favicon.ico" else "image/svg+xml")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._json(404, {"error": {"message": "not found"}})
                return
            if path.startswith("/fonts/"):
                # the web app's font (Outfit, OFL: serve/web/fonts); the page falls back to the system font
                name = path[len("/fonts/"):]
                f = ROOT / "serve" / "web" / "fonts" / name
                if "/" in name or "\\" in name or not name.endswith(".woff2") or not f.is_file():
                    self._json(404, {"error": {"message": "not found"}})
                    return
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/web/"):
                # the web app's own files (serve/web): styles, script, icon sprite - same origin, no CDN
                name = path[len("/web/"):]
                types = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                         ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
                         ".webmanifest": "application/manifest+json"}
                f = ROOT / "serve" / "web" / name
                ext = os.path.splitext(name)[1]
                if "/" in name or "\\" in name or ext not in types or not f.is_file():
                    self._json(404, {"error": {"message": "not found"}})
                    return
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", types[ext])
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/metrics/prometheus":
                if self._authorized():
                    body = svc.prometheus().encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                return
            if path == "/metrics":
                from serve import prometheus
                if prometheus.wants_prometheus(self.headers.get("Accept", ""), urlsplit(self.path).query):
                    if self._authorized():   # a scraper: the text format, vLLM's names (serve/prometheus.py)
                        body = prometheus.render(svc.metrics(), svc.latencies.snapshot()).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", prometheus.CONTENT_TYPE)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    return
                if self._authorized():
                    # the last 12 requests; `?requests=all` every one kept (the Monitor's "Show all", issue #35)
                    self._json(200, svc.metrics(all_requests="requests=all" in self.path))
                return
            if path == "/api/requests" and svc.api_monitor:
                if self._authorized():
                    request_id = parse_qs(urlsplit(self.path).query).get("id", [None])[0]
                    records = svc.request_records(request_id)
                    self._json(404 if records is None else 200,
                               {"error": {"message": "request no longer retained"}} if records is None else
                               records if request_id else {"requests": records, "retention": 100, "persistent": False,
                                                          "loaded": svc.loaded(), "auto_load": hasattr(svc.engine, "restart")})
                return
            if path == "/settings":
                if self._authorized():
                    self._json(200, {"shared": bool(svc.shared), "defaults": svc.shared})
                return
            if path == "/config":                            # #564: the Settings view's keys of the run config
                if self._authorized():
                    self._config_get()
                return
            if path == "/mcp":
                # the MCP servers, their state and tools (the web app's switch and Monitor card)
                if self._authorized():
                    self._json(200, svc.mcp.status() if svc.mcp else {"servers": [], "tools": 0})
                return
            if path == "/v1/audio/speech/status":
                if self._authorized():
                    from serve.speech import get_tts_status
                    self._json(200, get_tts_status())
                return
            if path in ("/v1/audio/transcriptions", "/v1/audio/status", "/audio/status"):
                if self._authorized():
                    from serve.transcribe import get_stt_status
                    self._json(200, get_stt_status())
                return
            if path in ("/available_models", "/api/models"):
                if self._authorized():
                    self._json(200, {"models": svc.available_models(), "current": svc.model})
                return
            if path in ("/api/code/session/events", "/v1/ray/history", "/v1/ray/session"):
                if self._authorized():
                    session_name = (parse_qs(urlsplit(self.path).query).get("session") or ["dl-ai-code"])[0]
                    if path == "/api/code/session/events":
                        self._session_events(session_name)
                    else:
                        self._ray_history(session_name)
                return
            if path == "/api/phone/status":
                if not self._authorized():                   # the key always (see the POST side)
                    return
                self._json(200, PHONE_BRIDGE.get_status())
                return
            if path in ("/api/phone/tool/pending", PHONE_PENDING_PATH):
                if not self._authorized():                   # the key always (see the POST side)
                    return
                PHONE_BRIDGE.report_heartbeat()
                call = PHONE_BRIDGE.pop_pending_call()
                # Check if desktop clipboard has newer content from KDE Klipper
                try:
                    res = subprocess.run(
                        ["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardContents"],
                        capture_output=True, text=True, timeout=0.8
                    )
                    if res.returncode == 0 and res.stdout:
                        ktxt = res.stdout.strip()
                        khash = hashlib.sha256(ktxt.encode("utf-8")).hexdigest()
                        with PHONE_BRIDGE.lock:
                            if ktxt and khash != PHONE_BRIDGE.clipboard.get("hash"):
                                PHONE_BRIDGE.clipboard = {
                                    "text": ktxt,
                                    "hash": khash,
                                    "source": "desktop",
                                    "updated_ms": int(time.time() * 1000)
                                }
                except Exception:
                    pass
                with PHONE_BRIDGE.lock:
                    clip = dict(PHONE_BRIDGE.clipboard) if PHONE_BRIDGE.clipboard.get("text") else None
                resp = {"pending": call}
                if clip:
                    resp["clipboard"] = clip
                self._json(200, resp)
                return
            if path in ("/api/phone/sensors/stream", PHONE_SENSORS_STREAM_PATH):
                if not self._authorized():
                    return
                with PHONE_BRIDGE.lock:
                    data = dict(PHONE_BRIDGE.sensor_stream)
                if not data:
                    stream_file = WORKSPACE_DIR / "phone-photos" / "_ray_sensor_stream.json"
                    if stream_file.is_file():
                        try:
                            data = json.loads(stream_file.read_text(encoding="utf-8"))
                        except Exception:
                            data = {}
                self._json(200, data)
                return
            if path in ("/api/phone/clipboard", PHONE_CLIPBOARD_PATH):
                if not self._authorized():
                    return
                with PHONE_BRIDGE.lock:
                    clip = dict(PHONE_BRIDGE.clipboard)
                self._json(200, clip)
                return
            if path == PHONE_DOWNLOAD_PATH:
                if not self._authorized():
                    return
                qs = parse_qs(urlsplit(self.path).query)
                target = safe_workspace_path((qs.get("file") or qs.get("path") or [""])[0])
                if not target or not target.is_file():
                    self._json(404, {"error": {"message": "file not found in workspace"}})
                    return
                self._send_file_download(target)
                return
            if path in ("/api/workspace/files", "/api/workspace"):
                if not self._authorized():
                    return
                try:
                    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
                    items = []
                    for p in sorted(WORKSPACE_DIR.rglob("*")):
                        if any(part.startswith(".") for part in p.parts):
                            continue
                        try:
                            resolved = p.resolve()
                            if not resolved.is_relative_to(WORKSPACE_DIR):
                                continue
                            stat = p.stat()
                        except (OSError, ValueError):
                            continue
                        rel = str(p.relative_to(WORKSPACE_DIR)).replace("\\", "/")
                        is_dir = p.is_dir()
                        ext = p.suffix.lower()
                        kind = "dir" if is_dir else ("image" if ext in WORKSPACE_IMAGE_EXTS else ("text" if ext in WORKSPACE_TEXT_EXTS else "other"))
                        items.append({
                            "name": p.name,
                            "path": rel,
                            "is_dir": is_dir,
                            "size": 0 if is_dir else stat.st_size,
                            "mtime": int(stat.st_mtime),
                            "kind": kind
                        })
                    self._json(200, {"workspace": str(WORKSPACE_DIR), "files": items})
                except Exception as e:
                    self._json(500, {"error": {"message": f"failed to list workspace: {e}"}})
                return
            if path == "/api/workspace/download":
                # D.L. AI: streamed from disk (a 263 MB zip was read whole into memory and the page then held it as a
                # Blob, which mobile browsers gave up on), resumable with Range, any file name.  A browser download
                # is a plain navigation: it is authorised by the Cloudflare Access login, or on the LAN by a
                # single-use ticket from POST /api/workspace/download-ticket.
                qs = parse_qs(urlsplit(self.path).query)
                ticket = (qs.get("ticket") or [""])[0]
                if ticket:
                    target = take_download_ticket(ticket)
                    if target is None:
                        self._json(403, {"error": {"message": "download link expired: start the download again"}})
                        return
                else:
                    if not self._authorized():
                        return
                    target = safe_workspace_path((qs.get("file") or qs.get("path") or [""])[0])
                if not target or not target.is_file():
                    self._json(404, {"error": {"message": "file not found in workspace"}})
                    return
                self._send_file_download(target)
                return
            if path == "/api/workspace/file":
                if not self._authorized():
                    return
                qs = parse_qs(urlsplit(self.path).query)
                target_rel = (qs.get("file") or qs.get("path") or [""])[0]
                target = safe_workspace_path(target_rel)
                if not target or not target.is_file():
                    self._json(404, {"error": {"message": "file not found in workspace"}})
                    return
                ext = target.suffix.lower()
                try:
                    if ext in WORKSPACE_IMAGE_EXTS:
                        mime, _ = mimetypes.guess_type(target.name)
                        mime = mime or "image/png"
                        b64 = base64.b64encode(target.read_bytes()).decode("ascii")
                        self._json(200, {
                            "name": target.name,
                            "path": str(target.relative_to(WORKSPACE_DIR)),
                            "kind": "image",
                            "url": f"data:{mime};base64,{b64}",
                            "size": target.stat().st_size
                        })
                    else:
                        text = target.read_text(encoding="utf-8", errors="replace")
                        self._json(200, {
                            "name": target.name,
                            "path": str(target.relative_to(WORKSPACE_DIR)),
                            "kind": "file",
                            "text": text,
                            "size": target.stat().st_size
                        })
                except Exception as e:
                    self._json(500, {"error": {"message": f"failed to read file: {e}"}})
                return
            if path == "" or (path == "/api-monitor" and svc.api_monitor):
                body = (ROOT / "serve" / "web" / ("monitor.html" if path else "index.html")).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                # D.L. AI: no frames in the page (the Android app's bridge is injected into every frame, and the page
                # embeds none), and no other site may frame it (clickjacking)
                self.send_header("Content-Security-Policy", "frame-src 'none'; frame-ancestors 'self'")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/health", "/api/health"):
                self._json(200, {"status": "ok", "max_context": svc.reported_ctx(), "model": svc.model,
                                 "images": svc.vision is not None, "api_key": bool(svc.api_key),
                                 "image_generation": svc.images is not None,
                                 "loaded": svc.loaded(), "service": "strata",
                                 "degraded": getattr(svc.engine, "degraded", None) if svc.loaded() else None})
            elif path.startswith("/v1/images/files/"):
                # response_format url: the name (32 random hex digits) is the access, as an OpenAI image URL is
                f = svc.images.file(path[len("/v1/images/files/"):]) if svc.images is not None else None
                if f is None:
                    self._json(404, {"error": {"message": "not found (the server keeps the newest images only)"}})
                    return
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "private, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/status":
                if not self._authorized():                  # #212: it shows the end of the last answer
                    return
                with svc.status_lock:
                    s = dict(svc.status)
                now = time.time()
                if s.get("busy"):
                    s["elapsed_s"] = round(now - s["started"], 1)
                    if s.get("first_token"):
                        s["tokens_per_s"] = round(svc._tok_s(), 1)
                        s["tokens_per_s_mean"] = round(svc._tok_s_mean(), 1)
                for k in ("started", "first_token"):
                    s.pop(k, None)
                self._json(200, s)
            elif path in ("/v1/models", "/models"):
                if self._authorized():
                    loaded = svc.loaded()
                    model = {"id": svc.model, "object": "model", "status": {"value": "loaded"},
                             "meta": {"n_ctx": svc.reported_ctx()},
                             "architecture": {"input_modalities": ["text", "image"] if svc.vision is not None else ["text"],
                                              "output_modalities": ["text"]}}
                    if not loaded and (svc.idle_unload_s or getattr(svc.engine, "unloaded", False)):
                        model["status"] = {"value": "unloaded"}   # like llama-server's router: listed, loads on use
                        loaded = True
                    if svc.aliases:                       # #297: the aliases, and each one listed under its own id
                        model["aliases"] = list(svc.aliases)
                    data = [model, *({**model, "id": x, "alias_of": svc.model} for x in svc.aliases)]
                    data = data if loaded else []
                    if svc.images is not None:            # the image model: POST /v1/images/generations
                        data.append({"id": svc.images.model, "object": "model", "status": {"value": "loaded"},
                                     "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}})
                    self._json(200, {"object": "list", "data": data})
            elif path == "/props":
                if self._authorized():
                    self._props()
            elif path == "/slots":
                if self._authorized():
                    loaded = not hasattr(svc.engine, "alive") or svc.engine.alive()
                    with svc.status_lock:
                        busy = bool(svc.status.get("busy"))
                        # llama.cpp's name for what the slot's context holds: the running request's prompt size,
                        # kept after it ends (the conversation cache carries it on).  A front-end's context meter
                        # divides it by n_ctx; without the key it reads 0 % against Strata forever (#562).
                        in_use = int(svc.status.get("prompt_tokens") or 0)
                    if getattr(svc.engine, "batch", 0) and hasattr(svc.engine, "slots_view"):
                        # --batch: one entry per slot (the same view /metrics has), not one for the whole engine
                        n_ctx = svc.reported_ctx()
                        slots = [{"id": s["slot"], "n_ctx": n_ctx, "is_processing": s["state"] != "idle",
                                  "n_prompt_tokens": int(s.get("prompt_tokens") or s.get("held_tokens") or 0)}
                                 for s in svc.engine.slots_view()]
                    else:
                        slots = [{"id": 0, "n_ctx": svc.reported_ctx(), "is_processing": busy,
                                  "n_prompt_tokens": in_use}]
                    self._json(200, slots if loaded else [])
            elif path == "/v1/status":
                if self._authorized():
                    self._json(200, svc.v1_status())
            else:
                self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):
            try:
                self._post()
            except BadBody as e:                              # #893: a malformed or oversized chunked body
                self._json(e.status, {"error": {"type": "invalid_request_error", "message": str(e)}})

        def _post(self):
            if not self._authorized():
                return
            path = self.path.split("?")[0].rstrip("/")   # issue #55: Claude Code posts /v1/messages?beta=true
            if path.startswith("/v1/") and self._foreign_page():
                return
            if path == "/settings":
                self._settings()
                return
            if path == "/config":
                self._config_post()
                return
            if path in ("/unload", "/load", "/restart") and not self._control_body():
                return
            # JSON from Strata's own page only, as /settings: else a plain form POST from any site unloads the model
            if path in ("/unload", "/load", "/restart") and not self._own_page("the model can be loaded, unloaded or restarted"):
                return
            # the same for the slot files: else any site could overwrite a saved conversation or replace the live one
            if path.startswith("/slots/") and not self._own_page("conversations can be saved or restored"):
                return
            if path == "/unload":                            # give the GPU back now (between requests)
                try:
                    wait_s = unload_wait(parse_qs(urlsplit(self.path).query).get("wait", [None])[0],
                                         svc.UNLOAD_WAIT_S)
                    r = svc.unload_waiting(wait_s) if wait_s else svc.unload()
                except EngineStuck as e:
                    self._json(503, {"error": {"type": "server_error", "message": str(e)}})
                    return
                self._json(409 if r == "busy" else 200, {"status": r})
                return
            if path == "/load":                              # load now, e.g. ahead of a request
                try:
                    svc.load()
                    self._json(200, {"status": "loaded"})
                except GpuBusy as e:
                    ra = getattr(e, "retry_after", None)
                    self._json(503, {"error": {"type": "server_error", "message": str(e)}},
                               headers={"Retry-After": int(ra)} if ra else None)
                return
            if path == "/restart":
                try:
                    r = svc.force_restart()
                except Exception as e:
                    self._json(500, {"error": {"type": "server_error", "message": str(e)}})
                    return
                self._json(200, {"status": r})
                return
            if path == "/switch_model":
                if not self._own_page("the model can be switched"):
                    return
                try:
                    req = json.loads(self._body() or b"{}")
                except ValueError:
                    req = {}
                target = req.get("model") or req.get("id")
                if not target:
                    self._json(400, {"error": {"message": "missing model identifier"}})
                    return
                try:
                    res = svc.switch_model(target)
                    self._json(200, res)
                except Exception as e:
                    self._json(500, {"error": {"type": "server_error", "message": str(e)}})
                return
            if path == "/api/workspace/download-ticket":
                try:
                    req = json.loads(self._body() or b"{}")
                except ValueError:
                    req = {}
                target = safe_workspace_path(str(req.get("file") or req.get("path") or ""))
                if not target or not target.is_file():
                    self._json(404, {"error": {"message": "file not found in workspace"}})
                    return
                self._json(200, {"url": f"api/workspace/download?ticket={new_download_ticket(target)}"})
                return
            if path in ("/api/workspace/upload", PHONE_UPLOAD_PATH):
                if self._foreign_origin():
                    self._json(403, {"error": {"message": "workspace files can only be uploaded from Strata's own page (or a trusted origin)"}})
                    return
                qs = parse_qs(urlsplit(self.path).query)
                filename = (qs.get("file") or qs.get("filename") or [""])[0]
                if not filename:
                    filename = self.headers.get("X-Filename", "")
                ctype = self.headers.get("Content-Type", "")
                data = None
                if ctype.startswith("application/json"):
                    try:
                        req = json.loads(self._body() or b"{}")
                    except Exception:
                        self._json(400, {"error": {"message": "invalid JSON"}})
                        return
                    filename = filename or req.get("filename") or req.get("name")
                    if not filename:
                        self._json(400, {"error": {"message": "missing filename"}})
                        return
                    if "content_base64" in req:
                        try:
                            data = base64.b64decode(req["content_base64"])
                        except Exception:
                            self._json(400, {"error": {"message": "invalid base64"}})
                            return
                    elif "text" in req:
                        data = req["text"].encode("utf-8")
                    elif "content" in req:
                        val = req["content"]
                        data = val.encode("utf-8") if isinstance(val, str) else bytes(val)
                    else:
                        self._json(400, {"error": {"message": "missing file content"}})
                        return
                else:
                    if not filename:
                        self._json(400, {"error": {"message": "missing filename in query or X-Filename header"}})
                        return
                    data = self._body()
                if path == PHONE_UPLOAD_PATH and not is_phone_photo(filename):
                    self._json(403, {"error": {"message": "this path only takes files under phone-photos/"}})
                    return
                target = safe_workspace_path(filename)
                if not target:
                    self._json(400, {"error": {"message": "invalid or unsafe filename"}})
                    return
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    self._json(200, {"status": "ok", "filename": target.name, "path": str(target.relative_to(WORKSPACE_DIR)), "size": len(data)})
                except Exception as e:
                    self._json(500, {"error": {"message": f"failed to save file: {e}"}})
                return
            if path in ("/api/workspace/delete", "/api/workspace/remove"):
                if not self._own_page("workspace files can be deleted"):
                    return
                qs = parse_qs(urlsplit(self.path).query)
                filename = (qs.get("file") or qs.get("path") or [""])[0]
                if not filename:
                    try:
                        req = json.loads(self._body() or b"{}")
                        filename = req.get("file") or req.get("path") or req.get("name")
                    except Exception:
                        pass
                target = safe_workspace_path(filename)
                if not target or not target.exists():
                    self._json(404, {"error": {"message": "file not found"}})
                    return
                try:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                    self._json(200, {"status": "ok", "deleted": filename})
                except Exception as e:
                    self._json(500, {"error": {"message": f"failed to delete: {e}"}})
                return
            if path == "/api/code/session":
                if not self._own_page("the CLI session can be driven"):
                    return
                try:
                    req = json.loads(self._body() or b"{}")
                except ValueError:
                    req = {}
                op = req.get("op")
                if op not in ("input", "approve", "deny", "interrupt", "export", "state", "archives", "archive_rename",
                              "archive_delete", "queue_delete", "queue_remove"):
                    self._json(400, {"error": {"message": "op must be input, approve, deny, interrupt, export, state, "
                                                          "archives, archive_rename, archive_delete or queue_delete"}})
                    return
                msg = {k: req[k] for k in ("op", "session", "text", "id", "origin", "effort", "voice", "query", "title")
                       if k in req}
                if op == "input":
                    msg["device"] = self._device(str(req.get("origin") or ""))
                try:
                    self._json(200, self._session_op(msg))
                except OSError as e:
                    self._json(503, {"error": {"message": f"the CLI session daemon is not running ({e})"}})
                return
            if path in ("/api/phone/status", "/api/phone/tool/call", "/api/phone/tool/result", PHONE_RESULT_PATH,
                        "/api/phone/sensors/stream", PHONE_SENSORS_STREAM_PATH,
                        "/api/phone/clipboard", PHONE_CLIPBOARD_PATH):
                # all three need the key (the web app and the Android app send it): "authorized or not foreign" let a
                # client without a key and without an Origin header through, after _authorized() had already sent its
                # 401, so anyone on the LAN could fake the phone's heartbeat or a tool's result
                if not self._authorized():
                    return
                # a web page elsewhere must not set the desktop clipboard or fake the phone: without an api_key (or
                # behind Cloudflare Access, whose cookie the browser sends along) a cross-site text/plain POST was let
                # in.  The web app posts from its own origin and the Android app sends no Origin.
                if self._foreign_origin():
                    self._json(403, {"error": {"message": "the phone relay only from Strata's own page (or an origin "
                                                          "in the config's trusted_origins)"}})
                    return
                if path == "/api/phone/status":
                    PHONE_BRIDGE.report_heartbeat()
                    self._json(200, {"status": "ok"})
                    return
                if path in ("/api/phone/sensors/stream", PHONE_SENSORS_STREAM_PATH):
                    PHONE_BRIDGE.report_heartbeat()
                    try:
                        req = json.loads(self._body() or b"{}")
                    except ValueError:
                        req = {}
                    if isinstance(req, dict):
                        with PHONE_BRIDGE.lock:
                            PHONE_BRIDGE.sensor_stream = req
                        try:
                            sf = WORKSPACE_DIR / "phone-photos" / "_ray_sensor_stream.json"
                            sf.parent.mkdir(parents=True, exist_ok=True)
                            sf.write_text(json.dumps(req), encoding="utf-8")
                        except Exception:
                            pass
                    self._json(200, {"status": "ok"})
                    return
                if path in ("/api/phone/clipboard", PHONE_CLIPBOARD_PATH):
                    PHONE_BRIDGE.report_heartbeat()
                    try:
                        req = json.loads(self._body() or b"{}")
                    except ValueError:
                        req = {}
                    if isinstance(req, dict) and req.get("text"):
                        text_val = str(req.get("text", ""))
                        with PHONE_BRIDGE.lock:
                            PHONE_BRIDGE.clipboard = {
                                "text": text_val,
                                "hash": str(req.get("hash", "")),
                                "source": str(req.get("source", "phone")),
                                "updated_ms": int(req["updated_ms"]) if isinstance(req.get("updated_ms"), (int, float))
                                              else int(time.time() * 1000)
                            }
                        if req.get("source") != "desktop" and text_val:
                            def _sync_to_klipper(t: str):
                                try:
                                    subprocess.run(
                                        ["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", t],
                                        capture_output=True, timeout=2.0
                                    )
                                except Exception:
                                    pass
                            threading.Thread(target=_sync_to_klipper, args=(text_val,), daemon=True).start()
                    self._json(200, {"status": "ok"})
                    return
                if path == "/api/phone/tool/call":
                    try:
                        req = json.loads(self._body() or b"{}")
                    except ValueError:
                        req = {}
                    tool_name = req.get("tool")
                    tool_args = req.get("args") or {}
                    if not tool_name:
                        self._json(400, {"error": {"message": "missing tool name"}})
                        return
                    dur_s = 0.0
                    if isinstance(tool_args, dict):
                        try:
                            dur_s = float(tool_args.get("duration_sec") or 0.0)
                        except (TypeError, ValueError):
                            dur_s = 0.0
                    call_timeout = max(20.0, min(135.0, dur_s + 12.0))
                    res = PHONE_BRIDGE.enqueue_call(tool_name, tool_args, timeout=call_timeout)
                    if res is not None:
                        self._json(200, {"result": res})
                    else:
                        self._json(504, {"error": {"message": "phone tool call timed out or phone is offline"}})
                    return
                if path in ("/api/phone/tool/result", PHONE_RESULT_PATH):
                    try:
                        req = json.loads(self._body() or b"{}")
                    except ValueError:
                        req = {}
                    cid = req.get("id")
                    cres = req.get("result", "")
                    if cid:
                        PHONE_BRIDGE.post_result(cid, cres)
                    self._json(200, {"status": "ok"})
                    return
            if path in ("/v1/audio/transcriptions", "/audio/transcriptions"):
                self._audio_transcriptions()
                return
            if path == "/v1/audio/speech":
                self._audio_speech()
                return
            try:
                req = json.loads(self._body() or b"{}")
                if not isinstance(req, dict):
                    raise ValueError("send a JSON object")
                if path.startswith("/v1/responses/"):        # retrieve/delete/cancel/compact: nothing is stored
                    self._json(404, responses_error_body("this server keeps no responses (stateless); send the "
                                                         "whole conversation to POST /v1/responses", code="not_found"))
                    return
                if path in ("/v1/load", "/v1/unload", "/v1/restart"):
                    if not self._own_page("the model can be loaded, unloaded or restarted"):
                        return
                    if path == "/v1/restart":
                        r = svc.force_restart()
                        self._json(200, {"status": r})
                        return
                    if req.get("model") not in (None, svc.model):
                        self._json(404, {"error": {"message": "model not found"}})
                        return
                    if path == "/v1/unload":
                        wait_s = unload_wait(parse_qs(urlsplit(self.path).query).get("wait", [None])[0],
                                             svc.UNLOAD_WAIT_S)
                        result = svc.unload_waiting(wait_s) if wait_s else svc.unload()
                        if result == "busy":
                            raise ModelBusy("a request is running or queued")
                    else:
                        if not svc.fifo.acquire(blocking=False):
                            raise ModelBusy("a request is running or queued")
                        try:
                            with svc.status_lock:
                                if svc.status.get("busy") or svc.status.get("queued"):
                                    raise ModelBusy("a request is running or queued")
                            svc.ensure_loaded()
                            svc.last_request_at = time.time()
                        finally:
                            svc.fifo.release()
                        result = "loaded"
                    self._json(200, {"status": result, **svc.v1_status()})
                    return
                if path == "/v1/vram":                       # #533: give VRAM back to other programs, or take it
                    if not self._own_page("the VRAM reserve can be changed"):
                        return
                    r = req.get("reserve_mib")
                    if r is not None and (isinstance(r, bool) or not isinstance(r, int) or r < 0):
                        raise ValueError("reserve_mib: a whole number of MiB (0 or more), or null for the start's")
                    try:
                        self._json(200, svc.vram(r))
                    except EngineDied as e:
                        self._json(503, {"error": {"type": "server_error", "message": str(e)}})
                    return
                if path in ("/v1/chat/completions", "/v1/completions", "/v1/messages", "/v1/responses", "/v1/ray/chat"):
                    self.record = svc.begin_request(path, req)
                if path == "/v1/responses":
                    self._responses(req)
                elif path.startswith("/slots/"):
                    query = parse_qs(self.path.partition("?")[2])
                    try:
                        code, body = svc.slot_action(path[len("/slots/"):], (query.get("action") or [""])[0],
                                                     req.get("filename"))
                    except EngineDied as e:                  # EngineSilent included: the engine was ended
                        code, body = 500, {"error": {"code": 500, "message": str(e) + "; the next request starts "
                                                     "the engine again", "type": "server_error"}}
                    self._json(code, body)
                elif path == "/v1/chat/completions":
                    self._openai(req)
                elif path == "/v1/ray/chat":
                    self._ray_chat(req)
                elif path == "/v1/completions":
                    self._completions(req)
                elif path == "/v1/messages":
                    self._anthropic(req)
                elif path == "/v1/messages/count_tokens":
                    self._count_tokens(req)
                elif path == "/v1/images/generations":
                    self._images(req)
                else:
                    self._json(404, {"error": {"message": "not found"}})
            except EngineNonFinite as e:                    # #879, twice: not the request's fault
                print(f"[strata] 503: {e}", flush=True)
                self._json(503, responses_error_body(str(e), "server_error") if path == "/v1/responses"
                           else {"error": {"type": "server_error", "message": str(e)}})
            except ValueError as e:
                print(f"[strata] 400 invalid request: {e}", flush=True)
                if path in ("/v1/responses", "/v1/completions"):
                    self._json(400, responses_error_body(str(e)))
                else:
                    self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
            except ModelBusy as e:
                self._json(409, {"error": {"type": "model_busy", "message": str(e)}})
            except StructuredOutputError as e:
                self._json(502, {"error": {"type": "structured_output_failed", "code": "structured_output_failed",
                                          "message": str(e)}})
            except (GpuBusy, EngineStarting) as e:
                ra = getattr(e, "retry_after", None)       # #1997 / #1994: a refusal that is worth retrying
                self._json(503, {"error": {"type": "server_error", "message": str(e)}},
                           headers={"Retry-After": int(ra)} if ra else None)
            except (TypeError, KeyError, AttributeError, IndexError, UnicodeError) as e:
                # a body that is JSON but the wrong shape ("messages": 5, a content part that is a number): a 400 that
                # says so, with the traceback in the log, instead of a dropped connection - unless the answer began
                if getattr(self, "answer_started", False):
                    raise
                import traceback
                print(f"[strata] 400 malformed request ({type(e).__name__}: {e}):\n" + traceback.format_exc(),
                      flush=True)
                body = {"error": {"type": "invalid_request_error",
                                  "message": f"the request is malformed ({type(e).__name__}: {e})"}}
                self._json(400, responses_error_body(body["error"]["message"]) if path == "/v1/responses" else body)
            except EngineDied as e:                          # before the answer started (not streamed)
                body = {"error": {"type": "server_error", "message": died_note(e)}}
                if getattr(self, "answer_started", False):
                    self._note(error=body["error"])
                    self.wfile.write(b"data: " + json.dumps(body).encode() + b"\n\ndata: [DONE]\n\n")
                else:
                    self._json(503, body)
            except EngineStuck as e:                         # an unload or restart that could not end the engine
                body = {"error": {"type": "server_error", "message": str(e)}}
                if getattr(self, "answer_started", False):
                    self._note(error=body["error"])
                    self.wfile.write(b"data: " + json.dumps(body).encode() + b"\n\ndata: [DONE]\n\n")
                else:
                    self._json(503, body)

            except ClientGone:                               # #1999: the client left while the request was prepared
                self._note(outcome="disconnected")
            except OSError:
                self._note(outcome="disconnected")
                raise                                        # as before #332: the server's own handling
            finally:
                svc.drop_embeddings()                        # the images' file of a request that never got to run()
                if self.watch_done is not None:
                    self.watch_done.set()
                record = self.record
                if record is not None:
                    with svc.status_lock:
                        record["wallclock_s"] = round(time.perf_counter() - record["_clock"], 3)
                        record["finished_at"] = time.time()
                        record["state"] = "error" if record.get("error") else record.get("outcome", "completed")
                    svc.request_trace.record = None

        def _images(self, req):
            """POST /v1/images/generations (serve/images.py): one sd-cli job in the GPU's turn."""
            gen = svc.images
            if gen is None:
                self._json(404, {"error": {"type": "invalid_request_error", "code": "images_not_set_up",
                                           "message": "image generation is not set up on this server (run setup "
                                                      "with --images qwen-image)"}})
                return
            job = images_api.parse_request(req, gen.cfg)        # ImageRequestError (a ValueError): 400
            svc.last_request_at = time.time()
            cancel = threading.Event()
            self._watch_client(cancel)
            print(f"[strata] image: {job['width']}x{job['height']}, n={job['n']}, {job['steps']} steps, "
                  f"seed {job['seed']}", flush=True)
            try:
                with images_api.gpu_turn(svc, gen, job, cancel) as policy:
                    images, figures = gen.run(job, cancel)
            except images_api.ImageJobFailed as e:
                self._json(500, {"error": {"type": "server_error", "code": "image_generation_failed",
                                           "message": str(e)}})
                return
            figures["gpu_policy"] = policy
            print(f"[strata] image done in {figures['seconds']:.1f} s ({policy})", flush=True)
            host = self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
            scheme = "https" if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else "http"
            self._json(200, gen.response(images, job, figures, f"{scheme}://{host}"))

        def _audio_transcriptions(self):
            """POST /v1/audio/transcriptions (serve/transcribe.py): local Whisper audio transcription."""
            if not self._authorized():
                return
            content_type = self.headers.get("Content-Type", "")
            try:
                body = self._body()
            except Exception as e:
                self._json(400, {"error": {"message": f"could not read audio body: {e}"}})
                return

            if not body:
                self._json(400, {"error": {"message": "missing audio payload"}})
                return

            audio_bytes = b""
            language = None
            prompt = None

            # 1. Multipart Form Data (OpenAI standard)
            if "multipart/form-data" in content_type:
                from email.parser import BytesParser
                from email.policy import default
                try:
                    msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        if name == "file":
                            audio_bytes = part.get_payload(decode=True) or b""
                        elif name == "language":
                            language = (part.get_payload(decode=True) or b"").decode("utf-8", errors="ignore").strip()
                        elif name == "prompt":
                            prompt = (part.get_payload(decode=True) or b"").decode("utf-8", errors="ignore").strip()
                except Exception as e:
                    self._json(400, {"error": {"message": f"malformed multipart payload: {e}"}})
                    return

            # 2. JSON with base64 audio
            elif "application/json" in content_type:
                import base64
                try:
                    data = json.loads(body.decode("utf-8", errors="ignore"))
                    raw_b64 = data.get("file") or data.get("audio") or ""
                    if "," in raw_b64:
                        raw_b64 = raw_b64.split(",", 1)[1]
                    audio_bytes = base64.b64decode(raw_b64)
                    language = data.get("language")
                    prompt = data.get("prompt")
                except Exception as e:
                    self._json(400, {"error": {"message": f"malformed json payload: {e}"}})
                    return

            # 3. Direct binary audio payload
            else:
                audio_bytes = body
                query = parse_qs(urlsplit(self.path).query)
                language = query.get("language", [None])[0]

            if not audio_bytes:
                self._json(400, {"error": {"message": "no audio data found in request"}})
                return

            from serve.transcribe import transcribe_audio, TranscriptionError
            try:
                t0 = time.time()
                text = transcribe_audio(audio_bytes, language=language, prompt=prompt)
                dur = time.time() - t0
                print(f"[strata] stt: transcribed {len(audio_bytes)} bytes in {dur:.2f}s -> {repr(text[:60])}", flush=True)
                self._json(200, {"text": text})
            except TranscriptionError as e:
                self._json(500, {"error": {"type": "server_error", "message": str(e)}})
            except Exception as e:
                self._json(500, {"error": {"type": "server_error", "message": f"transcription failed: {e}"}})

        def _audio_speech(self):
            """POST /v1/audio/speech (serve/speech.py): local Piper speech, OpenAI-style {"input", "voice", "speed",
            "response_format"}: "wav" (the default) or "opus" (Ogg Opus, needs ffmpeg; the phone on mobile data).  Ray's
            voice and talking face in the web app use it."""
            from serve.speech import SpeechError, synthesize, synthesize_opus
            try:
                req = json.loads(self._body() or b"{}")
                if not isinstance(req, dict):
                    raise ValueError
            except ValueError:
                self._json(400, {"error": {"type": "invalid_request_error", "message": "body must be a JSON object"}})
                return
            fmt = req.get("response_format") or "wav"
            if fmt not in ("wav", "opus"):
                self._json(400, {"error": {"type": "invalid_request_error",
                                           "message": "response_format must be wav or opus"}})
                return
            voice = req.get("voice")
            if voice in ("alloy", "nova", "shimmer", "echo", "fable", "onyx", "ray", "default"):
                voice = None                                  # OpenAI's voice names: Ray's own voice
            try:
                t0 = time.time()
                make = synthesize_opus if fmt == "opus" else synthesize
                audio = make(str(req.get("input") or ""), voice=voice, speed=req.get("speed") or 1.0)
            except SpeechError as e:
                self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            print(f"[strata] tts: {len(str(req.get('input') or ''))} chars in {time.time() - t0:.2f}s, "
                  f"{len(audio) // 1024} KB" + (" opus" if fmt == "opus" else ""), flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "audio/ogg" if fmt == "opus" else "audio/wav")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)

        def _props(self):
            model = parse_qs(urlsplit(self.path).query).get("model", [svc.model])[0]
            if model not in svc.model_names():
                self._json(404, {"error": {"message": "model not found"}})
                return
            if not svc.loaded() and not getattr(svc.engine, "unloaded", False):
                self._json(503, {"error": {"message": "the engine is not running"}})
                return
            defaults = {**svc.sampling_defaults, **svc.shared}
            names = {"repetition_penalty": "repeat_penalty", "penalty_last_n": "repeat_last_n"}
            params = {names.get(k, k): v for k, v in defaults.items()
                      if k in ("temperature", "top_p", "top_k", "min_p", "seed", "repetition_penalty",
                               "presence_penalty", "frequency_penalty", "penalty_last_n")}
            params["n_predict"] = svc.shared.get("max_tokens", -1)
            props = {"default_generation_settings": {"n_ctx": svc.reported_ctx(), "params": params},
                     "total_slots": max(1, int(getattr(svc.engine, "batch", 0) or 0)),   # #1004: the batch slots
                     "model_alias": svc.model, "chat_template": svc.template.source,
                     "chat_template_caps": svc.template.caps,
                     "modalities": {"vision": svc.vision is not None}, "models_autoload": hasattr(svc.engine, "restart"),
                     "is_sleeping": not svc.loaded()}
            if getattr(svc.engine, "model_path", None):
                props["model_path"] = svc.engine.model_path
            version = getattr(svc.engine, "info", {}).get("version")
            if version:
                props["build_info"] = "Strata " + str(version)
            self._json(200, props)

        def _control_body(self) -> bool:
            """Consume the unused control body before replying/closing (Windows otherwise sends a TCP reset)."""
            if self._chunked():
                self.body_read = True
                try:
                    self.connection.settimeout(2.0)
                    self._read_chunked(65536, keep=False)
                except BadBody as e:
                    self._json(e.status, {"error": {"message": f"control request: {e}"}})
                    return False
                except OSError:
                    self._json(400, {"error": {"message": "incomplete control request body"}})
                    return False
                return True
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": {"message": "invalid Content-Length"}})
                return False
            if not 0 <= length <= 65536:
                self._json(413, {"error": {"message": "control request body is limited to 64 KiB"}})
                return False
            timeout = self.connection.gettimeout()
            try:
                self.connection.settimeout(2.0)
                complete = len(self.rfile.read(length)) == length
            except OSError:
                complete = False
            finally:
                self.connection.settimeout(timeout)
                self.body_read = True                    # nothing left for the drain to wait for (#594)
            if not complete:
                self._json(400, {"error": {"message": "incomplete control request body"}})
            return complete

        def _own_page(self, what) -> bool:
            """Only JSON (a form or a "simple" cross-site request can't send it without a CORS preflight, which this
            server never grants) and no foreign Origin: a web page elsewhere must not change settings or run tools."""
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(415, {"error": {"message": "send application/json"}})
                return False
            if self._foreign_origin():
                self._json(403, {"error": {"message": f"{what} only from Strata's own page (or an origin in the "
                                                      f"config's trusted_origins)"}})
                return False
            return True

        def _config_get(self):
            if not svc.config_path:
                self._json(404, {"error": {"message": "this server was started without a run config"}})
                return
            try:
                cfg = runconfig.load(svc.config_path)
            except (OSError, ValueError) as e:
                self._json(500, {"error": {"type": "server_error", "message": f"the run config cannot be read: {e}"}})
                return
            self._json(200, runconfig.view(cfg, svc.config_path))

        def _config_post(self):
            """#564: change a few documented keys of the run config - JSON from Strata's own page only, as
            /settings (the key is checked before); every other key of the file stays as it is."""
            body = self._body()
            if not self._own_page("the run config can be changed"):
                return
            if not svc.config_path:
                self._json(404, {"error": {"message": "this server was started without a run config"}})
                return
            try:
                req = json.loads(body or b"{}")
                with svc.config_lock:
                    cfg = runconfig.load(svc.config_path)
                    new, changed = runconfig.apply(cfg, req.get("set") if isinstance(req, dict) else None)
                    if changed:
                        bak = runconfig.save(svc.config_path, new)
            except ValueError as e:
                self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            except OSError as e:
                self._json(500, {"error": {"type": "server_error", "message": f"the run config cannot be written: {e}"}})
                return
            if changed:
                print(f"[strata] the Settings view changed {', '.join(changed)} in {Path(svc.config_path).name} "
                      f"(the earlier file: {bak.name}); used from the next start", flush=True)
            self._json(200, {**runconfig.view(new, svc.config_path), "changed": changed})
        def _foreign_origin(self) -> bool:
            """A web page of another origin sent this.  The Origin must be this server's own address (host and port),
            or an origin the config trusts (trusted_origins: the web app behind a reverse proxy or tunnel); no Origin
            is a client that is no browser.  Headers a proxy adds (X-Forwarded-*, CF-Ray, CF-Connecting-IP) prove
            nothing about the page that sent the request, so they open nothing."""
            origin = (self.headers.get("Origin") or "").rstrip("/")
            return bool(origin) and origin.split("://", 1)[-1] != self.headers.get("Host", "") and \
                origin not in svc.trusted_origins

        def _no_local_images(self, messages):
            """A web page of another origin must not have a file on this computer read as an image.  Without an
            api_key, _foreign_page refuses such a page unless cors_origins lets it in - and a page cors_origins lets
            in (["*"]: every page) could name any file and, CORS allowing, read what the model says about it.  data:
            and http(s) images are the page's own to send; files come from Strata's own page, a trusted origin or a
            client that is no browser.  ValueError (a 400)."""
            if self._foreign_origin() and any(not src.startswith(("data:", "http://", "https://"))
                                              for src in images_of(messages)):
                raise ValueError("a web page of another origin cannot have a file on this computer read as an "
                                 "image: send it as a data: URL (or add the page's origin to the config's "
                                 "trusted_origins)")

        def _settings(self):
            # They change what every client gets, so only the app's own page may set them
            body = self._body()
            if not self._own_page("settings can be changed"):
                return
            try:
                req = json.loads(body or b"{}")
                if not isinstance(req, dict) or "defaults" not in req:
                    self._json(400, {"error": {"type": "invalid_request_error",
                                              "message": 'the body must be {"defaults": {...}} to set them, '
                                                         'or {"defaults": null} to clear them'}})
                    return
                shared = svc.set_shared(req["defaults"])
            except ValueError as e:
                self._json(400, {"error": {"type": "invalid_request_error", "message": str(e)}})
                return
            print("[strata] other apps now use the Chat settings: " + ", ".join(f"{k}={v}" for k, v in shared.items())
                  if shared else "[strata] other apps use their own settings again", flush=True)
            self._json(200, {"shared": bool(shared), "defaults": shared})

        def _sse(self):
            self._note(http_status=200)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")   # nginx and similar proxies pass each event at once
            self._cors()
            self.end_headers()
            if STREAM_WRITE_TIMEOUT_S > 0:
                try:
                    self.connection.settimeout(STREAM_WRITE_TIMEOUT_S)     # (#4271) a stuck write ends as OSError: disconnected
                except OSError:
                    pass

        def _capture(self, items, api):
            """Retain bounded input/output for the monitor without changing the API response (the items as they
            are when the monitor is off)."""
            if self.record is None:
                return items
            return self._captured(items, api)

        def _captured(self, items, api):
            try:
                for item in items:
                    if item is not None:
                        if api == "openai":
                            delta = item["choices"][0]["delta"]
                            content, reasoning = delta.get("content", ""), delta.get("reasoning_content", "")
                            usage, timings = item.get("usage"), item.get("timings")
                        elif api == "responses":
                            kind = item["type"]
                            content = item["delta"] if kind == "response.output_text.delta" else ""
                            reasoning = item["delta"] if kind == "response.reasoning_text.delta" else ""
                            usage, timings = (item.get("response") or {}).get("usage"), None
                        else:
                            _, event = item
                            delta = event.get("delta", {})
                            content, reasoning = delta.get("text", ""), delta.get("thinking", "")
                            usage, timings = event.get("usage"), None
                        with svc.status_lock:
                            for name, value in (("output", content), ("reasoning", reasoning)):
                                if value:
                                    combined = self.record[name] + value
                                    self.record[name] = combined[:262144]
                                    self.record[name + "_truncated"] |= len(combined) > 262144
                            if usage:
                                self.record["usage"] = usage
                            if timings:
                                self.record["timings"] = timings
                    yield item
            finally:
                items.close()

        def _ray_history(self, session_name: str = "dl-ai-code"):
            """Returns the recent conversational history from the shared CLI session daemon (dl_sessiond)."""
            if not SESSIOND_SOCKET.exists():
                self._json(200, {"session": session_name, "messages": []})
                return
            conn = socket.socket(socket.AF_UNIX)
            conn.settimeout(10)
            try:
                conn.connect(str(SESSIOND_SOCKET))
                conn.sendall((json.dumps({"op": "attach", "session": session_name}) + "\n").encode())
                f = conn.makefile("rb")
                hello = json.loads(f.readline() or "{}")
                msgs = []
                for ev in hello.get("events", []):
                    ev_type = ev.get("type")
                    if ev_type == "user":
                        msgs.append({"role": "user", "content": ev.get("text", "")})
                    elif ev_type == "text":
                        if msgs and msgs[-1]["role"] == "assistant":
                            msgs[-1]["content"] += ev.get("text", "")
                        else:
                            msgs.append({"role": "assistant", "content": ev.get("text", "")})
                self._json(200, {
                    "session": session_name,
                    "state": hello.get("state", {}),
                    "messages": msgs[-50:]
                })
            except Exception as e:
                self._json(500, {"error": {"message": f"failed to load session history: {e}"}})
            finally:
                conn.close()

        def _ray_chat(self, req: dict):
            """Bridge /v1/ray/chat to the shared CLI session daemon (dl_sessiond) so Ray has access to
            all MCP tools, full multi-turn conversational context, and workspace.
            Falls back to raw engine completion if sessiond is not running."""
            # it drives Ray's agent session (tools, the shell) like /api/code/session's input: the same check, not
            # only /v1's (a page on another port of an allowed host, a chrome-extension:// origin, cors_origins "*")
            if not self._own_page("Ray's session can be driven"):
                return
            if not SESSIOND_SOCKET.exists():
                self._ray_chat_prepare(req)
                return self._openai(req)

            messages = req.get("messages", [])
            last_user_msg = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")
            if not last_user_msg:
                last_user_msg = req.get("text", "")
            if not last_user_msg:
                self._json(400, {"error": {"message": "messages must contain at least one user message"}})
                return

            session_name = req.get("session") or "dl-ai-code"
            is_voice = req.get("voice", True)

            clean_msg = last_user_msg.strip().lower().rstrip(".!?,")
            is_new_session = clean_msg in (
                "/clear", "/new", "/reset",
                "clear", "new session", "start a new session",
                "start new session", "clear session", "clear conversation",
                "reset session", "reset conversation", "start a new conversation",
                "new conversation", "start over", "start fresh"
            )
            followup_prompt = ""
            for prefix in ("start a new session and ", "start a new session to ", "new session, ", "new session: ", "start fresh and "):
                if clean_msg.startswith(prefix):
                    is_new_session = True
                    followup_prompt = last_user_msg[len(prefix):].strip()
                    break

            try:
                conn = socket.socket(socket.AF_UNIX)
                conn.settimeout(180)
                conn.connect(str(SESSIOND_SOCKET))
                f = conn.makefile("rb")
            except OSError:
                self._ray_chat_prepare(req)
                return self._openai(req)

            try:
                conn.sendall((json.dumps({"op": "attach", "session": session_name}) + "\n").encode())
                hello = json.loads(f.readline() or "{}")

                if is_new_session:
                    conn.sendall((json.dumps({
                        "op": "input",
                        "session": session_name,
                        "text": "/clear",
                        "voice": is_voice,
                        "origin": "ray-android"
                    }) + "\n").encode())
                    # Consume events until turn_end
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if ev.get("type") == "turn_end":
                            break

                    if not followup_prompt:
                        reply_text = "Started a clean new session! What would you like to work on?"
                        if not req.get("stream", True):
                            return self._json(200, {
                                "id": "chatcmpl-ray",
                                "object": "chat.completion",
                                "model": svc.model,
                                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply_text}, "finish_reason": "stop"}]
                            })
                        self._sse()
                        chunk = {
                            "id": "chatcmpl-ray",
                            "object": "chat.completion.chunk",
                            "model": svc.model,
                            "choices": [{"index": 0, "delta": {"content": reply_text}, "finish_reason": None}]
                        }
                        self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return

                    # Follow-up prompt provided
                    last_user_msg = followup_prompt

                conn.sendall((json.dumps({
                    "op": "input",
                    "session": session_name,
                    "text": last_user_msg,
                    "voice": is_voice,
                    "origin": "ray-android"
                }) + "\n").encode())

                if not req.get("stream", True):
                    full_reply, after_tool = "", False
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        if ev.get("type") == "text":
                            text = ev.get("text", "")
                            if after_tool and text and full_reply and not full_reply[-1].isspace() \
                                    and not text[0].isspace():
                                text = " " + text                # the preamble and the answer, spaced apart
                            after_tool = False
                            full_reply += text
                        elif ev.get("type") == "tool_call":
                            after_tool = True
                        elif ev.get("type") == "turn_end":
                            break
                    res = {
                        "id": "chatcmpl-ray",
                        "object": "chat.completion",
                        "model": svc.model,
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": full_reply},
                            "finish_reason": "stop"
                        }]
                    }
                    return self._json(200, res)

                self._sse()
                tail, after_tool = "", False                # text after a tool call starts a new paragraph of speech
                while True:
                    line = f.readline()
                    if not line:
                        break
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    ev_type = ev.get("type")
                    # the answer as content; the model's thinking as reasoning_content (the voice drawer shows it,
                    # never reads it aloud); a tool call as ray_tool (the drawer's "Using a tool" note)
                    if ev_type == "text":
                        text = ev.get("text", "")
                        # the preamble before a tool ("Checking your battery now.") and the answer after it came out
                        # glued together ("now.Your battery")
                        if after_tool and text and tail and not tail[-1].isspace() and not text[0].isspace():
                            text = " " + text
                        after_tool = False
                        tail = text[-1:] or tail
                        delta, extra = {"content": text}, {}
                    elif ev_type == "thinking":
                        delta, extra = {"reasoning_content": ev.get("text", "")}, {}
                    elif ev_type == "tool_call":
                        after_tool = True
                        delta, extra = {}, {"ray_tool": {"name": ev.get("name") or ""}}
                    elif ev_type == "turn_end":
                        break
                    else:
                        continue
                    chunk = {
                        "id": "chatcmpl-ray",
                        "object": "chat.completion.chunk",
                        "model": svc.model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        **extra,
                    }
                    self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                conn.close()

        def _ray_chat_prepare(self, req: dict):
            """D.L. AI / Ray Android: inject Ray's persona and voice guidance for the assistant app."""
            if "stream" not in req:
                req["stream"] = True
            if "strata_mcp" not in req and svc.mcp is not None:
                req["strata_mcp"] = True
            messages = req.setdefault("messages", [])
            has_system = any(m.get("role") == "system" for m in messages)
            try:
                from dl_cli import RAY_ABOUT, voice_note
            except ImportError:
                try:
                    from tools.dl_cli import RAY_ABOUT, voice_note
                except ImportError:
                    RAY_ABOUT = ("You and the model run on the home server, and that is what you call it.\n"
                                 "Who you are: Ray (he/him), the household's red panda and AI assistant, as well as its "
                                 "coding agent and its smart home helper (Home Assistant, through an MCP server). "
                                 "Your avatar in the web app is a red panda drawn in dots. Like a red panda you are "
                                 "curious, playful and good-natured. Talk like a friendly, capable person: casual and "
                                 "direct, with a light joke now and then. When you use an emoji for yourself in writing, "
                                 "it is 🐾 and no other animal.")
                    def voice_note(thinking=True):
                        return "[Spoken prompt: your reply will be read aloud. Answer in plain speech.]"
            if not has_system:
                messages.insert(0, {"role": "system", "content": RAY_ABOUT})
            is_voice = req.pop("voice", False)
            if is_voice and messages:
                last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
                if last_user and isinstance(last_user.get("content"), str):
                    v_note = voice_note(thinking=True)
                    if v_note and v_note not in last_user["content"]:
                        last_user["content"] += "\n" + v_note

        def _openai(self, req):
            req = svc.with_shared(req, "openai")
            bias_api.normalize(req.get("logit_bias"), len(getattr(svc.tok, "tokens", ())) or None)
            messages, tools, kw = openai_to_messages(req)
            require_messages(messages)                # an empty conversation is a 400, as OpenAI answers it, not a reply to nothing
            self._no_local_images(messages)
            if tool_choice_of(req.get("tool_choice"))[0] == "none":   # as the Responses route: no tools are offered
                tools = None
            force = forced_call(req.get("tool_choice"), tools)      # a bad value is a 400 before anything is sent
            messages, validator = prepare_format(req.get("response_format"), messages)
            if validator is not None and (tools or req.get("strata_mcp")):
                raise ValueError("structured response_format with tools/MCP is not supported")
            svc.load()
            max_req = max_new = int(req.get("max_completion_tokens") or req.get("max_tokens") or 0)   # 0/-1: the rest
            bias_api.validate_request(req, svc.engine, len(getattr(svc.tok, "tokens", ())) or None)
            use_mcp = req.get("strata_mcp") is True and svc.mcp is not None      # the web app's opt-in (serve/mcp.py)
            own = {t.get("name") for t in tools or [] if isinstance(t, dict)}   # #592: a second line of defence
            if use_mcp:
                if not self._own_page("MCP tools can be used"):   # tools run with the user's rights on this PC
                    return
                svc.mcp.wait(10)                                  # servers still starting (only right after start)
                extra = svc.mcp.template_tools(exclude=own)       # the request's own tools win a name clash
                use_mcp = bool(extra)
                tools = (tools or []) + extra or None
            if force and use_mcp:
                raise ValueError("a forced tool_choice with MCP tools is not supported")
            svc.reasoning_budget(req)                         # a bad value is a 400 before anything is sent
            stop_strings(req)                                 # ... and so is a bad stop / stop_sequences
            check_request_sampling(req)                       # ... and a sampling field of the wrong type
            cancel = threading.Event()
            self._watch_client(cancel)                       # #430 #431 (#1999: before prepare, which can take long)
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, force=force, req=req, cancel=cancel)
            _debug_req("openai", req, messages, tools, max_new, thinking, len(ids))
            run = run_with_mcp(svc, svc.mcp, messages, tools, kw, ids, thinking, max_new, max_req, req, cancel,
                               {t["name"] for t in extra}) if use_mcp else None
            chunks = openai_chunks(svc, req, ids, thinking, tools, max_new, cancel, run=run, force=force)
            if validator is not None:
                chunks = structured_chunks(chunks, validator)
            chunks = self._capture(chunks, "openai")
            if not req.get("stream"):
                return self._json(200, openai_collect(chunks))
            self._sse()
            try:
                for c in chunks:
                    if c is None:
                        self.wfile.write(b": keep-alive\n\n")      # an SSE comment: clients ignore it
                    else:
                        self.wfile.write(b"data: " + json.dumps(c, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()                                 # client went away: stop the engine
                chunks.close()
            except (EngineDied, EngineStuck) as e:
                err = {"error": {"type": "server_error", "message": died_note(e)}}
                self._note(error=err["error"])
                try:
                    self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
                except OSError:
                    self._note(outcome="disconnected")
            except ValueError as e:
                err = {"error": {"type": "server_error", "message": str(e)}}
                self._note(error=err["error"])
                try:
                    self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
                except OSError:
                    self._note(outcome="disconnected")

        def _completions(self, req):
            """OpenAI legacy text completions over a caller-tokenized prompt (no chat template)."""
            req = svc.with_shared(req, "openai")
            prompt = req.get("prompt")
            if not isinstance(prompt, str):
                raise ValueError("prompt must be a string")
            for key in ("n", "best_of"):
                value = req.get(key, 1)
                if value != 1:
                    raise ValueError(f"{key} must be 1 (the server generates one sequence at a time)")
            if req.get("suffix") not in (None, ""):
                raise ValueError("suffix is not supported")
            if req.get("logprobs") is not None:
                raise ValueError("logprobs are not supported")
            stream_options = req.get("stream_options")
            if stream_options is not None:
                if not isinstance(stream_options, dict) or set(stream_options) - {"include_usage"}:
                    raise ValueError("stream_options supports only include_usage")
                if not req.get("stream"):
                    raise ValueError("stream_options are only supported with stream: true")
            _, _, template_kwargs = openai_to_messages({**req, "messages": []})
            thinking = template_kwargs.get("enable_thinking", True) is not False
            if req.get("enable_thinking") is False or req.get("thinking") is False:
                thinking = False
            thinking_cfg = req.get("thinking")
            if isinstance(thinking_cfg, dict) and thinking_cfg.get("type") == "disabled":
                thinking = False
            bias_api.normalize(req.get("logit_bias"), len(getattr(svc.tok, "tokens", ())) or None)
            ids = svc.tok.encode(prompt, parse_special=True)
            if thinking is False:                        # passthrough stays untouched when thinking is on; asked off,
                tail = svc.tok.encode(svc.template.gen_prompt_tail(False), parse_special=True)   # the prompt gets the tail
                tail_on = svc.tok.encode(svc.template.gen_prompt_tail(True), parse_special=True)  # a chat render adds
                if tail and ids[-len(tail):] != tail and ids[-len(tail_on):] != tail_on:
                    ids = ids + tail
            try:
                max_new = int(req.get("max_tokens") or 0)
            except (TypeError, ValueError):
                raise ValueError("max_tokens must be a whole number")
            bias_api.validate_request(req, svc.engine, len(getattr(svc.tok, "tokens", ())) or None)
            svc.reasoning_budget(req)
            stop_strings(req)
            check_request_sampling(req)
            cancel = threading.Event()
            self._watch_client(cancel)
            svc.load()
            model = svc.model_for(req)
            cid, created = "cmpl-" + uuid.uuid4().hex[:24], int(time.time())
            max_new = max_new if max_new > 0 else None
            ctx = svc.engine.max_context
            if ctx <= 0:
                ctx = getattr(svc.engine, "known_ctx", 0)
            if ctx <= 0:
                raise EngineStarting("the engine is starting (a minute or two); try again shortly")
            room = ctx - CTX_SLACK - len(ids)
            if room < 1:
                raise ValueError("request exceeds the context window: prompt leaves no room to answer")
            if max_new is None:
                max_new = room
            elif max_new > room:
                if not svc.fit_max_tokens:
                    raise ValueError(f"request exceeds the context window: prompt + max_tokens exceeds context "
                                     f"(at most {room} tokens here)")
                max_new = room

            def chunks():
                completion_tokens = 0
                content = []
                try:
                    for kind, value in svc.run(ids, thinking, None, max_new, req, cancel):
                        if kind == "ping":
                            yield None
                        elif kind == "event":
                            if value.kind in ("content", "reasoning") and value.text:
                                content.append(value.text)
                                yield {"id": cid, "object": "text_completion", "created": created, "model": model,
                                       "choices": [{"text": value.text, "index": 0, "logprobs": None,
                                                    "finish_reason": None}]}
                        elif kind == "done":
                            completion_tokens = value["completion_tokens"]
                            text = "".join(content)
                            yield {"id": cid, "object": "text_completion", "created": created, "model": model,
                                   "choices": [{"text": (prompt if req.get("echo") else "") + text, "index": 0,
                                                "finish_reason": {"cancel": "stop"}.get(value["finish"], value["finish"])}],
                                   "usage": {"prompt_tokens": len(ids), "completion_tokens": completion_tokens,
                                             "total_tokens": len(ids) + completion_tokens}}
                finally:
                    cancel.set() if self.watch_done is None else None

            stream = bool(req.get("stream"))
            if not stream:
                text = []
                last = None
                for item in chunks():
                    if item is not None:
                        if "usage" in item:
                            last = item
                        else:
                            text.append(item["choices"][0]["text"])
                result = last or {"id": cid, "object": "text_completion", "created": created, "model": model,
                                  "choices": [{"index": 0, "text": "", "logprobs": None, "finish_reason": "length"}],
                                  "usage": {"prompt_tokens": len(ids), "completion_tokens": 0, "total_tokens": len(ids)}}
                result["choices"][0]["text"] = (prompt if req.get("echo") else "") + "".join(text)
                self._json(200, result)
                return
            self._sse()
            stream_chunks = chunks()
            try:
                for item in stream_chunks:
                    if item is None:
                        self.wfile.write(b": keep-alive\n\n")
                    else:
                        self.wfile.write(b"data: " + json.dumps(item, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()
                stream_chunks.close()
            except (EngineDied, EngineStuck) as e:           # mid-stream: say so, then end the stream properly
                err = {"error": {"type": "server_error", "message": died_note(e)}}
                self._note(error=err["error"])
                try:
                    self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
                except OSError:
                    self._note(outcome="disconnected")
            except StructuredOutputError as e:
                err = {"error": {"type": "structured_output_failed", "code": "structured_output_failed", "message": str(e)}}
                self._note(error=err["error"])
                try:
                    self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
                except OSError:
                    self._note(outcome="disconnected")
            except ValueError as e:                          # the engine's ERR after the stream started: the
                err = {"error": {"type": "server_error", "message": str(e)}}   # headers are sent, so no 400 now
                self._note(error=err["error"])
                try:
                    self.wfile.write(b"data: " + json.dumps(err).encode() + b"\n\ndata: [DONE]\n\n")
                except OSError:
                    self._note(outcome="disconnected")

        def _responses_ready(self, req, events):
            """Send a finished Responses result that did not run on the engine."""
            if not req.get("stream"):
                return self._json(200, responses_api.collect(events))
            self._sse()
            try:
                for e in events:
                    self.wfile.write(f"event: {e['type']}\n".encode() + b"data: " +
                                     json.dumps(e, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
            except OSError:
                self._note(outcome="disconnected")

        def _responses(self, req):
            """#451: POST /v1/responses - OpenAI's Responses API, stateless (serve/responses.py), on the chat path.
            Errors use the Responses format; once the stream has started they arrive as a response.failed event."""
            try:
                title = (responses_api.thread_title_events(req, svc.model_for(req))
                         if svc.codex_thread_titles else None)
            except ResponsesError as e:
                return self._json(e.status, e.body())
            if title is not None:
                return self._responses_ready(req, title)
            cancel = threading.Event()
            self._watch_client(cancel)                       # #430 #431 (#1999: before prepare, which can take long)
            try:
                ids, thinking, tools, max_new, asm, validator, req = self._responses_prepare(req, cancel)
            except ClientGone:
                self._note(outcome="disconnected")
                return
            except ResponsesError as e:
                return self._json(e.status, e.body())
            except ModelBusy as e:
                return self._json(409, responses_error_body(str(e), "server_error", code="model_busy"))
            except (GpuBusy, EngineStarting, EngineStuck, EngineDied) as e:
                return self._json(503, responses_error_body(str(e), "server_error", code="server_error"))

            def check(text, finish):
                return validated_json(text, validator, finish)

            def events():
                yield from asm.start()
                done = None
                for kind, x in svc.run(ids, thinking, tools, max_new, req, cancel):
                    if kind == "ping":
                        yield None
                    elif kind == "event":
                        yield from asm.feed(x)
                    elif kind == "done":
                        done = x
                if done is not None and done["finish"] != "cancel" and not cancel.is_set():
                    yield from asm.finish(done, check)
            items = self._capture(events(), "responses")
            if not req.get("stream"):
                try:
                    result = responses_api.collect(items)
                except StructuredOutputError as e:
                    return self._json(502, responses_error_body(str(e), "server_error",
                                                                code="structured_output_failed"))
                except EngineDied as e:
                    return self._json(503, responses_error_body(died_note(e), "server_error",
                                                                code="server_error"))
                except EngineNonFinite as e:                 # #879, twice: not the request's fault
                    return self._json(503, responses_error_body(str(e), "server_error", code="server_error"))
                except ValueError as e:                      # the engine's ERR line
                    return self._json(500, responses_error_body(str(e), "server_error", code="server_error"))
                return self._json(200, result)
            self._sse()
            last = time.monotonic()

            def send(e):
                self.wfile.write(f"event: {e['type']}\n".encode() + b"data: " +
                                 json.dumps(e, ensure_ascii=False).encode() + b"\n\n")

            try:
                for e in items:
                    if e is None:
                        # Codex's idle timeout (5 minutes by default) counts events, not SSE comments: while a long
                        # prompt is read, a response.in_progress every 15 s tells it the server is still working
                        if time.monotonic() - last >= 15:
                            send(asm.in_progress())
                            last = time.monotonic()
                        else:
                            self.wfile.write(b": keep-alive\n\n")
                    else:
                        send(e)
                        last = time.monotonic()
                    self.wfile.flush()
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()                                 # client went away: stop the engine
                items.close()
            except EngineDied as e:                          # mid-stream: response.failed, then the stream ends
                self._responses_failed(asm, died_note(e), "server_error", send)
            except StructuredOutputError as e:
                self._responses_failed(asm, str(e), "structured_output_failed", send)
            except ValueError as e:                          # the engine's ERR after the stream started
                self._responses_failed(asm, str(e), "server_error", send)

        def _responses_failed(self, asm, message, code, send):
            e = asm.failed(message, code)
            self._note(error=e["response"]["error"])
            try:
                send(e)
                self.wfile.flush()
            except OSError:
                pass

        def _responses_prepare(self, req, cancel=None):
            responses_api.check_request(req)
            messages = responses_api.input_messages(req)
            tools, names, skipped = responses_api.request_tools(req)
            kw = responses_api.template_kwargs(req, {"reasoning_effort": svc.effort_default()})
            try:
                self._no_local_images(messages)              # as on the chat route: no file read for a foreign page
            except ValueError as e:
                raise ResponsesError(str(e), "input") from None
            try:
                messages, validator = prepare_format(responses_api.text_format(req), messages, with_tools=bool(tools))
            except ValueError as e:
                raise ResponsesError(str(e).replace("response_format", "text.format"), "text.format") from None
            noted = svc.__dict__.setdefault("hosted_tools_noted", set())   # said once per tool, not per request
            if set(skipped) - noted:
                print(f"[strata] /v1/responses: left out the hosted tools {', '.join(sorted(set(skipped) - noted))} "
                      f"(this server cannot run them)", flush=True)
                noted.update(skipped)
            if req.get("max_output_tokens") is None and "max_tokens" in svc.shared:   # the shared Chat settings
                req = {**req, "max_output_tokens": svc.shared["max_tokens"]}
            try:
                svc.reasoning_budget(req)                    # a bad value is a 400 before anything is sent
            except ValueError as e:
                raise ResponsesError(str(e), "reasoning_budget_tokens") from None
            try:
                stop_strings(req)
            except ValueError as e:
                raise ResponsesError(str(e), "stop") from None
            try:
                check_request_sampling(req)                   # the request is also the sampling dict (see below)
            except ValueError as e:                           # its message starts with the field's name: the param
                raise ResponsesError(str(e), str(e).partition(":")[0]) from None
            svc.load()
            # #924 (opt-in): a Codex compaction request is rendered with its conversation's tools, so its prompt
            # starts as the cached one did; the parser and the response keep the request's own tools
            shown = responses_api.prompt_tools(req, tools) if svc.codex_compaction_cache else tools
            try:
                try:
                    ids, thinking, max_new = svc.prepare(messages, shown, kw, req.get("max_output_tokens") or 0, req=req,
                                                          cancel=cancel)
                except ValueError:
                    if shown is tools:
                        raise
                    shown = tools                            # too long with the kept tools: the request as sent
                    ids, thinking, max_new = svc.prepare(messages, shown, kw, req.get("max_output_tokens") or 0, req=req,
                                                          cancel=cancel)
            except ResponsesError:
                raise
            except ValueError as e:                          # too long for the context, an image without vision
                raise ResponsesError(str(e), "input", "context_length_exceeded" if "context" in str(e) else None) \
                    from None
            if svc.codex_compaction_cache:
                responses_api.prompt_made(req, shown)
            _debug_req("responses", req, messages, tools, max_new, thinking, len(ids))
            include = req.get("include") if isinstance(req.get("include"), list) else []
            asm = responses_api.Assembler(req, svc.model_for(req), len(ids), names,
                                          "reasoning.encrypted_content" in include, validator is not None)
            # the request is also the sampling dict, as on the chat path (temperature, top_p, top_k, seed, ...)
            return ids, thinking, tools, max_new, asm, validator, req

        def _count_tokens(self, req):
            """Anthropic's token count, which Claude Code asks for its context figures: the prompt this server would
            read for the same request, rendered and tokenized - the model does not run."""
            _dump_claude_prompt(req)
            req = svc.with_shared(req, "anthropic")
            messages, tools, kw = anthropic_to_messages(req, svc.anthropic_think_unasked)
            stop_strings(req)                                 # the same 400 as the request itself would get
            check_request_sampling(req)                       # ... likewise a sampling field of the wrong type
            self._json(200, {"input_tokens": len(svc.encode_prompt(messages, tools, kw, store=False))})

        def _anthropic(self, req):
            _dump_claude_prompt(req)
            svc.load()
            req = svc.with_shared(req, "anthropic")
            messages, tools, kw = anthropic_to_messages(req, svc.anthropic_think_unasked)
            self._no_local_images(messages)
            if tool_choice_of(req.get("tool_choice"))[0] == "none":   # Anthropic's {"type": "none"}: no tools offered
                tools = None
            force = forced_call(req.get("tool_choice"), tools)        # "any" / {"type": "tool", "name": N}
            max_new = int(req.get("max_tokens") or 0)                  # 0/-1: the rest of the context
            svc.reasoning_budget(req)                         # a bad value is a 400 before anything is sent
            stop_strings(req)                                 # ... and so is a bad stop / stop_sequences
            check_request_sampling(req)                       # ... and a sampling field of the wrong type
            cancel = threading.Event()
            self._watch_client(cancel)                       # #430 #431 (#1999: before prepare, which can take long)
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_new, force=force, req=req, cancel=cancel)
            _debug_req("anthropic", req, messages, tools, max_new, thinking, len(ids))
            events = anthropic_events(svc, req, ids, thinking, tools, max_new, cancel, force=force)
            events = self._capture(events, "anthropic")
            if not req.get("stream"):
                return self._json(200, anthropic_collect(events))
            self._sse()
            try:
                for item in events:
                    if item is None:
                        self.wfile.write(b": keep-alive\n\n")
                    else:
                        name, e = item
                        self.wfile.write(f"event: {name}\n".encode() + b"data: " +
                                         json.dumps(e, ensure_ascii=False).encode() + b"\n\n")
                    self.wfile.flush()
            except OSError:
                self._note(outcome="disconnected")
                cancel.set()
                events.close()
            except EngineDied as e:                          # mid-stream: Anthropic's error event
                err = {"type": "error", "error": {"type": "api_error", "message": died_note(e)}}
                self._note(error=err["error"])
                self.wfile.write(b"event: error\ndata: " + json.dumps(err).encode() + b"\n\n")
            except ValueError as e:                          # the engine's ERR after the stream started
                err = {"type": "error", "error": {"type": "api_error", "message": str(e)}}
                self._note(error=err["error"])
                self.wfile.write(b"event: error\ndata: " + json.dumps(err).encode() + b"\n\n")

    return Handler


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already serving, and requests then land on
    # either one (a forgotten second start of run-<model>.bat).  Without it the second start fails loudly instead.
    allow_reuse_address = os.name != "nt"
    # socketserver listens with a backlog of 5: a burst of 30-40 clients at once got "connection reset by peer" on the
    # first ones (measured on 4 x R9700, also with one request at a time); the requests wait in the server, not the kernel
    # (STRATA_HTTP_BACKLOG overrides it)
    request_queue_size = max(5, int(os.environ.get("STRATA_HTTP_BACKLOG") or 256))

    def server_bind(self):
        # http.server's own server_bind also asks socket.getfqdn(host) for a server_name nothing here reads; on a Mac whose reverse lookup
        # stalls (GitHub's macOS runner: 35 s on the first lookup of every new process) each start waited that long before it listened
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):   # a client that hangs up needs no stack trace
            super().handle_error(request, client_address)

    def server_close(self):
        # the hardware sampler serve() started for this server stops with it (test isolation: every Service a test
        # started used to leave its sampler running, 21 of them after test_responses, which slowed test_parallel's timing)
        tel = getattr(getattr(self, "svc", None), "telemetry", None)
        if tel is not None and hasattr(tel, "close"):
            tel.close()
        super().server_close()


def serve(svc: Service, host="127.0.0.1", port=8095) -> ThreadingHTTPServer:
    svc.host_names = host_names_for(host, svc.allowed_hosts, svc.trusted_origins)
    svc.start_telemetry()
    httpd = Server((host, port), make_handler(svc))
    httpd.svc = svc
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    """The server.  Its console output goes through a bounded queue (serve/nonblocking_out.py, #4479 / #2481): a console
    that stops taking output must not hold a request's turn, a cancel or an admission.  STRATA_BLOCKING_CONSOLE=1 turns
    it off (testers)."""
    quiet_crash_env()                                  # every child inherits it: no gdb on a user's machine (serve/childenv.py)
    if os.environ.get("STRATA_BLOCKING_CONSOLE") == "1":
        return _main()
    from serve.nonblocking_out import decoupled_console
    with decoupled_console():
        return _main()


def undeclared_tool_calls_setting(cfg: dict) -> str:
    """#4622: the config's "undeclared_tool_calls": "text" (the default, when the config does not name it) keeps a well-formed call of a tool the request
    did not declare as the text the model wrote, with strata_rejected_tool_calls beside it; "call" returns it as a tool call, for a client that has
    its own policy for unknown names (it answers the model with the tool names it has).  Anything else stops the start."""
    mode = cfg.get("undeclared_tool_calls")
    if mode is None:                                  # the environment names it too (STRATA_UNDECLARED_TOOL_CALLS); the config wins
        mode = os.environ.get("STRATA_UNDECLARED_TOOL_CALLS") or "text"
    if mode not in ("text", "call"):
        raise SystemExit(f"[strata] config \"undeclared_tool_calls\" must be \"text\" or \"call\", not {mode!r}")
    return mode


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["mock", "strata"], default="mock")
    ap.add_argument("--config", help="strata engine config (JSON: exe, args, cwd, tokenizer, model_name), "
                                     "written by setup.py")
    ap.add_argument("--host", default=None,
                    help="the address to listen on: 127.0.0.1 = this PC only (the default), 0.0.0.0 = also other devices "
                         "on your network (set an API key); also \"host\" in the config")
    ap.add_argument("--script", action="append",
                    help="the mock engine's answer (default: a short greeting); given more than once, requests get "
                         "them in turn and the last one repeats")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--gpu", help="the GPU to run on, as nvidia-smi numbers them, or several for a layer split "
                                  "(\"0,2\"; also \"gpu\" in the config)")
    ap.add_argument("--tokenizer", default=str(ROOT / "pack/full/tokenizer"),
                    help="pack tokenizer directory (falls back to a byte tokenizer if absent)")
    ap.add_argument("--open", action="store_true", help="open the local page in the browser once the model is ready")
    ap.add_argument("--fit-max-tokens", action="store_true",
                    help="clamp max_tokens to the remaining context instead of rejecting the request "
                         "(default: reject with 400, like llama.cpp; also \"fit_max_tokens\": true in the config)")
    ap.add_argument("--api-key", default=os.environ.get("STRATA_API_KEY", ""),
                    help="require this key on /v1/* (Authorization: Bearer ... or x-api-key); also $STRATA_API_KEY. "
                         "Several keys: separate them with commas (key1,key2), as llama.cpp does")
    ap.add_argument("--mcp-config", help="a JSON file with MCP servers in Claude Desktop's format ({\"mcpServers\": "
                                         "{...}}); the web app's chat can use their tools (also \"mcp_servers\" in "
                                         "the config)")
    ap.add_argument("--lazy", action="store_true", help="start the API unloaded (the engine and the vision encoder start with the first request)")
    ap.add_argument("--api-monitor", action="store_true",
                    help="the API request monitor at /api-monitor: keeps the last 100 requests' prompts and answers in "
                         "memory (also \"api_monitor\": true in the config; off by default)")
    ap.add_argument("--idle-unload", type=float, default=None, metavar="SECONDS",
                    help="unload the model after this many seconds without requests, so other programs (games, other "
                         "model servers) can use the VRAM; the next request loads it again (also \"idle_unload_s\" "
                         "in the config; default: never)")
    ap.add_argument("--min-free-vram-mib", type=int, default=None,
                    help="load an unloaded model only when this much VRAM is free, else answer 503 (also "
                         "\"min_free_vram_mib\" in the config; default: always load)")
    ap.add_argument("--before-load", help="a command run before the model is loaded again (e.g. to unload another "
                                          "server's model; also \"before_load\" in the config, a string or a list)")
    ap.add_argument("--slot-save-path", default=None, metavar="DIR",
                    help="enable POST /slots/0?action=save|restore {\"filename\": NAME} (llama-server's API): the "
                         "conversation the engine holds, to or from DIR/NAME (also \"slot_save_path\" in the config)")
    ap.add_argument("--replicas", type=int, default=None, metavar="N",
                    help="data-parallel replicas (opt-in): cut the \"gpu\" list into N equal groups and run one engine on "
                         "each, requests spread over them (also \"replicas\" in the config: a number, or "
                         "[{\"gpus\": [0, 1]}, {\"gpus\": [2, 3]}])")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8-sig")) if a.config else {}   # Notepad adds a BOM
    lift_reasoning_effort_arg(cfg)
    if a.replicas is not None:
        cfg["replicas"] = a.replicas
    if a.gpu is not None:
        cfg["gpu"] = int(a.gpu) if a.gpu.strip().isdigit() else a.gpu
    a.host = a.host or cfg.get("host") or "127.0.0.1"   # issue #26: the run scripts pass no --host, the config can
    try:                                                # before the minutes of loading: is the port free?
        Server((a.host, a.port), BaseHTTPRequestHandler).server_close()
    except OSError as e:
        ap.error(listen_problem(a.host, a.port, e))
    if cfg.get("tokenizer"):
        a.tokenizer = cfg["tokenizer"]
    tok = ByteTokenizer()
    tpath = Path(a.tokenizer)
    if a.engine == "strata" and not (tpath / "vocab.json").exists():
        ap.error(f"the model's tokenizer is missing ({tpath / 'vocab.json'}); run setup again")
    if (tpath / "vocab.json").exists():
        import strata_tokenizer as ST
        vocab = json.loads((tpath / "vocab.json").read_text(encoding="utf-8"))
        tokens = [None] * len(vocab)
        for t, i in vocab.items():
            tokens[i] = t
        merges = (tpath / "merges.txt").read_text(encoding="utf-8").split("\n")
        types = json.loads((tpath / "token_type.json").read_text())
        tok = ST.Tokenizer(tokens, merges, types)
    hub = hub_from_config(cfg, a.mcp_config)            # before the minutes of loading: a bad entry stops here
    lazy = a.lazy or (cfg.get("lazy_load") is True if cfg else False)
    if a.engine == "strata":
        if not cfg:
            ap.error("--engine strata needs --config")
        vision = None
        env = child_env(cfg)
        sampling_defaults = sampling_defaults_from_config(cfg)
        if sampling_defaults:
            pretty = ", ".join(f"{k}={v}" for k, v in sampling_defaults.items())
            print(f"[strata] sampling defaults from the config: {pretty}", flush=True)
        if cfg.get("vision"):
            elastic = cfg["vision"].get("elastic") is True and (
                cfg.get("vram_elastic") is True or not cfg["vision"].get("gpu")
            )
            print("the vision encoder starts with the first picture (elastic) ..." if elastic else
                  "loading the vision encoder ..." if not lazy else
                  "vision encoder unloaded; it starts with the model ...", flush=True)
            # relative paths are the config's cwd's, as for the engine below
            vcfg = {k: (os.path.abspath(os.path.join(cfg.get("cwd") or ".", v))
                        if k in ("exe", "mmproj", "model") and isinstance(v, str) and not os.path.isabs(v) else v)
                    for k, v in cfg["vision"].items()}
            if vcfg.get("elastic") is True and vcfg.get("gpu") and cfg.get("vram_elastic") is not True:
                print('[strata] the vision section\'s "elastic" needs "vram_elastic": true (the expert cache gives the '
                      "encoder its VRAM): the encoder starts with the model instead", flush=True)
                vcfg["elastic"] = False
            vision = Vision(vcfg, log=open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None,
                            env=vision_env(cfg, env), lazy=lazy)
        print("model unloaded; the first request loads it ..." if lazy else
              "loading the model (the first start takes a minute or two) ...", flush=True)
        warn_budget_over_ram(engine_args(cfg) if "args" in cfg else [])      # #1080
        if layer_split_of(cfg):
            try:
                split = layer_split_value(cfg)          # #644: before the (minutes-long) start
            except ValueError as e:
                raise SystemExit(f"[strata] config {e}")
            print(f"[strata] layer split across GPUs {gpu_list(cfg)} ({split})", flush=True)
        elif len(gpu_list(cfg)) > 1:
            print(f"[strata] GPUs {gpu_list(cfg)}: the later card(s) serve as the peer expert tier (--peer-device)",
                  flush=True)
        # a relative "exe" is the config's cwd's: Windows' CreateProcess resolves "engine/strata.exe" against nothing
        # it is told about (WinError 2), so it is made absolute here
        exe = cfg["exe"] if os.path.isabs(cfg["exe"]) else os.path.abspath(os.path.join(cfg.get("cwd") or ".", cfg["exe"]))
        try:
            silence = engine_silence_s(cfg)             # #481: checked before the (minutes-long) start
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        try:
            effort_end = effort_end_args(cfg, exe, tok)  # #458
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        from serve import replicas as rp
        try:
            groups = rp.gpu_groups(cfg)
        except rp.ReplicaConfigError as e:
            raise SystemExit(f"[strata] config {e}")
        if groups:
            engine = start_replicas(cfg, groups, exe, effort_end or [], lazy)
        else:
            engine = StrataEngine(exe, engine_args(cfg) + (effort_end or []), cwd=cfg.get("cwd"), log=cfg.get("log"),
                                  env=env, lazy=lazy, cfg=cfg)
        engine.silence_s = silence                      # an attribute of its own: restart() keeps it
        warn_tight_ram(engine.info.get("arena_mib"))
        note = desktop_vram_note(cfg.get("backend"), engine.info.get("vram_free_mib"), engine.spawn[1],
                                 linux_desktop()) if not groups else None
        if note:                                        # #560 #516: before --open starts a browser on that card
            print(note, flush=True)
    else:
        effort_end = None
        engine, vision, sampling_defaults = MockEngine(tok, a.script or [
            "Thinking about it.</think>\n\nHello from the mock engine."]), None, {}
    # the model's own chat template (exported with its tokenizer), else the original model's
    tpl = tpath / "chat_template.jinja"
    svc = Service(engine, tok, ChatTemplate(tpl if tpl.exists() else ROOT / "serve/chat_template.jinja"),
                  model_name=default_model_name(cfg), vision=vision,
                  sampling_defaults=sampling_defaults,
                  fit_max_tokens=a.fit_max_tokens or cfg.get("fit_max_tokens") is True)
    svc.lazy = lazy
    svc.answer_room = cfg.get("answer_room") is not False
    svc.reasoning_close_retry = cfg.get("reasoning_close_retry") is True    # #1053: opt-in, off by default
    if cfg.get("images"):                               # image generation (serve/images.py), set up by setup --images
        icfg = {k: (os.path.abspath(os.path.join(cfg.get("cwd") or ".", v))
                    if k in ("exe", "diffusion_model", "vae", "llm", "out_dir") and isinstance(v, str)
                    and not os.path.isabs(v) else v)
                for k, v in cfg["images"].items()}
        try:
            svc.images = images_api.ImageGen(icfg, log=open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None)
        except ValueError as e:
            raise SystemExit(f"[strata] config: {e}")
        gone = svc.images.missing()
        if gone:
            print(f"[strata] image generation: missing {', '.join(gone)} - requests fail until setup --images has run "
                  "again", flush=True)
        print(f"[strata] image generation: {svc.images.model} {icfg.get('quant') or ''} on "
              f"{icfg.get('backend') or '?'} (POST /v1/images/generations; GPU policy {svc.images.policy})", flush=True)
    if cfg.get("prevent_sleep") is not None and not isinstance(cfg["prevent_sleep"], bool):
        raise SystemExit(f"[strata] config \"prevent_sleep\" must be true or false, not {cfg['prevent_sleep']!r}")
    from serve.keepawake import KeepAwake
    svc.keep_awake = KeepAwake.create(cfg.get("prevent_sleep") is True)      # #1727: opt-in, Windows only
    if cfg.get("reasoning_effort") is not None:         # #1641: the thinking level of requests that name none
        try:
            svc.config_effort = clean_shared_defaults({"reasoning_effort": cfg["reasoning_effort"]}).get("reasoning_effort")
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        if svc.config_effort:
            print(f"[strata] thinking level: {svc.config_effort} (reasoning_effort in the config; a request, or the "
                  "Chat settings shared with other apps, can set its own)", flush=True)
    svc.codex_thread_titles = cfg.get("codex_thread_titles") is True    # #923: opt-in, off by default
    svc.codex_compaction_cache = cfg.get("codex_compaction_cache") is True   # #924: opt-in, off by default
    try:
        svc.set_aliases(cfg.get("aliases"))             # #297: other names the model answers to
    except ValueError as e:
        raise SystemExit(f"[strata] config {e}")
    if svc.aliases:
        print(f"[strata] model aliases: {', '.join(svc.aliases)}", flush=True)
    if ("STRATA_API_KEY" in os.environ and not os.environ["STRATA_API_KEY"].strip()) or             any(x == "--api-key" and i + 1 < len(sys.argv) and not sys.argv[i + 1].strip() or x.strip() == "--api-key="
                for i, x in enumerate(sys.argv)):
        # #213: an empty key would switch authentication off without a word
        print("[strata] an API key was given but it is empty: set a key, or leave --api-key / STRATA_API_KEY out",
              file=sys.stderr)
        return 2
    try:
        svc.api_key = api_key_of(a.api_key or cfg.get("api_key", ""))
    except ValueError as e:
        print(f'[strata] {e}: set a key, or leave --api-key / STRATA_API_KEY / "api_key" out', file=sys.stderr)
        return 2
    svc.cf_access = cf_access.from_env()
    if svc.cf_access is not None:
        print(f"[strata] Cloudflare Access logins from {svc.cf_access.issuer} are accepted in place of the API key"
              if svc.cf_access.auds else f"[strata] Cloudflare Access: STRATA_CF_ACCESS_AUD is not set; the first "
              f"login from {svc.cf_access.issuer} logs its AUD tag", flush=True)
    if not svc.api_key and "api_key" in cfg:             # #569: written, but empty: the server has none (a warning, not a stop)
        print("[strata] the api_key in the config is empty: this server has no API key (anyone who can reach it can "
              "use it); set one, or leave api_key out", file=sys.stderr, flush=True)
    svc.cors_origins = origins_of(cfg.get("cors_origins"), "cors_origins", wildcard=True)
    svc.trusted_origins = origins_of(cfg.get("trusted_origins"), "trusted_origins", wildcard=False)
    try:
        svc.allowed_hosts = allowed_hosts_of(cfg.get("allowed_hosts"), os.environ.get("STRATA_ALLOWED_HOSTS", ""))
    except ValueError as e:
        raise SystemExit(f"[strata] config {e}")
    if svc.allowed_hosts:
        print("[strata] Host check off: any name reaches this server (allowed_hosts \"*\")" if "*" in svc.allowed_hosts
              else f"[strata] also answers to the host names {', '.join(svc.allowed_hosts)} (allowed_hosts)", flush=True)
    svc.api_monitor = a.api_monitor or cfg.get("api_monitor") is True
    if svc.api_monitor:
        print("[strata] API request monitor on (/api-monitor): the last 100 requests' prompts and answers are kept in "
              "memory" + ("" if svc.api_key else "; anyone who can reach this server can read them (no API key)"),
              flush=True)
    if svc.cors_origins:
        print(f"[strata] CORS on /v1/* for {', '.join(svc.cors_origins)}"
              + ("" if svc.api_key or "*" not in svc.cors_origins else
                 " - WARNING: any web page may use the model (no API key)"), flush=True)
    svc.idle_unload_s = a.idle_unload if a.idle_unload is not None else float(cfg.get("idle_unload_s") or 0)
    svc.min_free_vram_mib = a.min_free_vram_mib if a.min_free_vram_mib is not None else \
        int(cfg.get("min_free_vram_mib") or 0)
    svc.before_load = a.before_load or cfg.get("before_load") or None
    try:
        svc.before_load_timeout_s = float(cfg.get("before_load_timeout_s") or svc.before_load_timeout_s)
    except (TypeError, ValueError):
        print("[strata] \"before_load_timeout_s\" in the config is not a number; using "
              f"{svc.before_load_timeout_s:g} s", flush=True)
    svc.before_load_ignore_failure = cfg.get("before_load_ignore_failure") is True
    svc.before_load_strict = cfg.get("before_load_strict") is True
    # --slot-save-path is relative to the working directory the server was started in; the config's slot_save_path
    # to the config's "cwd" (the engine's folder) when it has one.  Either way the engine gets an absolute path.
    if a.slot_save_path or cfg.get("slot_save_path"):
        try:
            svc.slot_save_path = slot_save_dir(a.slot_save_path) if a.slot_save_path else \
                slot_save_dir(cfg["slot_save_path"], cfg.get("cwd"))
        except (ValueError, OSError) as e:
            raise SystemExit(f"[strata] {e}")
        print(f"[strata] slot save/restore on: {svc.slot_save_path} (session files are kept until deleted: "
              "about 1.2 GB per 63K-token conversation; restore only files this server wrote)", flush=True)
    mode = str(cfg.get("anthropic_thinking") or "model")   # #278: "on_request" = only when the request asks
    if mode not in ("model", "on_request"):
        raise SystemExit(f"[strata] config anthropic_thinking must be \"model\" or \"on_request\", not {mode!r}")
    svc.anthropic_think_unasked = mode == "model"
    recovery = cfg.get("tool_call_recovery", False)     # opt-in: see OutputParser's recover
    if not isinstance(recovery, bool):
        raise SystemExit(f"[strata] config \"tool_call_recovery\" must be true or false, not {recovery!r}")
    svc.tool_call_recovery = recovery
    svc.undeclared_tool_calls = undeclared_tool_calls_setting(cfg)
    etu = cfg.get("env_to_user", False)                # opt-in: see frontend._env_to_user
    if not isinstance(etu, bool):
        raise SystemExit(f"[strata] config \"env_to_user\" must be true or false, not {etu!r}")
    import serve.frontend as _frontend
    _frontend.ENV_TO_USER = etu
    rs = cfg.get("repeat_stop_tokens", REPEAT_STOP_TOKENS)   # #606: opt-out with 0
    if isinstance(rs, bool) or not isinstance(rs, int) or rs < 0:
        raise SystemExit(f"[strata] config \"repeat_stop_tokens\" must be a whole number >= 0 (0 = off), not {rs!r}")
    svc.repeat_stop_tokens = rs
    svc.effort_end = bool(effort_end)                   # #458: "effort_position": "end" with an engine that has it
    if cfg.get("reasoning_budget_tokens") is not None:  # #123: a default thinking budget for every request
        try:
            svc.reasoning_budget_tokens = cfg["reasoning_budget_tokens"]
            budget = svc.reasoning_budget({})
        except ValueError as e:
            raise SystemExit(f"[strata] config {e}")
        if budget:
            print(f"[strata] thinking budget: {budget} tokens (reasoning_budget_tokens; a request can set its own)",
                  flush=True)
    recovery = cfg.get("reasoning_loop_recovery", False)   # #728: false (default) | "stop" | "recover" (true)
    if recovery is True:
        recovery = "recover"
    if recovery is not False and recovery not in ("stop", "recover"):
        raise SystemExit("[strata] config \"reasoning_loop_recovery\" must be false, \"stop\" or \"recover\", "
                         f"not {recovery!r}")
    svc.reasoning_loop_recovery = recovery
    svc.gpu_index = (gpu_list(cfg) or [0])[0]           # the Monitor reads the card the engine runs on (issue #51)
    svc.gpu_indices = gpu_list(cfg)                     # ... or every card of a layer split (issue #112)
    if a.engine == "strata" and groups:                 # replicas: every card of every group
        svc.gpu_indices = [c for g in groups for c in g]
        svc.gpu_index = svc.gpu_indices[0]
    svc.backend = cfg.get("backend")                    # "hip": the AMD cards' readings come from sysfs (#301)
    if a.config:
        svc.config_path = a.config                      # #564: the web page's Settings view
    if a.config:                                        # the Chat settings shared with other apps, from last time
        svc.shared_path = str(Path(a.config).with_suffix("")) + ".shared-settings.json"
        try:
            svc.shared = clean_shared_defaults(json.loads(Path(svc.shared_path).read_text(encoding="utf-8")))
            if svc.shared:
                print("[strata] other apps use the Chat settings: " +
                      ", ".join(f"{k}={v}" for k, v in svc.shared.items()), flush=True)
        except (OSError, ValueError):
            svc.shared = {}
    if hub is not None:
        import atexit
        svc.mcp = hub
        print(f"[strata] starting {len(hub.servers)} MCP server{'s' * (len(hub.servers) != 1)} for the web app's "
              f"chat: {', '.join(hub.servers)}", flush=True)
        hub.start()
        atexit.register(hub.close)                      # the servers Strata started end with it
    httpd = serve(svc, host=a.host, port=a.port)
    svc.start_idle_unload()
    global STALL_LOG
    STALL_LOG = Path(os.environ.get("STRATA_STALL_LOG") or Path.home() / ".local/state/dl-ai/engine-stalls.jsonl")
    svc.degraded_reload = cfg.get("degraded_reload", True) is not False
    svc.start_degraded_reload()
    svc.start_vision_idle()
    here = "127.0.0.1" if a.host in ("0.0.0.0", "", "::") else a.host
    print(f"ready: http://{here}:{a.port}/v1  (OpenAI: /v1/chat/completions, Anthropic: /v1/messages, "
          f"context {engine.max_context} tokens{', images on' if vision else ''}"
          f"{', API key required' if svc.api_key else ''})", flush=True)
    print(f"       open http://{here}:{a.port}/ in a browser to chat; close this window to stop the model", flush=True)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        # issue #26: reachable from other devices - say at which address, and what can still block it
        ips = lan_addresses()
        for ip in ips:
            print(f"       from other devices: http://{ip}:{a.port}/   (API: http://{ip}:{a.port}/v1)", flush=True)
        if not ips:
            print("       from other devices: http://<this PC's IP address>:" + str(a.port) + "/", flush=True)
        if not svc.api_key:
            print("       WARNING: no API key - anyone on your network can use this model. Add \"api_key\": \"...\" "
                  "to the config (clients send it as their API key; the web page asks for it)", flush=True)
        if os.name == "nt":
            print("       nothing arrives? Windows Firewall blocks it until allowed: accept its prompt for Python, or run "
                  "in an admin PowerShell:\n         New-NetFirewallRule -DisplayName \"Strata " + str(a.port) + "\" "
                  "-Direction Inbound -Protocol TCP -LocalPort " + str(a.port) + " -Action Allow -Profile Private\n"
                  "       (and set this network to Private in Windows' network settings)", flush=True)
    if a.open and cfg.get("open_browser") is not False:   # #609: the config's "open_browser": false wins (an older
        import webbrowser                                  # run-<model>.bat still passes --open)
        webbrowser.open(f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/")
    # #96: docker stop sends SIGTERM, which Python ignores by default, so the container's PID 1 would be killed after
    # the grace period with the engine still running. SIGTERM takes Ctrl+C's path below (QUIT to the engine).
    # SIGINT keeps Python's own handler, so Ctrl+C and a second Ctrl+C work as before.
    def on_sigterm(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, on_sigterm)
    except (ValueError, OSError, AttributeError):         # not the main thread
        pass
    try:
        while True:
            time.sleep(1)                               # Windows never delivers Ctrl+C to an untimed Event.wait()
    except KeyboardInterrupt:
        print("\n[strata] stopping (Ctrl+C again to end the engine at once) ...", flush=True)
        closers = [httpd.shutdown, getattr(engine, "close", None), vision.shutdown if vision else None,
                   hub.close if hub is not None else None]
        for close in filter(None, closers):
            try:
                close()
            except KeyboardInterrupt:                   # a second Ctrl+C: don't wait for the engine to free its memory
                if getattr(engine, "proc", None):
                    engine.proc.kill()
        try:
            from serve import cache_drop
            cache_drop.drop_after_exit(engine)           # opt-in (STRATA_DROP_CACHE_ON_EXIT=1), default unchanged
        except Exception as e:  # noqa: BLE001 - never block the exit
            print(f"[strata] could not release the model files' cache: {e}", flush=True)
        print("[strata] stopped", flush=True)
    return 0

