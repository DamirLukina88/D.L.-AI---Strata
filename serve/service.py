"""Service: the model's lifecycle, the FIFO, one request's generation, metrics and the MCP tool loop.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
from serve import images as images_api
from serve.frontend import ChatTemplate
from serve.frontend import Event
from serve.frontend import OutputParser
from serve.frontend import THINK_END
from serve.frontend import images_of
from serve.frontend import literal_tags
from serve.frontend import mark_think_literals
from serve.frontend import unmark_think_literals
from serve.mcp import McpCancelled
from typing import Iterator
import collections
import contextlib
import ctypes
import json
import os
import subprocess
import threading
import time
import uuid
from serve.late import server as _server
from serve.config import clean_shared_defaults
from serve.engine import (
    ConvCacheLog,
    DEGRADED_HEADROOM_GIB,
    Engine,
    StrataEngine,
    conversation_cache_view,
    conversation_slots,
    mem_available_gib,
)
from serve.engine_args import (
    child_env,
    combined_embeddings_path,
    engine_args,
    vision_env,
    write_temporary,
)
from serve.errors import (
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
from serve.request_stats import (
    answer_speed,
    prompt_tokens_seen,
    request_stats,
    request_timings,
)
from serve.textcore import (
    Detokenizer,
    StopMatcher,
    load_tokenizer_from_path,
    slot_filename_problem,
    stop_strings,
)
from serve.tunables import (
    ANSWER_RESERVE_MIN,
    ANSWER_ROOM_MIN_CAP,
    CTX_SLACK,
    EFFORT_TEXT,
    EFFORT_TURN,
    KEEPALIVE_S,
    LOOPBACK_NAMES,
    LOOP_CHECK_EVERY,
    LOOP_COVERAGE,
    RATE_MIN_SPAN_S,
    RATE_WINDOW_S,
    REASONING_CLOSE,
    REASONING_WRAP_UP,
    REPEAT_STOP_TOKENS,
    VISION_START,
    batch_slots_on,
    focused_recovery_prompt,
    reasoning_repeat_coverage,
)
from serve.vision import Vision


class Service:
    def __init__(self, engine: Engine, tokenizer, template: ChatTemplate, model_name: str = "qwen3.8-flash-next",
                 vision: Vision | None = None, sampling_defaults: dict | None = None,
                 fit_max_tokens: bool = False):
        self.engine, self.tok, self.template, self.model, self.vision = engine, tokenizer, template, model_name, vision
        self.literals = literal_tags(getattr(tokenizer, "control_tokens", ()))   # texts that stay text inside a message
        self.fit_max_tokens = fit_max_tokens          # --fit-max-tokens: clamp the output cap instead of 400
        self.aliases: list[str] = []                  # #297: other names of the model (the config's `aliases`)
        self.answer_room = True                       # 0.1.45: see ANSWER_ROOM_MIN_CAP (the config's "answer_room": false turns it off)
        self.reasoning_close_retry = False            # #1053 (opt-in): close the thinking once when a reply ends inside it
        self.codex_compaction_cache = False           # #924 (opt-in): a Codex compaction is rendered with its conversation's tools
        self.codex_thread_titles = False              # #923 (opt-in): answer Codex's thread-title turns without the engine
        self.sampling_defaults = dict(sampling_defaults or {})   # the run config's `sampling` block
        self.shared = {}                              # the web app's Chat settings for every client (POST /settings)
        self.shared_path = None                       # where they are kept between starts (next to the config)
        self.config_effort = None                     # #1641: the config's "reasoning_effort": the level for requests with none
        self.keep_awake = None                        # #1727 (opt-in): serve.keepawake.KeepAwake, the config's "prevent_sleep"
        self.fifo = threading.Lock()
        self.slot_save_path = None                    # --slot-save-path: /slots/0?action=save|restore (off when None)
        self.embeddings = threading.local()           # the current request's image embeddings file (GENI)
        self.api_key = ""                              # when set, /v1/* needs it (Bearer or x-api-key)
        # #458 (opt-in, the config's "effort_position": "end"): a non-default reasoning effort goes in a short system
        # turn before the answer instead of the top of the prompt, so switching it keeps the cached conversation
        self.effort_end = False
        self.conv_log = ConvCacheLog()                  # #596: the parked conversations, from the engine's log
        self.config_path = None                         # #564: the run config the web page's Settings view edits
        self.config_lock = threading.Lock()
        self.switch_lock = threading.Lock()
        # #321: browser pages of these origins may call /v1/* (CORS; "*" = any page - only with an api_key that
        # matters); empty = no CORS headers at all, as before
        self.cors_origins: list[str] = []
        # #321: origins that count as Strata's own page for /settings and MCP tools, e.g. the web app reached through a
        # reverse proxy or tunnel whose Host differs ("https://strata.example.com"); never a wildcard
        self.trusted_origins: list[str] = []
        # DNS rebinding: extra Host names this server answers to (the config's allowed_hosts, $STRATA_ALLOWED_HOSTS;
        # "*" = any), and every name it answers to, which serve() works out from the address it listens on
        self.allowed_hosts: list[str] = []
        self.host_names: set[str] = set(LOOPBACK_NAMES)
        self.status = {"busy": False, "queued": 0}      # GET /status: what the model is doing right now
        self.rate = collections.deque(maxlen=32)        # (time, generated) samples for the live tok/s window
        # "parallel" (the engine's batch slots): every running request's own status and rate window; self.status
        # then says busy while any runs and shows the newest one
        self.live_reqs: dict[int, tuple[dict, collections.deque]] = {}
        # #332: the API request monitor (/api-monitor) keeps the last 100 requests' prompts and answers in memory,
        # so it is off unless the config's "api_monitor" (or --api-monitor) turns it on
        self.api_monitor = False
        self.api_requests = collections.deque(maxlen=100)  # bounded I/O in memory; no headers or API keys
        self.request_trace = threading.local()
        self.history = collections.deque(maxlen=500)    # the last finished requests, newest last (GET /metrics)
        # since the server started (the Monitor's totals, issue #35)
        self.totals = {"since": time.time(), "requests": 0, "prompt_tokens": 0, "reused": 0, "output_tokens": 0,
                       "prompt_ms": 0.0, "decode_ms": 0.0,
                       "drafts_offered": 0, "drafts_accepted": 0}   # #457: the MTP drafts, summed where reported
        self.last_timings = None                         # the last finished request's, llama.cpp's names (/v1/status)
        # /metrics/prometheus' two throughput gauges need the totals as they stood at the last scrape, because
        # llama.cpp averages them over the window between two scrapes (#2341).
        self.scrape_bucket = (0, 0.0, 0, 0.0)
        from serve.prometheus import Latencies
        self.latencies = Latencies()                     # GET /metrics in Prometheus text: the latency histograms
        self.last_request_at = None                      # when a request last started or finished
        self.started_at = time.time()
        self.status_lock = threading.Lock()
        self.mcp = None                                  # serve/mcp.py's McpHub when MCP servers are configured
        # sharing the GPU with other programs (all off by default): unload the engine after this many idle seconds,
        # only start it again when this much VRAM is free, and run this command first (e.g. to unload another
        # server's model); the next request after an unload starts the engine again
        self.idle_unload_s = 0
        self.degraded_reload = True     # config "degraded_reload": false keeps a short-of-memory engine until /restart
        self.lazy = False
        self.min_free_vram_mib = 0
        self.before_load = None
        self.before_load_timeout_s = 120.0               # #1997: how long the before_load command may run
        self.before_load_ignore_failure = False          # #1997: load even when it fails, without a VRAM check
        self.vram_free_wait_s = 15.0                     # how long a full card is waited on (memory given back)
        self.before_load_strict = False                  # #1997: refuse (503) whenever it fails
        self.vram_reserve = None                         # #533: the last POST /v1/vram reserve (None: the start's)
        self.vram_reserve_asked = False                  # a POST /v1/vram was made (vram_reserve None is then asked)
        self.vision_held = False                         # an elastic encoder holds VRAM the expert cache gave it
        self.last_image_at = 0.0                         # when an image turn last ended (the elastic encoder's idle)
        self.reasoning_loop_recovery = False
        self.reasoning_budget_tokens = 0                 # #123: the config's default thinking budget (0: none)
        self.repeat_stop_tokens = REPEAT_STOP_TOKENS     # #606: one token this many times in a row ends a reply (0: off)
        self.anthropic_think_unasked = True               # #278: "anthropic_thinking": "on_request" -> False
        self.undeclared_tool_calls = "text"               # #4622: config "undeclared_tool_calls": "call" hands a call of an undeclared name to the client
        self.tool_call_recovery = False                   # opt-in: tool calls in forms next to the template's
        self.images = None                                # serve/images.py's ImageGen when the config has "images"
        self.restore_after_load = None                    # a session file an image job saved before it unloaded
        self.stop_ids = set(tokenizer.encode(_server().IM_END, parse_special=True) +
                            tokenizer.encode("<|endoftext|>", parse_special=True))
        # #567: a prompt re-encodes only what follows the last special token it shares with a recent prompt (the
        # same ids as a full encode: tools/strata_tokenizer.py PromptEncoder).  Tokenizers without resume points
        # encode in full.
        self.prompts = None
        if hasattr(tokenizer, "encode_marked") and hasattr(tokenizer, "max_special_len"):
            from strata_tokenizer import PromptEncoder
            # one kept prompt per conversation the engine's cache can hold (--conversation-cache-slots); the
            # encoder's own default without that setting
            slots = conversation_slots(engine)
            self.prompts = PromptEncoder(tokenizer, keep=slots) if slots is not None and slots > 0 \
                else PromptEncoder(tokenizer)

    def loaded(self) -> bool:
        return not hasattr(self.engine, "alive") or self.engine.alive()

    def slot_action(self, slot: str, action: str, filename) -> tuple[int, dict]:
        """llama-server's POST /slots/{id}?action=save|restore {"filename": ...}: the conversation the engine holds,
        to or from a file in slot_save_path.  -> (HTTP status, body)."""
        def error(code, message):
            return code, {"error": {"code": code, "message": message,
                                    "type": "invalid_request_error" if code < 500 else "server_error"}}
        if not self.slot_save_path or not hasattr(self.engine, "session_file"):
            return error(501, "slot save/restore is disabled (start the server with --slot-save-path DIR)")
        if getattr(self.engine, "batch", 0):
            # #465 parallel requests do not hold the FIFO and share the engine's control lines: a session file
            # could interleave with a request being admitted, so the two are not combined (the engine refuses too)
            return error(501, "slot save/restore is not available with parallel requests (\"parallel\" / --batch)")
        if slot != "0":
            return error(400, "this server has one slot: 0")
        if action not in ("save", "restore"):
            return error(400, "action must be save or restore")
        why = slot_filename_problem(filename)
        if why:
            return error(400, f"filename {why}")
        path = os.path.join(self.slot_save_path, filename)
        if action == "restore":
            try:
                os.lstat(path)                              # the engine opens it without following a link
            except OSError:
                return error(404, f"no saved session named {filename}")
        self.last_request_at = time.time()                  # the idle unload counts this as activity
        with self.status_lock:
            self.status["queued"] += 1
        waiting = True
        try:
            with self.fifo:
                with self.status_lock:
                    self.status["queued"] -= 1
                waiting = False
                if not self.loaded():
                    return error(503, "the model is not loaded")
                with self.status_lock:
                    self.status.update(busy=True, phase="saving the session" if action == "save"
                                       else "restoring a session", started=time.time(), first_token=None,
                                       prompt_tokens=None, generated=None, max_tokens=None)
                try:
                    if action == 'save' and getattr(self.engine, 'session_save_reclaim', False):
                        from serve.session_save_retry import session_file
                        r = session_file(self, action, path, SessionRefused)
                    else:
                        r = self.engine.session_file(action, path)
                except SessionRefused as e:
                    body = error(e.status, str(e))
                    body[1]["error"]["kind"] = e.kind
                    if e.published:
                        body[1]["error"]["published"] = True
                    return body
                except ValueError as e:                     # the request itself (an invalid command)
                    return error(400, str(e))
                finally:
                    with self.status_lock:
                        self.status["busy"] = False
                    self.last_request_at = time.time()
        finally:
            if waiting:                                     # never reached the FIFO (an exception while waiting)
                with self.status_lock:
                    self.status["queued"] -= 1
        if action == "save":
            return 200, {"id_slot": 0, "filename": filename, "n_saved": r["tokens"], "n_written": r["bytes"],
                         "timings": {"save_ms": r["ms"]}}
        return 200, {"id_slot": 0, "filename": filename, "n_restored": r["tokens"], "n_read": r["bytes"],
                     "timings": {"restore_ms": r["ms"]}}

    def set_aliases(self, aliases) -> None:
        """#297: the config's `aliases` - a list of names (or one comma-separated string), like llama-server's --alias.
        ValueError for anything else."""
        if aliases is None:
            aliases = []
        if isinstance(aliases, str):
            aliases = aliases.split(",")
        if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
            raise ValueError(f"aliases={aliases!r}: expected a list of model names")
        names = []
        for x in (x.strip() for x in aliases):
            if x and x != self.model and x not in names:
                names.append(x)
        self.aliases = names

    def model_names(self) -> list[str]:
        return [self.model, *self.aliases]

    def model_for(self, req) -> str:
        """The name to answer with: the request's own when it is the model's name or an alias (#297), else the model's.
        Other names are still served, as before."""
        asked = req.get("model") if isinstance(req, dict) else None
        return asked if isinstance(asked, str) and asked in self.aliases else self.model

    def reported_ctx(self) -> int:
        """The context the endpoints report (/v1/status, /v1/models, /props, /health, /slots, /metrics): the engine's,
        or the last one it reported while it restarts (max_context is 0 until READY, and a client that sizes its
        prompt from it would send nothing, #351).  Reporting only: requests are checked in prepare()."""
        return int(getattr(self.engine, "max_context", 0) or getattr(self.engine, "known_ctx", 0) or 0)

    def reasoning_budget(self, req) -> int | None:
        """#123: the most tokens this request may think, or None: the request's `reasoning_budget_tokens` (or, as
        llama.cpp reads it, `thinking_budget_tokens`), else the config's.  0 (or less) means no budget, so a request can
        turn a configured one off.  ValueError (a 400) for anything that is not a whole number."""
        req = req if isinstance(req, dict) else {}
        value = req.get("reasoning_budget_tokens", req.get("thinking_budget_tokens"))
        if value is None:
            value = self.reasoning_budget_tokens
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"reasoning_budget_tokens={value!r}: expected a whole number of tokens (0: no budget)")
        return value if value > 0 else None

    def _vision_down(self) -> bool:
        """The encoder should run and does not (the engine's load starts it again).  An elastic encoder is down
        between pictures by design: it starts in the image turn (_vision_up), not with the engine."""
        return (self.vision is not None and hasattr(self.vision, "alive") and not self.vision.alive()
                and not getattr(self.vision, "elastic", False))

    def _engine_reserve(self) -> int | None:
        """The VRAM the engine keeps free for other programs outside an elastic encoder's turn: the last POST /v1/vram
        reserve, or 0 when none was asked (the cache grows back to its full size; None would leave the reserve the engine
        started with, a segment or more below the size it had)."""
        return self.vram_reserve if self.vram_reserve_asked else 0

    def _vision_up(self):
        """The image turn's start for an elastic encoder that is not running (the caller holds self.fifo): the expert
        cache first keeps the encoder's elastic_mib of VRAM free on top of the reserve, then the encoder starts (load and
        warm-up, a few seconds).  If the cache cannot shrink (an engine without --vram-elastic, the resident low-RAM mode)
        the encoder starts anyway, as a non-elastic one would."""
        v = self.vision
        if not getattr(v, "elastic", False) or v.alive():
            return
        if v.elastic_mib > 0 and hasattr(self.engine, "vram") and self.loaded():
            try:
                out = self.engine.vram((self._engine_reserve() or 0) + v.elastic_mib)
                self.vision_held = True
                print(f"[strata] images: the expert cache keeps {v.elastic_mib} MiB free for the image encoder "
                      f"({out.get('expert_cache_mib')} of {out.get('expert_cache_full_mib')} MiB left)", flush=True)
            except ValueError as e:
                print(f"[strata] images: the expert cache did not make room for the image encoder ({e}); starting "
                      "it anyway", flush=True)
        if self.vision_held:
            time.sleep(0.2)          # the driver's free-VRAM counter shows the cache's release a moment later
        free0, t0 = self.free_vram_mib(), time.time()
        v.restart()
        free1 = self.free_vram_mib()
        took = f", {free0 - free1} MiB of VRAM" if free0 is not None and free1 is not None else ""
        print(f"[strata] images: the image encoder started in {time.time() - t0:.1f} s{took}", flush=True)

    def _vision_idle_down(self, force: bool = False) -> str:
        """An elastic encoder idle for elastic_idle_s (or force) stops, and the expert cache takes its VRAM back:
        "down", "busy" (a request holds the turn, or a picture came more recently) or "nothing" (not elastic or not
        holding anything)."""
        v = self.vision
        if not getattr(v, "elastic", False) or not (self.vision_held or v.alive()):
            return "nothing"
        if not force and time.time() - self.last_image_at < v.elastic_idle_s:
            return "busy"
        if not self.fifo.acquire(blocking=False):
            return "busy"
        try:
            v.unload()
            if self.vision_held and hasattr(self.engine, "vram") and self.loaded():
                out = self.engine.vram(self._engine_reserve())
                print(f"[strata] images: the image encoder stopped after {v.elastic_idle_s:g} s without a picture; "
                      f"the expert cache took its VRAM back ({out.get('expert_cache_mib')} of "
                      f"{out.get('expert_cache_full_mib')} MiB)", flush=True)
            self.vision_held = False
            return "down"
        finally:
            self.fifo.release()

    def start_vision_idle(self):
        v = self.vision
        if not getattr(v, "elastic", False):
            return
        print(f"[strata] images: the image encoder starts with the first picture and stops after {v.elastic_idle_s:g} s "
              f"without one; while it runs the expert cache keeps {v.elastic_mib} MiB free for it", flush=True)

        def loop():
            while True:
                time.sleep(max(1.0, min(30.0, v.elastic_idle_s / 4)))
                try:
                    self._vision_idle_down()
                except Exception as e:                 # tried again at the next turn; the thread keeps running
                    print(f"[strata] images: stopping the idle image encoder: {e}", flush=True)
        threading.Thread(target=loop, daemon=True).start()

    def free_vram_mib(self) -> int | None:
        """Free VRAM on the engine's (first) GPU, from NVML (AMD backend: amdgpu's sysfs files, #301); None when it can't
        be read (then nothing is refused)."""
        try:
            if getattr(self, "backend", None) == "hip":
                from serve.telemetry import free_vram_mib
                return free_vram_mib(int(getattr(self, "gpu_index", 0) or 0), amd=True)
            from serve.telemetry import _Nvml
            nv = _Nvml(int(getattr(self, "gpu_index", 0) or 0))
            if not nv.ok():
                return None
            m = nv.Mem()
            if nv.lib.nvmlDeviceGetMemoryInfo(nv.dev, ctypes.byref(m)) != 0:
                return None
            return int(m.free >> 20)
        except Exception:
            return None

    FATAL_GPU_MAX = 3            # fatal GPU errors of one engine within FATAL_GPU_WINDOW_S: after that it is not started again
    FATAL_GPU_WINDOW_S = 600.0

    def _note_fatal_gpu_exit(self, code) -> None:
        """#4350: the engine ends itself after a fatal GPU error (the device context cannot be used again) and says so in its last
        ERR line.  The next request starts it again, like any engine death, with one plain line here; the request that was in
        flight already failed with a 503.  Three such deaths within ten minutes mean a restart will not help (a bad card, driver or
        model state): then the server stops starting it and says so (503), until the ten minutes have passed."""
        why = getattr(self.engine, "last_err", None) or ""
        if "fatal GPU error" not in why:
            return
        pid = getattr(getattr(self.engine, "proc", None), "pid", None)
        seen = self.__dict__.setdefault("_fatal_gpu_pids", set())
        times = self.__dict__.setdefault("_fatal_gpu_times", [])
        now = time.time()
        if pid not in seen:                              # one death counts once, however many requests find it dead
            seen.add(pid)
            times.append(now)
        times[:] = [t for t in times if now - t < self.FATAL_GPU_WINDOW_S]
        print(f"[strata] the GPU reported a fatal error ({why[len('fatal GPU error:'):].strip()[:160]}); the engine ended "
              f"(exit code {code}) and is started again; the request that was running failed and can be sent again "
              f"({len(times)} of {self.FATAL_GPU_MAX} allowed in {self.FATAL_GPU_WINDOW_S / 60:g} minutes)", flush=True)
        if len(times) >= self.FATAL_GPU_MAX:
            raise EngineDied(f"the GPU reported a fatal error {len(times)} times in {self.FATAL_GPU_WINDOW_S / 60:g} minutes, so "
                             "the engine is not started again (the last: " + why[:160] + "). Check the graphics driver, the "
                             "card's temperature and power, and the log; a request after "
                             f"{self.FATAL_GPU_WINDOW_S / 60:g} minutes tries again")

    def ensure_loaded(self):
        """Start the engine if it is not running (unloaded, or it died - issue #27), after the before_load hook and
        the free-VRAM check.  The caller holds self.fifo."""
        if self.loaded() and not self._vision_down():
            return
        hook_failed = None
        if self.before_load:
            cmd = self.before_load
            print(f"[strata] before loading: {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}", flush=True)
            why = None
            try:
                r = subprocess.run(cmd, shell=isinstance(cmd, str), timeout=self.before_load_timeout_s,
                                   stdin=subprocess.DEVNULL)
                if r.returncode != 0:
                    why = f"it exited with code {r.returncode}"
            except subprocess.TimeoutExpired:
                why = f"it did not finish in {self.before_load_timeout_s:g} s (before_load_timeout_s)"
            except (OSError, subprocess.SubprocessError) as e:
                why = f"it could not run ({e})"
            if why is not None:
                # #1997: a failing hook (e.g. the other server's /unload that is still busy) may mean the GPU was not
                # given back.  A peer that is simply not running also makes `curl` fail (exit 7), so the exit code alone
                # does not refuse: the card's free VRAM decides (min_free_vram_mib, checked just below); "strict" always
                # refuses, "ignore" always loads.
                if self.before_load_strict and not self.before_load_ignore_failure:
                    print(f"[strata] the before_load command failed ({why}); the model stays unloaded and this "
                          "request is answered 503 - try again (before_load_strict)", flush=True)
                    raise GpuBusy(f"the before_load command failed ({why}): the GPU was not given back, so the "
                                  "model was not loaded; try again in a moment", retry_after=15)
                hook_failed = why
                if self.before_load_ignore_failure or not self.min_free_vram_mib:
                    print(f"[strata] the before_load command failed ({why}); loading anyway"
                          + ("" if self.before_load_ignore_failure else
                             " (set min_free_vram_mib to have the free VRAM checked, or before_load_strict to refuse)"),
                          flush=True)
                else:
                    print(f"[strata] the before_load command failed ({why}); checking the free VRAM", flush=True)
        if self.min_free_vram_mib and not (hook_failed and self.before_load_ignore_failure):
            free = self.free_vram_mib()
            deadline = time.time() + self.vram_free_wait_s   # memory another process just gave back can take a moment
            while free is not None and free < self.min_free_vram_mib and time.time() < deadline:
                time.sleep(0.5)
                free = self.free_vram_mib()
            if free is not None and free < self.min_free_vram_mib:
                if hook_failed and not self.before_load_ignore_failure:
                    print(f"[strata] the before_load command failed ({hook_failed}) and only {free} MiB of VRAM is "
                          f"free (the model needs {self.min_free_vram_mib}): not loading; 503", flush=True)
                raise GpuBusy(f"the GPU is in use by another program: {free} MiB of VRAM free, the model needs "
                              f"{self.min_free_vram_mib} (min_free_vram_mib) - it stays unloaded until that is free"
                              + (f"; the before_load command failed ({hook_failed})" if hook_failed else ""),
                              retry_after=15)
            if hook_failed and not self.before_load_ignore_failure:
                print(f"[strata] the before_load command failed ({hook_failed}), but {free} MiB of VRAM is free: "
                      "loading", flush=True)
        vision_started = False
        if self._vision_down():                         # first, as at a start: a GPU encoder takes its VRAM before
            print("[strata] starting the vision encoder ...", flush=True)   # the engine sizes its cache
            try:
                self.vision.restart()
            except Exception as e:
                raise EngineDied(f"the vision encoder failed to start: {e}") from e
            vision_started = True
        if self.loaded():
            return
        if getattr(self.engine, "unloaded", False):
            print("[strata] loading the model again (it was unloaded) ...", flush=True)
        else:
            code = self.engine.exit_code() if hasattr(self.engine, "exit_code") else None
            self._note_fatal_gpu_exit(code)
            print(f"[strata] the engine had stopped (exit code {code}); starting it again "
                  "(a minute or two) ...", flush=True)
        try:
            self.engine.restart()
        except Exception:
            if vision_started:
                self.vision.unload()
            raise
        print("[strata] the engine is running again", flush=True)
        if self.restore_after_load:                      # an image job unloaded it: its conversation comes back
            images_api.restore_session(self)
        if self.vram_reserve is not None and hasattr(self.engine, "vram"):   # #533: the reserve asked for last
            try:
                self.engine.vram(self.vram_reserve)
            except (ValueError, EngineDied) as e:
                print(f"[strata] the VRAM reserve ({self.vram_reserve} MiB) was not applied: {e}", flush=True)

    vram_wait_s = 300.0                                  # #533: how long POST /v1/vram waits for a running request

    def vram(self, reserve_mib: int | None) -> dict:
        """#533, POST /v1/vram: keep `reserve_mib` of VRAM free for other programs (None: the reserve the engine
        started with), applied between requests - a request that is running finishes first (up to wait_s).  Only an
        engine started with --vram-elastic (the config's "vram_elastic": true) can do it; it never resizes on its own.
        An unloaded engine applies it when it loads.  -> {"status": ..., and the engine's figures}."""
        if not hasattr(self.engine, "vram"):
            raise ValueError("this engine cannot resize its VRAM use")
        if not self.fifo.acquire(timeout=self.vram_wait_s):
            raise ModelBusy("a request is still running; try again when it has finished")
        # parallel requests do not hold the fifo: the engine's control lines (a prompt being admitted) are taken too,
        # and the engine refuses a resize while a slot decodes
        ctl = getattr(self.engine, "ctl", None) if getattr(self.engine, "batch", 0) else None
        if ctl is not None and not ctl.acquire(timeout=self.vram_wait_s):
            self.fifo.release()
            raise ModelBusy("a request is still running; try again when it has finished")
        try:
            if not self.loaded():
                self.vram_reserve, self.vram_reserve_asked = reserve_mib, True
                return {"status": "not loaded", "reserve_mib": reserve_mib,
                        "note": "applied when the model loads"}
            # an elastic encoder that runs keeps its VRAM on top of the asked reserve
            out = self.engine.vram((reserve_mib or 0) + self.vision.elastic_mib if self.vision_held else reserve_mib)
            self.vram_reserve, self.vram_reserve_asked = reserve_mib, True
            print(f"[strata] VRAM: {out.get('vram_free_mib')} MiB free, expert cache {out.get('expert_cache_mib')} of "
                  f"{out.get('expert_cache_full_mib')} MiB ({out.get('expert_slots')} experts)", flush=True)
            return {"status": "ok", **out}
        finally:
            if ctl is not None:
                ctl.release()
            self.fifo.release()

    def _say_died(self, e: Exception) -> None:
        """The server window's line for an engine that died (or was ended, #481) in the middle of a request."""
        note = self.engine.death_note() if hasattr(self.engine, "death_note") else ""
        log = getattr(self.engine, "log_path", None)
        print(f"[strata] {e}. {note} The next request starts the engine again."
              f"{' Its log: ' + log if log else ''}", flush=True)

    def load(self):
        """POST /load and every generation request: start the engine now if it is unloaded (raises GpuBusy)."""
        # a request is on its way: the idle thread must not unload between this and the request's own start
        self.last_request_at = time.time()
        if self.loaded() and not self._vision_down():
            return
        trace = getattr(self.request_trace, "record", None)
        waiting = time.perf_counter()
        with self.status_lock:                          # #1603: waiting for the fifo to start the engine is queued, not nothing
            self.status["queued"] += 1
        counted = True
        try:
            with self.fifo:
                with self.status_lock:
                    self.status["queued"] -= 1
                counted = False
                loading = time.perf_counter()
                if trace is not None:
                    with self.status_lock:
                        trace["queue_s"] += round(loading - waiting, 3)
                        trace["state"] = "loading"
                try:
                    self.ensure_loaded()
                finally:
                    if trace is not None:
                        with self.status_lock:
                            trace["load_s"] += round(time.perf_counter() - loading, 3)
                            trace["state"] = "queued"
        finally:
            if counted:
                with self.status_lock:
                    self.status["queued"] -= 1

    def end_engine_if_unchanged(self, born) -> bool:
        """End the engine after a request that ended without its end event (#3961), but only if it is still the engine process that request ran on
        (`born`, the engine's gen) and nobody is on it: the turn is taken without waiting, and held while the engine is ended, so a request admitted
        right after the lost one is never killed by it. A server with batch slots shares the engine between requests, so it is left alone. True when
        the engine was ended (the next request then starts it again)."""
        end = getattr(self.engine, "end_for_restart", None)
        if end is None or born is None or batch_slots_on(self.engine):
            return False
        if not self.fifo.acquire(blocking=False):              # the next request is already generating on it
            return False
        try:
            if getattr(self.engine, "gen", None) != born:      # it was ended or restarted since: that is another process
                return False
            end()
            return True
        finally:
            self.fifo.release()

    UNLOAD_WAIT_S = 300.0       # #1997: POST /unload?wait=1 waits this long for the running turn (wait=<s> to choose)

    def unload_waiting(self, wait_s: float) -> str:
        """#1997: unload(), but a running or queued request is waited for (up to wait_s) instead of answering "busy":
        a peer server that needs this GPU can then free the card on the server's terms.  "busy" after wait_s."""
        deadline = time.monotonic() + max(0.0, wait_s)
        while True:
            r = self.unload()
            if r != "busy" or time.monotonic() >= deadline:
                return r
            time.sleep(0.25)

    def unload(self, idle_for: float | None = None) -> str:
        """Stop the engine between requests: "unloaded", "not loaded", "busy" (a request is running or waiting, or
        with idle_for: one ran more recently than that) or "unsupported"."""
        if not hasattr(self.engine, "unload"):
            return "unsupported"
        if not self.fifo.acquire(blocking=False):
            return "busy"
        try:
            if not self.engine.alive():
                return "not loaded"
            with self.status_lock:
                if self.status.get("busy") or self.status.get("queued"):
                    return "busy"
            if idle_for is not None and time.time() - (self.last_request_at or self.started_at) < idle_for:
                return "busy"
            self.engine.unload()
            if self.vision is not None and hasattr(self.vision, "unload"):
                self.vision.unload()
            self.vision_held = False
            print(f"[strata] model unloaded{f' after {idle_for:.0f} s idle' if idle_for else ''}; "
                  "the next request loads it again", flush=True)
            return "unloaded"
        finally:
            self.fifo.release()

    def force_restart(self, reload: bool = True) -> str:
        """Forcefully kill and restart or unload the engine immediately (stopping any stuck requests).
        reload=False: only unload, even when the config is not lazy (switch_model replaces the engine next)."""
        print("[strata] forceful restart requested...", flush=True)
        if hasattr(self.engine, "proc") and self.engine.proc is not None:
            try:
                self.engine.proc.kill()
            except OSError:
                pass
            try:
                self.engine.proc.wait(timeout=5)
            except Exception:
                pass
        if hasattr(self.engine, "close"):
            try:
                self.engine.close()
            except Exception:
                pass
        with self.status_lock:
            self.status["busy"] = False
            # not "queued": each request still waiting takes itself off when it gets the turn (a reset left -1, and
            # unload() answered "busy" from then on)
            self.status["state"] = "idle"
            self.status["detail"] = "Restarted"
            self.status.pop("started", None)
            self.status.pop("first_token", None)
        self.live_reqs.clear()

        if not reload or getattr(self, "lazy", False) or getattr(self.engine, "unloaded", False):
            self.engine.unloaded = True
            self.engine.ended = True
            if hasattr(self.engine, "info") and isinstance(self.engine.info, dict):
                v = self.engine.info.get("version")
                self.engine.info = {"version": v} if v is not None else {}
            print("[strata] engine stopped and marked unloaded; ready for next request", flush=True)
            return "unloaded"
        else:
            try:
                self.engine.restart()
                print("[strata] engine restarted successfully", flush=True)
                return "restarted"
            except Exception as e:
                print(f"[strata] engine restart error: {e}", flush=True)
                return f"error: {e}"

    def available_models(self) -> list[dict]:
        """List all available model configurations on this server."""
        configs = []
        for cfg_file in sorted(_server().ROOT.glob("strata-*.json")):
            if cfg_file.name.endswith(".shared-settings.json"):     # the Chat settings, not a model
                continue
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
                if not (isinstance(data, dict) and data.get("exe") and isinstance(data.get("args"), list)):
                    continue                                         # only engine configs, as strata_bench.find_configs
                m_id = data.get("model_name") or cfg_file.stem.replace("strata-", "")
                d_name = data.get("display_name") or m_id
                configs.append({
                    "id": m_id,
                    "name": d_name,
                    "config": cfg_file.name,
                    "active": m_id == self.model,
                    "loaded": (m_id == self.model and self.loaded())
                })
            except Exception:
                pass
        return configs

    def switch_model(self, target: str) -> dict:
        """Switch active model to target id or config filename on the fly."""
        if not self.switch_lock.acquire(blocking=False):
            raise ModelBusy("A model switch is already in progress; please wait.")
        try:
            models = self.available_models()
            match = next((m for m in models if m["id"] == target or m["config"] == target or m["name"] == target), None)
            if not match:
                raise ValueError(f"Model {target!r} not found in available configurations")

            target_id = match["id"]
            target_config = _server().ROOT / match["config"]

            if self.model == target_id:
                if self.loaded():
                    print(f"[strata] model {target_id} is already loaded and active", flush=True)
                    return {"status": "already_loaded", "model": self.model, "name": match["name"]}
                else:
                    print(f"[strata] model {target_id} matches active configuration; loading now...", flush=True)
                    self.load()
                    return {"status": "loaded", "model": self.model, "name": match["name"]}

            with open(target_config, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)

            # Pre-validate that model files exist BEFORE unloading anything
            args = cfg.get("args", [])
            for opt in ("--pack", "--native", "--ple-gguf"):
                if opt in args:
                    idx = args.index(opt)
                    if idx + 1 < len(args):
                        fpath = Path(args[idx + 1])
                        if not fpath.exists():
                            raise FileNotFoundError(
                                f"Model files for {match['name']} are not downloaded yet ({fpath}). "
                                "Download or setup the model weights first."
                            )

            tpath = Path(cfg["tokenizer"])
            if not tpath.exists():
                raise FileNotFoundError(f"Tokenizer directory for {match['name']} does not exist: {tpath}")

            tok = load_tokenizer_from_path(tpath)
            exe = cfg["exe"] if os.path.isabs(cfg["exe"]) else os.path.abspath(os.path.join(cfg.get("cwd") or ".", cfg["exe"]))
            env = child_env(cfg)
            lazy = cfg.get("lazy_load") is True

            print(f"[strata] switching model from {self.model} to {target_id}...", flush=True)
            if self.loaded() or (hasattr(self.engine, "alive") and self.engine.alive()):
                print(f"[strata] unloading previous model {self.model}...", flush=True)
                # not a restart: with a config that is not lazy it loaded the old model again, and the new engine
                # below replaced it without closing it (two engines on the card, the old process orphaned)
                self.force_restart(reload=False)
                # Give Linux kernel and ROCm driver a moment to unpin/reclaim memory
                time.sleep(2.0)

            engine = StrataEngine(exe, engine_args(cfg), cwd=cfg.get("cwd"), log=cfg.get("log"), env=env, lazy=lazy, cfg=cfg)
            self.engine = engine
            self.tok = tok
            self.model = target_id
            self.config_path = str(target_config)
            self.lazy = lazy
            tpl = tpath / "chat_template.jinja"
            self.template = ChatTemplate(tpl if tpl.exists() else _server().ROOT / "serve/chat_template.jinja")
            if "idle_unload_s" in cfg:
                self.idle_unload_s = float(cfg["idle_unload_s"])

            if getattr(self, "vision", None) is not None:
                try:
                    self.vision.unload()
                except Exception:
                    pass
                self.vision = None

            if cfg.get("vision"):
                vcfg = {k: (os.path.abspath(os.path.join(cfg.get("cwd") or ".", v))
                            if k in ("exe", "mmproj", "model") and isinstance(v, str) and not os.path.isabs(v) else v)
                        for k, v in cfg["vision"].items()}
                self.vision = Vision(vcfg, log=open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None,
                                     env=vision_env(cfg, env), lazy=lazy)

            if not lazy:
                self.load()
                return {"status": "switched_and_loaded", "model": self.model, "name": match["name"]}
            else:
                return {"status": "switched", "model": self.model, "name": match["name"], "lazy": True}
        finally:
            self.switch_lock.release()



    def start_idle_unload(self):
        if not self.idle_unload_s or not hasattr(self.engine, "unload"):
            return
        print(f"[strata] the model unloads after {self.idle_unload_s} s without requests", flush=True)

        def loop():
            while True:
                time.sleep(max(1.0, min(30.0, self.idle_unload_s / 4)))
                try:
                    self.unload(idle_for=self.idle_unload_s)
                except EngineStuck as e:                # tried again at the next turn; the thread keeps running
                    print(f"[strata] idle unload: {e}", flush=True)
        threading.Thread(target=loop, daemon=True).start()

    def reload_degraded(self, idle_s: float = 60.0, gap_s: float = 600.0, avail=mem_available_gib) -> str:
        """Start the engine again when it started short of memory (engine.degraded) and that memory is free now:
        only between requests, after idle_s without one, at most once per gap_s.  "fine", "waiting" (too soon after
        the last try), "busy", "no memory" or "reloaded" / "still short"."""
        d = getattr(self.engine, "degraded", None)
        if not d or not getattr(self.engine, "alive", lambda: False)():
            return "fine"
        now = time.time()
        if now - getattr(self, "_degraded_try", 0.0) < gap_s:
            return "waiting"
        # the running engine gives back what it holds when it stops
        if avail() + d["kept_gib"] < d["wanted_gib"] + DEGRADED_HEADROOM_GIB:
            return "no memory"
        if not self.fifo.acquire(blocking=False):
            return "busy"
        try:
            with self.status_lock:
                if self.status.get("busy") or self.status.get("queued"):
                    return "busy"
            if now - (self.last_request_at or self.started_at) < idle_s:
                return "busy"
            self._degraded_try = now
            print(f"[strata] the engine started short of memory and {avail():.1f} GiB is free now: starting it again",
                  flush=True)
            self.engine.restart()
            again = getattr(self.engine, "degraded", None)
            print("[strata] " + ("still short of memory after the restart" if again else "engine reloaded with the "
                                 "whole resident RAM mode"), flush=True)
            return "still short" if again else "reloaded"
        except Exception as e:  # noqa: BLE001 - the next request starts it as usual
            print(f"[strata] reload after a short-of-memory start failed: {e}", flush=True)
            return f"error: {e}"
        finally:
            self.fifo.release()

    def start_degraded_reload(self):
        if not self.degraded_reload or not hasattr(self.engine, "restart"):
            return

        def loop():
            while True:
                time.sleep(30.0)
                try:
                    self.reload_degraded()
                except Exception as e:  # noqa: BLE001 - the loop keeps running
                    print(f"[strata] degraded reload: {e}", flush=True)
        threading.Thread(target=loop, daemon=True).start()

    def set_shared(self, defaults) -> dict:
        """The Chat settings every client gets for what it leaves out; {} / None = clients use their own again."""
        self.shared = clean_shared_defaults(defaults)
        if self.shared_path:
            try:
                if self.shared:
                    Path(self.shared_path).write_text(json.dumps(self.shared, indent=1), encoding="utf-8")
                else:
                    Path(self.shared_path).unlink(missing_ok=True)
            except OSError as e:
                print(f"[strata] could not save the shared settings: {e}", flush=True)
        return self.shared

    def effort_default(self) -> str | None:
        """The thinking level of a request that names none: the Chat settings shared with apps first, then the config's
        "reasoning_effort" (#1641).  Every API reads it here (the Responses API did not: 0.1.44.1)."""
        return self.shared.get("reasoning_effort") or self.config_effort

    def with_shared(self, req: dict, api: str) -> dict:
        """The request with the shared thinking level and max tokens filled in where it has none of its own."""
        s = self.shared
        effort = self.effort_default()
        if not s and not effort:
            return req
        req = dict(req)
        if "max_tokens" in s and not req.get("max_tokens") and not req.get("max_completion_tokens"):
            req["max_tokens"] = s["max_tokens"]
        if effort:
            if api == "openai":
                ctk = req.get("chat_template_kwargs") if isinstance(req.get("chat_template_kwargs"), dict) else {}
                if req.get("reasoning_effort") in (None, "") and not req.get("reasoning") and \
                        "enable_thinking" not in ctk and "reasoning_effort" not in ctk:
                    req["reasoning_effort"] = effort
            elif not req.get("thinking") and not req.get("output_config"):
                if effort == "none":
                    req["thinking"] = {"type": "disabled"}
                elif getattr(self, "anthropic_think_unasked", True):
                    req["output_config"] = {"effort": effort}
        return req

    def start_telemetry(self):
        """The hardware sampler behind GET /metrics (serve/telemetry.py), recording this server's tok/s too."""
        if getattr(self, "telemetry", None) is None:
            from serve.telemetry import Telemetry
            self.telemetry = Telemetry(extra=lambda: {"tok_s": self._tok_s(), "tok_s_mean": self._tok_s_mean(),
                                                    "prefill_tok_s_mean": self._prefill_tok_s_mean()},
                                       gpu_index=int(getattr(self, "gpu_index", 0) or 0),
                                       gpu_indices=getattr(self, "gpu_indices", None),
                                       amd=getattr(self, "backend", None) == "hip")
            if getattr(self, "engine", None) is not None and hasattr(self.engine, "gpu_busy"):
                # #1317: the quick frozen-engine check does not end an engine whose GPU is busy (a long prompt chunk on a
                # slow card keeps the GPU at work while the host thread sleeps)
                self.engine.gpu_busy = lambda: (self.telemetry.snapshot()["now"].get("gpu_util") or 0) >= 10

    def _tok_s(self):
        """tok/s over the last RATE_WINDOW_S seconds.  Returns 0.0 while nothing is generating.  With parallel requests:
        the sum of theirs."""
        with self.status_lock:
            many = [(dict(st), list(rt)) for st, rt in self.live_reqs.values()]
        if many:
            return sum(self._rate_of(st, rt) for st, rt in many)
        with self.status_lock:
            s = dict(self.status)
            rate = list(self.rate)
        return self._rate_of(s, rate)

    @staticmethod
    def _rate_of(s, rate):
        if not s.get("busy") or not s.get("first_token"):
            return 0.0
        now = time.time()
        newest = rate[-1] if rate else None
        oldest = next(((t, g) for t, g in rate if now - t <= RATE_WINDOW_S), None)
        if newest and oldest and newest[0] - oldest[0] >= RATE_MIN_SPAN_S:
            return max(0.0, (newest[1] - oldest[1]) / (newest[0] - oldest[0]))
        return s["generated"] / max(RATE_MIN_SPAN_S, now - s["first_token"])

    def _tok_s_mean(self):
        """The whole-request mean since the first token (the old formula), kept so the two can be compared."""
        with self.status_lock:
            many = [dict(st) for st, _ in self.live_reqs.values()] or [dict(self.status)]
        return sum(s["generated"] / max(1e-6, time.time() - s["first_token"]) for s in many
                   if s.get("busy") and s.get("first_token"))

    def _prefill_tok_s_mean(self):
        """Engine-reported mean over newly read tokens, excluding the cached prefix."""
        with self.status_lock:
            reading = self.status.get("busy") and self.status.get("first_token") is None
        return getattr(self.engine, "prefill_tok_s_mean", None) if reading else 0.0

    def begin_request(self, path, req):
        """#332: a monitor record for this request, or None when the monitor is off (nothing is kept then)."""
        if not self.api_monitor:
            return None
        raw = json.dumps(req, ensure_ascii=False, indent=2)
        record = {"id": uuid.uuid4().hex[:12], "path": path, "model": req.get("model") or self.model,
                  "started_at": time.time(), "state": "queued", "stream": bool(req.get("stream")),
                  "response_format": (req.get("response_format") or {}).get("type")
                  if isinstance(req.get("response_format"), dict) else None,
                  "input": raw[:262144], "input_truncated": len(raw) > 262144,
                  "output": "", "reasoning": "", "output_truncated": False, "reasoning_truncated": False,
                  "queue_s": 0.0, "load_s": 0.0, "first_token_s": None,
                  "_clock": time.perf_counter()}
        with self.status_lock:
            self.api_requests.append(record)
        self.request_trace.record = record
        return record

    def request_records(self, request_id=None):
        with self.status_lock:
            records = list(self.api_requests)
            if request_id:
                record = next((r for r in records if r["id"] == request_id), None)
                if record is None:
                    return None
                return {k: v for k, v in record.items() if not k.startswith("_")}
            return [{k: v for k, v in r.items()
                     if k not in ("input", "output", "reasoning", "response") and not k.startswith("_")}
                    | {"wallclock_s": r.get("wallclock_s", round(time.perf_counter() - r["_clock"], 3))}
                    for r in reversed(records)]

    def metrics(self, all_requests=False) -> dict:
        """GET /metrics: what the Monitor tab shows - the engine's facts, what it is doing, the last requests, and
        the hardware (with a minute of history per series)."""
        with self.status_lock:
            s = dict(self.status)
            if self.live_reqs:                          # parallel requests: the newest one's status
                s = {**s, **dict(list(self.live_reqs.values())[-1][0]), "queued": s.get("queued", 0)}
            hist = list(self.history)
            totals = dict(self.totals)
        now = time.time()
        progress = getattr(self.engine, "progress", None)
        if s.get("busy") and s.get("first_token") is None:
            state = "reading"
        elif s.get("busy"):
            state = "generating"
        elif not self.loaded():
            state = "unloaded"
        else:
            state = "idle"
        live = {"state": state, "queued": s.get("queued", 0), "phase": s.get("phase") if s.get("busy") else None,
                "prompt_tokens": s.get("prompt_tokens") if s.get("busy") else None,
                "prompt_read": None, "prompt_total": None, "generated": s.get("generated") if s.get("busy") else None,
                "max_tokens": s.get("max_tokens") if s.get("busy") else None,
                "elapsed_s": round(now - s["started"], 1) if s.get("busy") and s.get("started") else None,
                "tok_s": round(self._tok_s(), 1) if state == "generating" else None,
                "tok_s_mean": round(self._tok_s_mean(), 1) if state == "generating" else None,
                "prefill_tok_s_mean": getattr(self.engine, "prefill_tok_s_mean", None) if s.get("busy") else None,
                "tok_s_window_s": RATE_WINDOW_S if state == "generating" else None}
        if state == "reading" and progress:
            live["prompt_read"], live["prompt_total"] = progress
        par = int(getattr(self.engine, "batch", 0) or 0)
        if par:                                         # #465: the requests running together, slot by slot
            with self.status_lock:
                running = len(self.live_reqs)
            slots = self.engine.slots_view() if hasattr(self.engine, "slots_view") else []
            # the requests in flight that are not in a slot: the one alone on the solo path, or waiting their turn
            in_slots = sum(1 for x in slots if x["state"] != "idle")
            live.update(parallel=par, running=running, slots=slots, outside_slots=max(0, running - in_slots),
                        waiting=int(getattr(self.engine, "waiting", 0) or 0),
                        admitting=int(getattr(self.engine, "admitting", 0) or 0))
            if running and state == "idle":
                live["state"] = "generating"
        if hasattr(self.engine, "replica_view"):        # opt-in replicas: each one's state and requests routed to it
            live["replicas"] = self.engine.replica_view()
        is_loaded = self.loaded()
        engine_info = dict(getattr(self.engine, "info", {}) or {}) if is_loaded else {
            k: v for k, v in (getattr(self.engine, "info", {}) or {}).items() if k in ("version",)
        }
        engine = {"model": self.model, "max_context": self.reported_ctx(), "images": self.vision is not None,
                  **engine_info}
        # D.L. AI: with lazy_load the engine reports cvec only once it is loaded; the Sampling drawer's projection
        # switch must also show (and its saved value survive a Save) while the model is unloaded
        spawn_args = (getattr(self.engine, "spawn", None) or (None, []))[1]
        if any(a in ("--control-vector", "--control-vector-scaled") for a in spawn_args):
            engine["cvec_configured"] = True
        tel = self.telemetry.snapshot() if getattr(self, "telemetry", None) else {"now": {}, "history": {}, "static": {}}
        parked = self.conv_log.poll(getattr(self.engine, "log_path", None), getattr(self.engine, "log_start", None))
        return {"engine": engine, "live": live, "requests": hist[::-1][:None if all_requests else 12],
                "conversation_cache": conversation_cache_view(engine, hist, totals, parked),
                "requests_kept": len(hist), "totals": totals, "hardware": tel["now"],
                "hardware_static":
                tel["static"], "history": tel["history"], "time": now}

    def prometheus(self) -> str:
        """GET /metrics/prometheus: the totals and what is running in Prometheus' text format, under llama-server's
        metric names (llamacpp:*) so its dashboards work unchanged; the drafts and requests as strata:*."""
        with self.status_lock:
            s, t = dict(self.status), dict(self.totals)
            running = len(self.live_reqs) or int(bool(s.get("busy")))
            prompt_n = t["prompt_tokens"] - t["reused"]               # what was read, as llama.cpp counts it
            prompt_s, decode_s = t["prompt_ms"] / 1000, t["decode_ms"] / 1000
            # llama.cpp reads these two gauges from a bucket it resets on every scrape (server_metrics::bucket,
            # "the gauges are averaged over the window between two scrapes"), so an idle server reports 0 rather
            # than its lifetime average. Keep the same window here, or the names lie to llama.cpp dashboards.
            was_prompt_n, was_prompt_s, was_predicted_n, was_decode_s = self.scrape_bucket
            self.scrape_bucket = (prompt_n, prompt_s, t["output_tokens"], decode_s)
        d_prompt_n, d_prompt_s = prompt_n - was_prompt_n, prompt_s - was_prompt_s
        d_predicted_n, d_decode_s = t["output_tokens"] - was_predicted_n, decode_s - was_decode_s
        rows = [
            ("llamacpp:prompt_tokens_total", "counter", "Prompt tokens read", prompt_n),
            ("llamacpp:prompt_tokens_cached_total", "counter", "Prompt tokens the conversation cache already held",
             t["reused"]),
            ("llamacpp:prompt_seconds_total", "counter", "Prompt read time", prompt_s),
            ("llamacpp:tokens_predicted_total", "counter", "Tokens generated", t["output_tokens"]),
            ("llamacpp:tokens_predicted_seconds_total", "counter", "Generation time", decode_s),
            ("llamacpp:prompt_tokens_seconds", "gauge", "Average prompt read throughput in tokens/s, since the last scrape",
             d_prompt_n / d_prompt_s if d_prompt_s > 0 else 0),
            ("llamacpp:predicted_tokens_seconds", "gauge", "Average generation throughput in tokens/s, since the last scrape",
             d_predicted_n / d_decode_s if d_decode_s > 0 else 0),
            ("llamacpp:requests_processing", "gauge", "Requests running", running),
            ("llamacpp:requests_deferred", "gauge", "Requests waiting their turn", s.get("queued") or 0),
            ("strata:requests_total", "counter", "Requests finished", t["requests"]),
            ("strata:drafts_offered_total", "counter", "Speculative draft tokens offered", t["drafts_offered"]),
            ("strata:drafts_accepted_total", "counter", "Speculative draft tokens accepted", t["drafts_accepted"]),
            ("strata:tool_calls_unread_total", "counter", "<tool_call> blocks returned as text (an undeclared name or a form the template does not use)",
             t.get("tool_calls_unread", 0)),
            ("strata:tool_args_repaired_total", "counter", "Tool call arguments (a JSON array or object) that were damaged and read as written",
             t.get("tool_args_repaired", 0)),
            ("strata:model_loaded", "gauge", "1 while the model is loaded", int(self.loaded())),
        ]
        return "".join(f"# HELP {name} {help_}\n# TYPE {name} {kind}\n{name} {value}\n"
                       for name, kind, help_, value in rows)

    def v1_status(self) -> dict:
        """GET /v1/status: what this server is and does, for a client that would rather ask than guess (a front-end
        that polls its OpenAI-compatible server's status, collabosm's for one): the model and its window, images,
        the APIs, what is running, and the last request's timings in llama.cpp's names.  /metrics has the rest."""
        with self.status_lock:
            s, totals = dict(self.status), dict(self.totals)
            last_t, last_at = (dict(self.last_timings) if self.last_timings else None), self.last_request_at
        tel = self.telemetry.snapshot() if getattr(self, "telemetry", None) else {"now": {}, "static": {}}
        hw, static = tel.get("now") or {}, tel.get("static") or {}

        def scaled(v, unit, digits=0):
            return round(v / unit, digits) if isinstance(v, (int, float)) else None

        busy, ctx = bool(s.get("busy")), self.reported_ctx()
        images = self.vision is not None
        return {
            "service": "strata", "model": self.model,
            "loaded": self.loaded(), "auto_load": hasattr(self.engine, "restart"),
            "structured_output": {"formats": ["json_object", "json_schema"], "method": "prompt_and_validate",
                                  "constrained_decoding": False, "stream_buffered": True},
            "engine": (getattr(self.engine, "info", {}) or {}).get("version"),
            "started": int(self.started_at), "uptime_s": int(time.time() - self.started_at),
            "cache_max_tokens": ctx,
            "context": {"native": ctx, "max_positions": ctx},
            # one request at a time (more wait their turn), or "parallel": N batch slots (#465)
            "concurrency": {"serving": max(1, int(getattr(self.engine, "batch", 0) or 0)),
                            "requested": max(1, int(getattr(self.engine, "batch", 0) or 0))},
            "dialects": ["/v1/chat/completions", "/v1/completions", "/v1/messages", "/v1/responses"],
            "vision": {"enabled": images, "available": images, "error": None},
            "image_generation": self.images.status() if self.images is not None else {"enabled": False},
            "activity": {"requests": totals["requests"] + int(busy), "in_flight": int(busy) + int(s.get("queued") or 0),
                         "last_request_at": int(last_at) if last_at else None},
            "last_timings": last_t,
            "vram": dict((getattr(self.engine, "info", {}) or {}).get("vram") or {},
                         elastic=bool((getattr(self.engine, "info", {}) or {}).get("vram_elastic"))),
            "machine": {
                "at": int(time.time()),
                "gpu": {"name": static.get("gpu_name"), "used_mib": scaled(hw.get("gpu_mem_used"), 2 ** 20),
                        "total_mib": scaled(hw.get("gpu_mem_total"), 2 ** 20), "util_pct": hw.get("gpu_util"),
                        "temp_c": hw.get("gpu_temp"), "power_w": hw.get("gpu_power")} if static.get("gpu_name") else None,
                "ram": {"used_gib": scaled(hw.get("ram_used"), 2 ** 30, 1),
                        "total_gib": scaled(hw.get("ram_total"), 2 ** 30, 1)} if hw.get("ram_total") else None}}

    def render_prompt(self, messages, tools, kwargs) -> str:
        """The template rendered.  #458: with `effort_end`, a request with a non-default effort (low, medium or no
        thinking) is rendered as a default one up to the answer - the same prompt start, so the conversation cache
        keeps it - and its effort follows in a short system turn right before the answer (thinking off: the template's
        empty thinking block).  The engine (--tail-role-token) checkpoints in front of that turn."""
        effort = kwargs.get("reasoning_effort")
        off = kwargs.get("enable_thinking") is False
        if not self.effort_end or (not off and effort in (None, "", "xhigh", "high")):
            return self.template.render(messages, tools=tools, **kwargs)
        base = {k: v for k, v in kwargs.items() if k not in ("reasoning_effort", "enable_thinking")}
        history = self.template.render(messages, tools=tools, add_generation_prompt=False, **base)
        full = self.template.render(messages, tools=tools, add_generation_prompt=True, **kwargs)
        mine = self.template.render(messages, tools=tools, add_generation_prompt=False, **kwargs)
        if not full.startswith(mine):                  # a template this cannot take apart: rendered as asked
            return full
        tail = "" if off else EFFORT_TURN.format(EFFORT_TEXT.get(effort, EFFORT_TEXT["medium"]))
        return history + tail + full[len(mine):]

    def encode_prompt(self, messages, tools, kwargs, store: bool = True) -> list[int]:
        """The request's prompt: the template rendered and tokenized.  #537: a <think> / </think> written inside a
        message's text is encoded as the text it is, not as the model's reasoning markers (the template's own are).
        A control token's text (<|im_start|>, <|im_end|>, <|endoftext|>, ...) inside a message is text as well: only
        the control tokens the template writes are control tokens.  `store=False` (a token count) reuses the kept
        prompts without adding or replacing one."""
        marked, marked_tools, changed = mark_think_literals(messages, tools, self.literals)
        prompt = self.render_prompt(marked, marked_tools, kwargs)
        plain = ()
        if changed:
            prompt, plain = unmark_think_literals(prompt, self.literals)
        if self.prompts is not None:            # #567: only what follows the last special shared with a recent prompt
            return self.prompts.encode(prompt, plain, store)
        return self.tok.encode(prompt, parse_special=True, plain=plain) if plain else \
            self.tok.encode(prompt, parse_special=True)

    @contextlib.contextmanager
    def _turn(self, cancel=None):
        """The engine's single turn (self.fifo) for an image encode.  #1999: a client that leaves while this request
        waits for it gives its place up (ClientGone), as a queued generation does (#1619)."""
        if cancel is None:
            self.fifo.acquire()
        else:
            while not self.fifo.acquire(timeout=0.25):
                if cancel.is_set():
                    raise ClientGone()
        try:
            yield
        finally:
            self.fifo.release()

    def _note_unreadable_tool_images(self, messages, cancel=None):
        """A picture a tool returned (Claude Code's Read of an image file) that this server cannot read - it has no
        image encoder, or the encoder refuses that picture - becomes a short note in its place instead of a 400.
        Clients resend the whole history every turn, so one unreadable tool picture would fail every later request of
        the conversation; a picture the user sends keeps the 400.  A picture that encodes stays in the cache, so the
        prompt's own encode below finds it."""
        fetched = {}                     # a URL's bytes, so prepare() does not download the same picture again
        for m in messages:
            content = m.get("content")
            if m.get("role") != "tool" or not isinstance(content, list):
                continue
            for n, item in enumerate(content):
                if not isinstance(item, dict) or item.get("type") != "image":
                    continue
                why = "this server has no image encoder" if self.vision is None else None
                if why is None:
                    src = item["source"]
                    try:
                        if cancel is not None and cancel.is_set():
                            raise ClientGone()
                        if src.startswith(("http://", "https://")):
                            src = fetched[item["source"]] = Vision.download(src)   # outside the FIFO, as in prepare()
                        with self._turn(cancel):  # the encoder takes its turn with the requests (see below)
                            self._vision_up()         # an elastic encoder is not running until a picture needs it
                            self.vision.encode(src)
                    except (ValueError, OSError, RuntimeError) as e:    # RuntimeError: the encoder did not start
                        why = str(e)
                if why is not None:
                    print(f"[strata] a picture a tool returned was left out of the prompt: {why}", flush=True)
                    content[n] = {"type": "text", "text": f"[image omitted: {why}]"}
        return fetched

    def forget_prompt(self, ids):
        if self.prompts is not None:
            self.prompts.forget(ids)

    def prepare(self, messages, tools, kwargs, max_new=None, force=None, req=None, cancel=None):
        """-> (ids, thinking, max_new). An unset or non-positive max_new (some clients send -1) means "unlimited":
        the rest of the context.  `force` (forced_call): without thinking the reply starts with it, so it ends the
        prompt; with thinking, Service.run writes it once the thinking is over."""
        # `cancel` (#1999): set when the client hangs up; the downloads, the wait for the turn and the encodes stop
        # between pictures and raise ClientGone
        fetched = self._note_unreadable_tool_images(messages, cancel)
        ids = encoded_ids = self.encode_prompt(messages, tools, kwargs)
        if force and kwargs.get("enable_thinking", True) is False:
            ids = ids + self.tok.encode(force, parse_special=True)
        self.embeddings.path = None
        self.embeddings.keys = None
        images = images_of(messages)
        if images:
            if self.vision is None:
                raise ValueError("this server was started without the vision encoder (run setup again and choose "
                                 "'vision'), so it cannot read images")
            pad = self.tok.encode(_server().IMAGE_PAD, parse_special=True)[0]
            start = self.tok.encode(VISION_START, parse_special=True)[0]
            # An image URL is downloaded first, outside the FIFO: under it, a slow server held every other request
            # for as long as urlopen waited.
            def fetch(src):
                if cancel is not None and cancel.is_set():
                    raise ClientGone()
                return fetched[src] if src in fetched else Vision.download(src) \
                    if src.startswith(("http://", "https://")) else src
            images = [fetch(src) for src in images]
            # Encode only while the engine is idle: the engine and the image encoder (a separate process) must not
            # run on the GPU at the same time - an encode during a running request left that request stuck at
            # "reading the prompt" with CPU and GPU busy, for good (reproduced).  So encoding takes its turn in the
            # same FIFO as the requests.
            with self._turn(cancel):
                self._vision_up()
                try:
                    encoded = (self.vision.encode_all(images, cancel) if hasattr(self.vision, "encode_all")
                               else [self.vision.encode(src) for src in images])
                finally:
                    self.last_image_at = time.time()
            # one <|image_pad|> per image -> one per image token.  Only the markers the template writes for an image
            # (right after <|vision_start|>) are images: the same text inside a message (an agent reading these docs,
            # #150) is kept as plain text, or it took an image's place and the counts no longer matched.
            literal = self.tok.encode(_server().IMAGE_PAD, parse_special=False)
            out, k = [], 0
            for j, t in enumerate(ids):
                if t == pad and j > 0 and ids[j - 1] == start:
                    # more pairs than images: text parts that cut both markers apart (the literal marks keep whole ones text)
                    if k == len(encoded):
                        raise ValueError("the prompt and its images do not match")
                    out += [pad] * encoded[k][1]
                    k += 1
                elif t == pad:
                    out += literal
                else:
                    out.append(t)
            if k != len(encoded):
                raise ValueError("the prompt and its images do not match")
            ids = out
        ctx = self.engine.max_context
        if ctx <= 0:
            if getattr(self.engine, "starting", False):   # #344: (re)starting, not a prompt that is too long
                raise EngineStarting("the engine is starting (a minute or two); try again shortly")
            # a failed restart leaves max_context 0: check against the last known context, so the request reaches
            # run() - which starts the engine again - instead of failing with "exceeds the context (0)" forever
            ctx = getattr(self.engine, "known_ctx", 0)
            if ctx <= 0:
                raise EngineStarting("the engine is starting (a minute or two); try again shortly")
        room = ctx - CTX_SLACK - len(ids)
        if max_new is None or max_new <= 0 or (self.fit_max_tokens and room < 1):
            if room < 1:
                # A prompt refused for the context is not kept (#567): the client cannot resend it unchanged.  The
                # other refusals (engine starting, images) keep it: the same prompt comes back and its encode is reused.
                self.forget_prompt(encoded_ids)
                raise ValueError("request exceeds the context window: "
                                 f"prompt ({len(ids)} tokens) leaves no room to answer in the context "
                                 f"({ctx}); requests are never truncated")
            max_new = room
        elif max_new > room:
            if not self.fit_max_tokens:
                self.forget_prompt(encoded_ids)
                raise ValueError("request exceeds the context window: "
                                 f"prompt ({len(ids)} tokens) + max tokens ({max_new}) exceeds the context "
                                 f"({ctx}); requests are never truncated. Send a smaller "
                                 f"max_tokens (at most {max(0, room)} here), or add \"fit_max_tokens\": true to the "
                                 "model's strata-<model>.json to shorten it to the room left (#545)")
            max_new = max(1, room)          # --fit-max-tokens: a shorter completion beats a 400
        if images:
            # The request's images in one file for GENI (~10 MB a picture), written once nothing above refuses the
            # request: one refused after it (the engine starting, no room) left it in the vision directory for good,
            # one more for every retry of a 503.  run() deletes it; drop_embeddings() if run() never starts.
            combined = combined_embeddings_path(self.vision.dir, sum(Path(p).stat().st_size for p, _ in encoded))
            self.embeddings.path = combined             # first, so a half-written one is found as well
            # #2228: each picture's key is its normalized bytes' hash (the encoder's file name), so the engine's
            # conversation cache matches a picture by what it is, not by its embedding floats: a picture encoded again
            # (an encoder restart, the cache's eviction) with other bits still matches its checkpoints
            self.embeddings.keys = [Path(p).stem[:16] for p, _ in encoded]
            write_temporary(combined, [p for p, _ in encoded])
        if req is not None and req.get("strata_prefix") is not None:
            req["strata_prefix"] = self.resolve_prefix(req["strata_prefix"], messages, tools, kwargs, ids, bool(images))
        return ids, kwargs.get("enable_thinking", True) is not False, max_new

    PREFIX_END = "\u0001strata-prefix-end\u0001"          # marks where a message's shared part ends in the rendered prompt

    def resolve_prefix(self, spec, messages, tools, kwargs, ids, has_images=False) -> dict:
        """R1: `"strata_prefix"` marks the start of the prompt as a shared read-only prefix: a long document that many
        short questions follow.  Three ways to say where it ends: `{"messages": K}` (the first K messages), `{"message":
        I, "chars": N}` (the first N characters of message I's text: a document and its question in one message) or
        `{"tokens": N}`.  The engine reads the prompt in two parts there, keeps the checkpoint at the boundary pinned
        (never evicted) and does not park the branch it leaves, so N questions cost one prefix.  Returns
        {"tokens": N} (what the engine's `pin=N` takes: always a prefix of the prompt's ids, the tokenizer's merge across
        the boundary included), or {} when the prefix cannot be marked (said in the log: the request is never refused for
        it).  A malformed field is a 400."""
        keys = ("messages", "message", "chars", "tokens")
        if (not isinstance(spec, dict) or not spec or any(k not in keys for k in spec) or
                set(spec) not in ({"messages"}, {"tokens"}, {"message", "chars"})):
            raise ValueError('strata_prefix: {"messages": K} (the first K messages), {"message": I, "chars": N} (the first '
                             'N characters of message I) or {"tokens": N}')
        for k, v in spec.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < (0 if k == "message" else 1):
                raise ValueError(f"strata_prefix.{k}: a whole number ({'0' if k == 'message' else '1'} or more)")
        if has_images:
            print("[strata] strata_prefix ignored: the request has images", flush=True)
            return {}
        what = ",".join(f"{k}={v}" for k, v in spec.items())

        def lcp(a, b):
            n = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                n += 1
            return n

        def head_ids(msgs):
            """The ids the rendered `msgs` start with (a message's trailing marker cut at PREFIX_END when it is there)."""
            marked, marked_tools, changed = mark_think_literals(msgs, tools, self.literals)
            effort = kwargs.get("reasoning_effort")
            off = kwargs.get("enable_thinking") is False        # render_prompt's rule for #458's effort_end
            kw = ({k: v for k, v in kwargs.items() if k not in ("reasoning_effort", "enable_thinking")}
                  if self.effort_end and (off or effort not in (None, "", "xhigh", "high")) else dict(kwargs))
            kw["add_generation_prompt"] = False
            text = self.template.render(marked, tools=marked_tools, **kw)
            cut = text.find(self.PREFIX_END)
            if cut >= 0:
                text = text[:cut]
            if changed:
                text, plain = unmark_think_literals(text, self.literals)
                return self.tok.encode(text, parse_special=True, plain=plain)
            return self.tok.encode(text, parse_special=True)

        if "tokens" in spec:
            n = spec["tokens"]
        elif "messages" in spec:
            k = spec["messages"]
            if k >= len(messages):
                print(f"[strata] strata_prefix.messages={k} ignored: the request has {len(messages)} message(s) and the "
                      "prefix must leave at least the last one", flush=True)
                return {}
            head = head_ids(messages[:k])
            n = lcp(head, ids)
        else:
            i, chars = spec["message"], spec["chars"]
            text = messages[i].get("content") if 0 <= i < len(messages) else None
            if not isinstance(text, str) or chars > len(text):
                print(f"[strata] strata_prefix ignored: message {i} has no text of {chars} characters", flush=True)
                return {}
            cut = messages[:i] + [{**messages[i], "content": text[:chars] + self.PREFIX_END}]
            head = head_ids(cut)
            n = lcp(head, ids)
        if n < 1 or n >= len(ids) - 1:
            print(f"[strata] strata_prefix {what} ignored: it leaves no usable prefix of the {len(ids)}-token prompt "
                  f"(common start {n})", flush=True)
            return {}
        return {"tokens": n}

    def drop_embeddings(self) -> None:
        """Delete the combined image file prepare() wrote when no run() took it over (a run deletes its own as it
        ends): a request can end before its answer starts - its client gone, anything raised after prepare() - and
        then nothing else would.  The handler calls this when a request is done."""
        path, self.embeddings.path = getattr(self.embeddings, "path", None), None
        if path is not None:
            Path(path).unlink(missing_ok=True)

    def _note(self, n, evs, st=None, rate=None):
        with self.status_lock:
            s = self.status if st is None else st
            s["generated"] = n
            if s.get("first_token") is None:
                s["first_token"] = time.time()
            (self.rate if rate is None else rate).append((time.time(), n))   # the live rate's window (RATE_WINDOW_S)
            for ev in evs:
                if ev.kind == "reasoning":
                    s["phase"] = "thinking"
                elif ev.kind == "content":
                    s["phase"] = "answering"
                elif ev.kind == "tool_start":
                    s["phase"], s["tool"] = f"writing a tool call: {ev.call.name}", ev.call.name
                elif ev.kind == "tool_call":
                    s["phase"] = "tool call complete"
                s["tail"] = ((s.get("tail") or "") + (ev.text or ""))[-600:]

    def _progress(self, last_print, every=1.0, st=None):
        """A progress line in the server window every `every` seconds while a request runs."""
        now = time.time()
        if now - last_print < every:
            return last_print
        with self.status_lock:
            s = dict(self.status if st is None else st)
        el = now - s.get("started", now)
        if s.get("first_token") is None:
            pr = getattr(self.engine, "progress", None)   # (position reached, prompt tokens): a reused prefix counts
            done = f"{pr[0]:,} of {pr[1]:,}" if pr and pr[1] else f"{s.get('prompt_tokens', 0):,}"   # as read (#29)
            print(f"[strata] reading the prompt: {done} tokens, {el:.0f} s so far", flush=True)
        else:
            rate = s["generated"] / max(RATE_MIN_SPAN_S, now - s["first_token"])
            # #984: while a thinking budget applies, the thinking line shows it, not the request's max_tokens
            limit = (f"budget {s['thinking_budget']} (max {s.get('max_tokens')})"
                     if s["phase"] == "thinking" and s.get("thinking_budget") else f"max {s.get('max_tokens')}")
            print(f"[strata] {s['phase']}: {s['generated']} of {limit} tokens, {rate:.1f} tok/s, "
                  f"{el:.0f} s", flush=True)
        return now

    def run(self, ids, thinking, tools, max_new, sampling, cancel, force=None,
            declared_only=False) -> Iterator[tuple[str, object]]:
        """The request's events (see _run); with "prevent_sleep" in the config, the PC stays awake while it runs or waits."""
        ka = self.keep_awake
        if ka is not None:
            ka.acquire()
        try:
            yield from self._run(ids, thinking, tools, max_new, sampling, cancel, force, declared_only)
        finally:
            if ka is not None:
                ka.release()

    def _run(self, ids, thinking, tools, max_new, sampling, cancel, force=None,
             declared_only=False) -> Iterator[tuple[str, object]]:
        """Yields ("event", Event) as text arrives, then ("done", {"finish": .., "completion_tokens": ..}).
        `force` (forced_call): the opening of the call the reply must make - see prepare()."""
        defaults = {**self.sampling_defaults, **self.shared}   # the config's, then the Chat settings shared with apps
        if defaults:                   # the request's own fields win (explicit 0 stays greedy)
            req_values = {k: v for k, v in (sampling or {}).items() if v is not None}
            sampling = {**defaults, **req_values}
        # #123: read after the merge, so a budget shared through POST /settings is seen like the other keys
        budget = self.reasoning_budget(sampling) if thinking else None
        if thinking and not budget and self.answer_room and max_new and max_new >= ANSWER_ROOM_MIN_CAP:
            # 0.1.45: max_tokens counts the thinking too.  A client that caps the reply at 8192 (the desktop agent's
            # harness sends max_completion_tokens: 8192 on every request) and a task the model thinks long about got
            # the cut-off in the middle of the thinking and NO answer.  So thinking is closed early enough to leave
            # the answer its quarter of the cap (the budget's wrap-up: a short closing sentence, </think>, the answer).
            # A request with a budget of its own, or max_tokens below ANSWER_ROOM_MIN_CAP, is left as it was.
            budget = max_new - min(max(ANSWER_RESERVE_MIN, max_new // 4), max_new // 2)
            if max_new <= 32768: print(f"[strata] thinking limited to {budget} of max_tokens {max_new} so the answer has room "
                  "(\"answer_room\": false in the config turns this off)", flush=True)
        if budget and max_new and max_new > 0:
            # #984: a budget at or near max_tokens never fires before the reply is cut off while still thinking, so
            # it has no answer.  Close the thinking early enough to leave room for one.
            reserve = min(max(ANSWER_RESERVE_MIN, max_new // 4), max_new // 2)
            if budget > max_new - reserve:
                print(f"[strata] thinking capped at {max_new - reserve} of max_tokens {max_new} to leave room for "
                      f"the answer (budget {budget})", flush=True)
                budget = max(1, max_new - reserve)
        parser = OutputParser(thinking=thinking, tools=tools, stream_tools=True, recover=self.tool_call_recovery,
                              declared_only=declared_only,
                              deferred=getattr(self, "undeclared_tool_calls", "text") == "call")
        detok, n, finish = Detokenizer(self.tok), 0, "length"
        run_tok, run_len, repeated = None, 0, False     # #606: the current run of one repeated token
        thinking_n = 0                                  # tokens written while thinking (Responses' reasoning_tokens)
        stop_list = stop_strings(sampling)
        stops = StopMatcher(stop_list) if stop_list else None

        def cut(evs):
            """The events with the answer's text cut at a stop string (OpenAI stop, Anthropic stop_sequences)."""
            if stops is None:
                return evs
            out = []
            for ev in evs:
                if stops.hit is not None:
                    break                               # nothing after the stop string is sent
                if ev.kind == "content":
                    text = stops.push(ev.text or "")
                    if text:
                        out.append(Event("content", text))
                    continue
                held = stops.flush()                    # a stop string does not run across a tool call or thinking
                if held:
                    out.append(Event("content", held))
                out.append(ev)
            return out
        opening = []                                    # without thinking the prompt ends with the forced opening:
        if force and not thinking:                      # the parser reads it as if the model had written it
            opening, force = parser.feed(force), None
        tail = ""                                       # the last characters written (the newlines before a call)
        answered, close_retried = False, False          # #1053: content or a call came out; the thinking was closed
        nf_retried = False                              # #879: the request was sent again after non-finite logits
        timings, before = None, None                    # this request's timings; the engine's `last` before it
        recovery_count, reasoning_text, repeat_coverage = 0, "", 0.0
        looped, next_loop_check = False, LOOP_CHECK_EVERY       # #728: reasoning that repeats whole passages
        raw_ids = []                                    # every generated id (STRATA_DEBUG: dump raw model text)
        emb, self.embeddings.path = getattr(self.embeddings, "path", None), None   # this run's to delete now
        img_keys, self.embeddings.keys = getattr(self.embeddings, "keys", None), None
        if emb and img_keys:
            sampling = {**(sampling or {}), "strata_img_keys": img_keys}   # #2228: sent beside the embeddings file
        # Only a DONE line replaces engine.last, so a request that died, errored or was disconnected must not have
        # the PREVIOUS request's decode figures recorded as its own: each pass keeps its own DONE (a segment) if
        # one arrived.  A reasoning-budget continuation is another native generation, not another API request,
        # so the generated reasoning must not become this request's cached input (#615).
        segments = []
        trace = getattr(self.request_trace, "record", None)
        waiting = time.perf_counter()
        # #465: with "parallel" (the engine's batch slots) requests run at once: each keeps its own status and rate
        # window (self.status says busy while any runs); one at a time they are self.status / self.rate, as before
        par = bool(getattr(self.engine, "batch", 0))
        st = {} if par else self.status
        rate = collections.deque(maxlen=32) if par else self.rate
        with self.status_lock:
            self.status["queued"] += 1
        try:
            # --batch: the engine runs several requests at once (StrataEngine.generate_batched orders them)
            turn = contextlib.ExitStack()
            if not getattr(self.engine, "batch", 0):
                # #1619: a request waiting for the single turn sends a keep-alive every QUEUE_BEAT_S, so a client with
                # a stream idle timeout does not abort a healthy queued request (and its retry read the prompt again);
                # a client that left while queued gives its place up instead of taking the turn only to cancel there
                got = False
                try:
                    while not got:
                        got = self.fifo.acquire(timeout=_server().QUEUE_BEAT_S)
                        if got:
                            turn.callback(self.fifo.release)
                        elif cancel.is_set():
                            break
                        else:
                            yield "ping", None
                except BaseException:                    # the consumer closed us at a ping: no longer queued
                    with self.status_lock:
                        self.status["queued"] -= 1
                    raise
                if not got:                              # cancelled while queued
                    with self.status_lock:
                        self.status["queued"] -= 1
                    yield "done", {"finish": "cancel", "completion_tokens": 0, "reused": 0, "timings": None,
                                   "reasoning_tokens": 0, "reasoning_recoveries": 0}
                    return
            with turn:
                try:
                    with self.status_lock:
                        if trace is not None:
                            trace["queue_s"] += round(time.perf_counter() - waiting, 3)
                            trace["state"] = "generating"
                        if not par:
                            self.status["queued"] -= 1
                    # issue #27: it died in an earlier request (or was unloaded) - start it again instead of failing
                    # (parallel requests do not hold the fifo: one of them starts it, the others wait for that).
                    # #1603: a parallel request stays counted as queued until it is registered as running below -
                    # waiting here for the fifo (an image encode, a /v1/vram resize) left it neither - and one on a
                    # loaded engine has nothing to start, so it does not wait for the fifo at all
                    try:
                        if not par:
                            self.ensure_loaded()
                        elif not (self.loaded() and not self._vision_down()):
                            with self.fifo:
                                self.ensure_loaded()
                    except BaseException:
                        if par:
                            with self.status_lock:
                                self.status["queued"] -= 1
                        raise
                    with self.status_lock:
                        if par:
                            self.status["queued"] -= 1
                        st.update(busy=True, phase="reading the prompt", prompt_tokens=len(ids),
                                  generated=0, started=time.time(), first_token=None, tool=None, tail="",
                                  max_tokens=max_new, reasoning_recoveries=0, thinking_budget=budget)
                        if par:
                            self.live_reqs[id(st)] = (st, rate)
                            self.status.update(st)
                        self.last_request_at = time.time()
                        rate.clear()                    # the previous request's samples must not leak into this one
                    before = getattr(self.engine, "last", None)
                    last_print = time.time()
                    prompt, thought = ids, 0            # thought: the reasoning tokens so far (the budget's count)
                    for ev in opening:
                        yield "event", ev
                    while True:
                        segment_before = getattr(self.engine, "last", None)
                        segments_before = len(segments)     # (#879: a pass sent again leaves no segment)
                        gen = self.engine.generate(prompt, max_new - n, sampling, cancel, embeddings=emb) if emb \
                            else self.engine.generate(prompt, max_new - n, sampling, cancel)
                        recover_prompt = None
                        seg, wrap, leaving = [], False, False   # this pass's tokens; the budget is reached; closed
                        nonfinite = False               # #879: the engine ended this pass on non-finite logits
                        opens = False                   # the thinking is over: write the forced call's opening
                        try:
                            # A value the frontend holds back (a tool call's array or object argument is sent
                            # whole, once complete) can keep the stream silent for minutes while tokens are
                            # generated; a client's idle timeout then ends the request.  Send the same keep-alive
                            # the engine's heartbeat sends when nothing has gone out for KEEPALIVE_S.
                            last_out = time.perf_counter()
                            for t in gen:
                                if t is None:               # heartbeat while the engine is quiet
                                    last_print = self._progress(last_print, st=st)
                                    last_out = time.perf_counter()
                                    yield "ping", None
                                    continue
                                n += 1
                                if trace is not None and trace["first_token_s"] is None:
                                    with self.status_lock:
                                        trace["first_token_s"] = round(time.perf_counter() - trace["_clock"], 3)
                                if t in self.stop_ids:
                                    if force and parser.state == "reasoning" and parser.buf == THINK_END:
                                        opens = True    # #537: the held </think> was the end: the call opens there
                                        break
                                    finish = "stop"
                                    raw_ids.append(t)
                                    break
                                raw_ids.append(t)
                                seg.append(t)
                                thinking_n += parser.state in ("reasoning", "rcall")
                                run_len = run_len + 1 if t == run_tok else 1
                                run_tok = t
                                if self.repeat_stop_tokens and run_len >= self.repeat_stop_tokens:
                                    repeated = True     # #606: a degenerate output, not an answer: end it here
                                    break
                                piece = detok.push(t)
                                tail = (tail + piece)[-2:]
                                evs = cut(parser.feed(piece))
                                self._note(n, evs, st, rate)
                                last_print = self._progress(last_print, st=st)
                                for ev in evs:
                                    if self.reasoning_loop_recovery and ev.kind == "reasoning":
                                        reasoning_text += ev.text or ""
                                    if ev.kind in ("content", "tool_start", "tool_call"):
                                        answered = True
                                    yield "event", ev
                                if evs:
                                    last_out = time.perf_counter()
                                elif time.perf_counter() - last_out >= KEEPALIVE_S:
                                    last_out = time.perf_counter()
                                    yield "ping", None
                                if stops is not None and stops.hit is not None:
                                    finish = "stop"         # gen.close() below STOPs the engine, as for a stop token
                                    break
                                if (self.reasoning_loop_recovery and not recovery_count and parser.state == "reasoning"
                                        and n >= next_loop_check and not parser.buf and not parser.pending
                                        and not detok.pending()):
                                    next_loop_check = n + LOOP_CHECK_EVERY
                                    repeat_coverage = reasoning_repeat_coverage(reasoning_text)
                                    if repeat_coverage >= LOOP_COVERAGE:
                                        if self.reasoning_loop_recovery == "stop":
                                            looped = True        # #728: end the reply here, as for a repeated token
                                            break
                                        if not emb:              # "recover": not for a request with pictures
                                            recover_prompt = focused_recovery_prompt(self.tok, ids, raw_ids)
                                            if recover_prompt is not None:
                                                break
                                if budget and parser.state == "reasoning":
                                    thought += 1
                                    # at a clean point: no tag held back, no character split across tokens
                                    if thought >= budget and not parser.buf and not detok.pending():
                                        wrap = True
                                        break
                                if force:
                                    if any(ev.kind in ("tool_start", "tool_call") for ev in evs):
                                        force = None    # the model is writing a call of its own
                                    elif parser.state == "content" and not parser.buf and not detok.pending():
                                        opens = True
                                        break
                        except EngineNonFinite:
                            nonfinite = True
                        except EngineDied as e:
                            finish = "error"
                            self._say_died(e)
                            raise
                        except ValueError as e:             # the engine's ERR line (it may have ended after it)
                            finish = "error"
                            print(f"[strata] the engine reported an error: {e}", flush=True)
                            raise
                        except GeneratorExit:               # the client went away: an engine that never acknowledges
                            leaving = True                  # the STOP below is ended, but no error replaces this
                            raise
                        finally:
                            try:
                                gen.close()             # STOP+drain to THIS request's DONE while still holding the
                                #                         fifo, so a stop-token break can't leave the shared engine
                                #                         queue mid-drain for the next request to read as its own DONE
                            except EngineSilent as e:   # #481: the STOP was never acknowledged: the engine is ended
                                finish = "error"
                                self._say_died(e)
                                if not leaving and not cancel.is_set():
                                    raise
                            segment_done = getattr(self.engine, "last", None)
                            if segment_done is not None and segment_done is not segment_before:
                                segments.append(dict(segment_done))
                        if nonfinite and not cancel.is_set():
                            # #879: the engine emitted none of the poisoned window's tokens and reads its next prompt
                            # from token 0.  Nothing sent yet: the same request once more, unseen by the client
                            if n == 0 and not nf_retried:
                                nf_retried = True
                                # the retry reads from token 0: its DONE, not this one's, says what was reused
                                del segments[segments_before:]
                                print("[strata] the engine's logits became non-finite before the first token (#879); it "
                                      "dropped its cached state: sending the request again once", flush=True)
                                continue
                            if n == 0:
                                finish = "error"
                                print("[strata] the engine's logits became non-finite again on the retry (#879): the "
                                      "request ends with an error", flush=True)
                                raise EngineNonFinite("the model's output became non-finite (NaN) twice in a row "
                                                      "(#879); the engine has dropped its cached state - send the "
                                                      "request again")
                            print(f"[strata] the engine's logits became non-finite after {n} tokens (#879): the reply "
                                  "ends here as \"length\"; the engine dropped its cached state, so the next request "
                                  "reads its prompt from the start", flush=True)
                            finish = "length"
                            break
                        if recover_prompt is not None and not cancel.is_set() and n < max_new:
                            recovery_count += 1
                            # Only the two settings that keep the same words coming are raised (temperature to at
                            # least 1.0, presence penalty to at least 1.5): a client's top_p and top_k are never
                            # touched, and its own request dict is copied, not changed.
                            want = (max(1.0, float((sampling or {}).get("temperature") or 0)),
                                    max(1.5, float((sampling or {}).get("presence_penalty") or 0)))
                            if want != tuple(float((sampling or {}).get(k) or 0)
                                             for k in ("temperature", "presence_penalty")):
                                sampling = {**(sampling or {}), "temperature": want[0], "presence_penalty": want[1]}
                            prompt = recover_prompt
                            with self.status_lock:
                                st["reasoning_recoveries"] = recovery_count
                            if trace is not None:
                                trace["reasoning_recoveries"] = recovery_count
                                trace["reasoning_repeat_coverage"] = round(repeat_coverage, 3)
                            print(f"[strata] repeated reasoning detected at {n} tokens "
                                  f"(coverage={repeat_coverage:.3f}); resuming the same output with the low-effort "
                                  "instruction (reasoning_loop_recovery)", flush=True)
                            continue
                        if (self.reasoning_close_retry and thinking and finish == "stop" and not close_retried
                                and not answered and not wrap and not opens and parser.state == "reasoning"
                                and parser.buf != THINK_END         # #537: not after a held </think>, the end
                                and (stops is None or stops.hit is None) and not cancel.is_set()):
                            # #1053: the model wrote its reasoning and stopped before </think>: the client would get
                            # an empty answer.  Close the thinking once and let it answer.
                            close_retried = True
                            extra = self.tok.encode(REASONING_CLOSE, parse_special=True)
                            if max_new - n - len(extra) >= 1:
                                print("[strata] the reply ended inside its thinking with no answer: closing the "
                                      "thinking once and continuing (reasoning_close_retry)", flush=True)
                                for t in extra:
                                    n += 1
                                    raw_ids.append(t)
                                    thinking_n += parser.state in ("reasoning", "rcall")
                                    evs = cut(parser.feed(detok.push(t)))
                                    self._note(n, evs, st, rate)
                                    for ev in evs:
                                        yield "event", ev
                                prompt = prompt + seg + extra
                                finish = "length"
                                continue
                        if not (wrap or opens) or cancel.is_set():
                            break
                        # #123: the thinking reached reasoning_budget_tokens.  Close it the way the model would (a
                        # short wrap-up and </think>) and let it answer: the next pass's prompt is this one plus what
                        # was generated plus the wrap-up, so the engine continues from the prefix it already holds.
                        # A forced call (tool_choice) is opened the same way: after the wrap-up, or where the
                        # thinking ended, after the blank line the template puts before a call.
                        if wrap:
                            budget = st["thinking_budget"] = None
                            text = REASONING_WRAP_UP + (force or "")
                        else:
                            text = "\n" * (2 - (len(tail) - len(tail.rstrip("\n")))) + force
                        force = None
                        extra = self.tok.encode(text, parse_special=True)
                        if max_new - n - len(extra) < 1:
                            break                       # no room left to answer: "length", as without a budget
                        if wrap:
                            print(f"[strata] thinking budget reached ({thought} tokens): wrapping up the thinking",
                                  flush=True)
                        for t in extra:
                            n += 1
                            raw_ids.append(t)
                            thinking_n += parser.state in ("reasoning", "rcall")
                            evs = cut(parser.feed(detok.push(t)))
                            self._note(n, evs, st, rate)
                            for ev in evs:
                                yield "event", ev
                        if stops is not None and stops.hit is not None:
                            finish = "stop"
                            break
                        prompt = prompt + seg + extra
                    if cancel.is_set():
                        finish = "cancel"
                    elif looped:
                        print(f"[strata] the thinking repeated the same passages (coverage={repeat_coverage:.3f}) at "
                              f"{n} tokens: ended as \"length\" (reasoning_loop_recovery: \"stop\" in "
                              "strata-<model>.json; remove it to turn this off)", flush=True)
                    elif repeated:
                        print(f"[strata] the reply repeated one token ({self.tok.decode([run_tok])!r}) "
                              f"{run_len} times in a row: ended as \"length\" (repeat_stop_tokens in "
                              "strata-<model>.json; 0 turns this off). If a new request with a short prompt does the "
                              "same, restart the server and report it (#606)", flush=True)
                except GeneratorExit:                   # the client disconnected mid-stream
                    finish = "disconnect"
                    raise
                finally:
                    # #266: settle this request's status, history and totals while still holding the fifo: once
                    # it is released the next request sets its own status, which this must not record or clear
                    with self.status_lock:
                        if st.get("busy"):
                            last = request_stats(segments)          # only this request's own DONEs count
                            started = st.get("started", time.time())
                            cvec = (getattr(self.engine, "info", {}) or {}).get("cvec", 0)
                            loaded = str(cvec) not in ("0", "", "None")
                            hit_rate = round(last["hits"] / last["lookups"], 3) if last.get("lookups") else None
                            # #588: the share the GPU read over PCIe (--pcie-frac) or another GPU computed - not in
                            # the hit rate's lookups, which is the VRAM share of the rest (None: an older engine)
                            routed = (last.get("lookups") or 0) + (last.get("offloaded") or 0)
                            pcie_share = round(last["offloaded"] / routed, 3) \
                                if last.get("offloaded") is not None and routed else None
                            seen = prompt_tokens_seen(len(ids), last)   # #471: < len(ids) when cancelled mid-read
                            self.history.append({
                                "projection": (sampling or {}).get("experimental_speed_projection") is not False
                                if loaded else None,
                                "time": started, "duration_s": round(time.time() - started, 1), "finish": finish,
                                "prompt_tokens": seen, "reused": last.get("reused"), "output_tokens": n,
                                # the request's whole prompt, and the tokens read of it (None: an older engine)
                                "prompt_total": len(ids), "prompt_read": last.get("prompt_read"),
                                "reasoning_recoveries": recovery_count,
                                "reasoning_repeat_coverage": round(repeat_coverage, 3),
                                "engine_generated": last.get("generated"),
                                "prompt_ms": last.get("prompt_ms"), "decode_ms": last.get("decode_ms"),
                                "decode_tok_s": round(last["generated"] / (last["decode_ms"] / 1000), 1)
                                if n and (last.get("generated") or 0) >= 2 and last.get("decode_ms") else None,
                                "hit_rate": hit_rate, "pcie_share": pcie_share, "ram_blobs": last.get("ram_blobs"),
                                "file_blobs": last.get("file_blobs"), "file_mb": last.get("file_mb"),
                                # #457: the speculative drafts from the DONE line (None: the engine did not say)
                                "drafts_offered": last.get("drafts_offered"),
                                "drafts_accepted": last.get("drafts_accepted")})
                            t = self.totals
                            t["requests"] += 1
                            t["prompt_tokens"] += seen
                            t["reused"] += last.get("reused") or 0
                            t["output_tokens"] += n
                            t["prompt_ms"] += last.get("prompt_ms") or 0.0
                            t["decode_ms"] += last.get("decode_ms") or 0.0
                            t["drafts_offered"] += last.get("drafts_offered") or 0
                            t["drafts_accepted"] += last.get("drafts_accepted") or 0
                            ft0 = st.get("first_token")             # this request's own (#465: one per request)
                            self.latencies.observe(ft0 - started if ft0 else None, n,
                                                   (last.get("decode_ms") or 0.0) / 1000, time.time() - started)
                            fresh = getattr(self.engine, "last", None)
                            if fresh is not None and fresh is not before:      # the engine's clock for THIS request
                                timings = request_timings(seen, n, last)
                                self.last_timings = dict(timings, at=int(time.time())) if timings else None
                            self.last_request_at = time.time()
                            now = time.time()
                            el = now - st.get("started", now)
                            ft = st.get("first_token")
                            rate = answer_speed(last, n, now - ft if ft else None)
                            hit_msg = f", expert cache {hit_rate*100:.1f}% hit" if hit_rate is not None else ""
                            if hit_msg and pcie_share:
                                hit_msg += f" (+{pcie_share*100:.1f}% of the routed experts over PCIe)"
                            rate_txt = f"{rate:.1f} tok/s" if rate is not None else "no speed"
                            print(f"[strata] done: {n} tokens in {el:.0f} s ({rate_txt}) "
                                  f"({finish}, cancel={cancel.is_set()}){hit_msg}", flush=True)
                            if finish == "length" and parser.state in ("reasoning", "rcall"):   # #530
                                print("[strata] the reply reached max tokens while still thinking, so it has no "
                                      "answer: a thinking budget (reasoning_budget_tokens, in the request or in "
                                      "strata-<model>.json for every request) leaves room to answer", flush=True)
                            if os.environ.get("STRATA_DEBUG") and raw_ids:
                                print(f"[strata] raw: {self.tok.decode(raw_ids)!r}", flush=True)
                        st["busy"] = False
                        st.pop("tail", None)                     # #212: the answer's end is not kept once it is done
                        st.pop("tool", None)
                        if par:
                            self.live_reqs.pop(id(st), None)
                            if self.live_reqs:              # the newest request still running
                                self.status.update(list(self.live_reqs.values())[-1][0])
                            else:
                                self.status.update(busy=False)
                                self.status.pop("tail", None)
                                self.status.pop("tool", None)
        finally:
            if emb:
                Path(emb).unlink(missing_ok=True)
        for ev in cut(parser.finish(finish)):
            yield "event", ev
        if parser.rescued or parser.refused:
            self.totals["tool_calls_from_reasoning"] = self.totals.get("tool_calls_from_reasoning", 0) + parser.rescued
            print(f"[strata] tool calls inside the thinking: {parser.rescued} read as calls, {parser.refused} kept as "
                  f"reasoning (quoted, or the turn did not end on a stop)", flush=True)
        if getattr(parser, "stray_think", 0):
            # #4077: the model wrote a closing think tag while thinking; the reasoning after it was sent as the answer
            self.totals["stray_think_closers"] = self.totals.get("stray_think_closers", 0) + parser.stray_think
            print(f"[strata] {parser.stray_think} extra closing think tag(s) in the answer were dropped (the model wrote one "
                  "while thinking, so the rest of its reasoning went out as the answer; a call after it still counts)", flush=True)
        if getattr(parser, "notes", None):
            self.totals["tool_args_repaired"] = self.totals.get("tool_args_repaired", 0) + len(parser.notes)
            print(f"[strata] {len(parser.notes)} tool call argument(s) repaired: {'; '.join(sorted(set(parser.notes)))}", flush=True)
        rejected = []
        if parser.unread:
            named = getattr(parser, "unread_names", None)
            print(f"[strata] {parser.unread} <tool_call> block(s) in the answer did not read as a call of a declared "
                  "tool and went back as text (a name the request did not declare, or a form the template does "
                  "not use)" + (f"; the names the model wrote: {', '.join(named)}" if named else "")
                  + "; the response carries them as strata_rejected_tool_calls, /metrics counts them", flush=True)
            with self.status_lock:
                self.totals["tool_calls_unread"] = self.totals.get("tool_calls_unread", 0) + parser.unread
            # #3796: the same names for the client (a machine-readable marker next to the text, which stays as the model wrote it)
            rejected = [{"name": nm, "reason": "undeclared"} for nm in named or []]
        if stops is not None and stops.hit is None and stops.held:
            yield "event", Event("content", stops.flush())     # the held tail was not a stop string after all
        done = {"finish": finish, "completion_tokens": n, "reused": (timings or {}).get("cache_n", 0),
                "timings": timings, "reasoning_tokens": thinking_n,
                "reasoning_recoveries": recovery_count}
        if stops is not None and stops.hit is not None:
            done["stop_sequence"] = stops.hit
        if rejected:
            done["rejected_tool_calls"] = rejected
        yield "done", done


def _dump_claude_prompt(req: dict):
    """Save full system prompt and tool definitions per model into dumps/claude_models/."""
    try:
        model = str(req.get("model") or "unknown").replace("/", "_")
        dump_dir = Path(__file__).resolve().parent.parent / "dumps" / "claude_models"
        dump_dir.mkdir(parents=True, exist_ok=True)
        sys_val = req.get("system")
        sys_text = ""
        if isinstance(sys_val, str):
            sys_text = sys_val
        elif isinstance(sys_val, list):
            sys_text = "\n\n".join(b.get("text", "") for b in sys_val if isinstance(b, dict))
        if sys_text:
            (dump_dir / f"{model}_system.md").write_text(sys_text, encoding="utf-8")
        if req.get("tools"):
            (dump_dir / f"{model}_tools.json").write_text(json.dumps(req["tools"], indent=2, ensure_ascii=False), encoding="utf-8")
        (dump_dir / f"{model}_summary.json").write_text(json.dumps({
            "model": model,
            "system_chars": len(sys_text),
            "tools_count": len(req.get("tools") or []),
            "tools": [t.get("name") for t in (req.get("tools") or [])]
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


def _debug_req(api, req, messages, tools, max_new, thinking, prompt_tokens):
    """One compact line per request while diagnosing blank/empty turns. Set STRATA_DEBUG=1 to enable."""
    if not os.environ.get("STRATA_DEBUG"):
        return
    last = messages[-1] if messages else {}
    body = last.get("content")
    if isinstance(body, list):
        body = " ".join(p.get("text", "") for p in body if isinstance(p, dict))
    preview = (str(body or "")[:80]).replace("\n", " ")
    print(f"[strata] req {api}: msgs={len(messages)} tools={len(tools or [])} "
          f"max_tokens_raw={req.get('max_tokens')!r}/{req.get('max_completion_tokens')!r} "
          f"max_new={max_new} thinking={thinking} stream={bool(req.get('stream'))} "
          f"prompt_tokens={prompt_tokens} last={last.get('role')!r}:{preview!r}", flush=True)


# ------------------------------------------------------------------------------------------------ MCP tool loop
def run_with_mcp(svc: Service, hub, messages, tools, kw, ids, thinking, max_new, max_req, sampling, cancel,
                 mcp_names):
    """Service.run with the MCP tools executed here: the model writes a call to an MCP tool, the server runs it, adds
    the call and its result to the conversation and lets the model continue - up to `max_rounds` times.  Yields what
    Service.run yields (text, thinking, the request's own tool calls) plus ("mcp", {...}) for the tool activity, and
    one ("done", ...) at the very end with the output tokens of every round.

    `mcp_names`: the MCP tools this request offered; any other call is one of the request's own tools and ends the
    turn as always (the client answers it).  MCP calls written in the same answer are then not run (their results
    could not reach the model before the client's)."""
    max_rounds = int(hub.settings["max_rounds"])
    total, rounds, done = 0, 0, None
    messages = list(messages)
    while True:
        text, reasoning, calls, own_calls = [], [], [], 0
        for kind, x in svc.run(ids, thinking, tools, max_new, sampling, cancel, declared_only=True):
            if kind == "done":
                done = x
                continue
            if kind == "event":
                ev: Event = x
                if ev.call is not None and ev.call.name in mcp_names:
                    if ev.kind == "tool_start":          # the model has started writing a call: say so at once
                        yield "mcp", {"event": "start", "id": ev.call.id, "name": ev.call.name}
                    elif ev.kind == "tool_call":
                        calls.append(ev.call)
                    continue                             # its argument pieces are not streamed to the client
                if ev.kind == "tool_call":
                    own_calls += 1
                elif ev.kind == "content":
                    text.append(ev.text)
                elif ev.kind == "reasoning":
                    reasoning.append(ev.text)
            yield kind, x
        total += done["completion_tokens"]
        run_them = calls and not own_calls and done["finish"] == "stop" and not cancel.is_set()
        if run_them and rounds >= max_rounds:
            yield "mcp", {"event": "limit", "max_rounds": max_rounds}
            run_them = False
        if not run_them:
            for c in calls:                              # announced, never run: close them in the client's view
                yield "mcp", {"event": "result", "id": c.id, "ok": False, "skipped": True, "text": "not run",
                              "chars": 0, "truncated": False, "ms": 0}
            break
        rounds += 1
        results = []
        for c in calls:
            s, tool = hub.routes().get(c.name, (None, c.name))
            yield "mcp", {"event": "call", "id": c.id, "name": c.name, "server": s.name if s else None,
                          "tool": tool, "arguments": c.arguments, "round": rounds}
            # The call runs on a thread while this generator keeps yielding heartbeats: they reach the client as
            # keep-alives, which is how a client that went away (the web app's Stop) is noticed during a slow tool.
            box = {}

            def work(c=c, box=box):
                try:
                    box["r"] = hub.call(c.name, c.arguments, cancel)
                except McpCancelled:
                    box["cancelled"] = True
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            try:
                while worker.is_alive():
                    worker.join(1.0)
                    if worker.is_alive():
                        yield "ping", None
            except GeneratorExit:
                cancel.set()                             # the client is gone: stop the tool too
                raise
            if "r" not in box:
                break
            r = box["r"]
            print(f"[strata] tool {c.name}: {'ok' if r['ok'] else 'error'}, {r['chars']:,} characters in "
                  f"{r['ms'] / 1000:.1f} s{' (truncated for the model)' if r['truncated'] else ''}", flush=True)
            results.append(r["text"])
            yield "mcp", {"event": "result", "id": c.id, **{k: r[k] for k in ("ok", "text", "chars", "truncated", "ms")}}
        if cancel.is_set() or len(results) < len(calls):
            done = {**done, "finish": "cancel"}
            break
        messages.append({"role": "assistant", "content": "".join(text).strip(),
                         **({"reasoning_content": "".join(reasoning).strip()} if reasoning else {}),
                         "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls]})
        messages += [{"role": "tool", "content": r} for r in results]
        try:
            ids, thinking, max_new = svc.prepare(messages, tools, kw, max_req, cancel=cancel)
        except ClientGone:                                      # #1999: the client left while a picture was prepared
            done = {**done, "finish": "cancel"}
            break
    yield "done", {**done, "completion_tokens": total, "prompt_tokens": len(ids)}
