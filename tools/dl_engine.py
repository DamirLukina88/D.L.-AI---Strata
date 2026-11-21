"""One streamed chat turn against the engine: stream reading, loop detection, progress.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.request
try:
    from .dl_common import (
    C_ACCENT,
    C_MUTED,
    C_RESET,
    _switch,
    cli as _cli,
    dl_profile,
)
except ImportError:
    from dl_common import (
    C_ACCENT,
    C_MUTED,
    C_RESET,
    _switch,
    cli as _cli,
    dl_profile,
)
try:
    from .dl_tools_schema import DL_TOOLS
except ImportError:
    from dl_tools_schema import DL_TOOLS


# (window of the latest thinking in chars, shortest sentence that counts, repeats that make a loop).  A short cycle:
# the IQ1_M model repeated three sentences ~530 times in one 180,333-char block (17 min, tetris after-memory,
# 2026-10-20).  A long cycle: ~21 lines repeated 18 times in a 79,173-char block (crc32c, same run).  Checked on the
# 189 thinking blocks over 3,000 chars saved on 2026-10-20: these rules flag 4, and all 4 go round in circles.
LOOP_RULES = ((8000, 30, 8), (24000, 60, 4))


LOOP_CHECK_EVERY = 3000         # chars of new thinking between two checks


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def thinking_loops(text: str) -> str | None:
    """The sentence the thinking keeps repeating, or None."""
    for window, shortest, repeats in LOOP_RULES:
        counts: dict[str, int] = {}
        for sent in _SENTENCE.split(text[-window:]):
            sent = sent.strip()
            if len(sent) < shortest:
                continue
            counts[sent] = counts.get(sent, 0) + 1
            if counts[sent] >= repeats:
                return sent
    return None


READING_SHOW_S = float(os.environ.get("DL_READING_SHOW_S") or 20.0)   # a prompt read this long shows "Reading the prompt… N s"


READING_SLOW_S = float(os.environ.get("DL_READING_SLOW_S") or 120.0)  # ... and this long adds "unusually slow" (once)


def stream_chat_turn(messages: list[dict], url: str, api_key: str, tools: list[dict] | None = None,
                     emit=None, cancel=None, effort: str | None = None, budget: int = 0):
    """One streamed model reply.  `emit(event)` replaces terminal printing (the session daemon); `cancel` is a
    threading.Event that stops the stream early.  No sampling fields are sent: the server fills in the web app's
    Chat settings (reasoning effort, temperature, top_p, top_k, seed, max tokens, speed projection), so the CLI
    follows them."""
    endpoint = f"{url.rstrip('/')}/v1/chat/completions"
    active_tools = DL_TOOLS if tools is None else tools
    payload = {
        "model": "strata",
        # dl_turn / dl_*: the session daemon's marks (/rewind, handoff boundary); not the model's
        "messages": [{k: v for k, v in m.items() if not k.startswith("dl_")}
                     if any(k.startswith("dl_") for k in m) else m for m in messages],
        "tools": active_tools,
        "stream": True,
        "return_progress": True,   # prompt_progress chunks while the engine reads the prompt (llama.cpp's flag)
    }
    if effort:                     # a session's own thinking level (/effort); the server's Chat settings otherwise
        payload["reasoning_effort"] = effort
    if budget and budget > 0:
        payload["reasoning_budget_tokens"] = budget
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    t0 = time.time()
    reasoning_started = False
    reasoning_closed = False
    full_reasoning = []
    full_content = []
    tool_calls_dict = {}
    tok_count = 0
    finish_reason = None
    usage = {}
    loop_guard = _switch("DL_LOOP_GUARD")
    reasoning_len, next_loop_check, loop_sentence = 0, LOOP_CHECK_EVERY, None

    # "Reading the prompt… N s" (audit 2026-11-15: an image prompt read for 339 s with nothing on screen).  The server
    # sends a keep-alive comment every 10 s and, with return_progress, a prompt_progress chunk per chunk it reads.
    first_out = False
    reading = {"last": 0.0, "last_pp": 0.0, "sent": False, "slow": False}

    def note_reading(pp: dict | None = None) -> None:
        if emit is None or first_out:
            return
        now = time.time()
        elapsed = now - t0
        if elapsed < dl_profile.tuned("DL_READING_SHOW_S", _cli().READING_SHOW_S, float):
            return
        # a progress chunk at most every 2 s; a bare keep-alive (no progress to tell) only after 10 s of nothing
        turns_slow = elapsed >= dl_profile.tuned("DL_READING_SLOW_S", _cli().READING_SLOW_S, float) and not reading["slow"]          # always told, once
        if not turns_slow and ((now - reading["last_pp"] < 2.0) if pp else
                               (now - reading["last"] < 10.0 and reading["sent"])):
            return
        reading["last"], reading["sent"] = now, True
        if pp:
            reading["last_pp"] = now
        ev = {"type": "progress", "phase": "reading", "elapsed_s": int(elapsed)}
        if pp and int(pp.get("total") or 0) > 0:
            cache = int(pp.get("cache") or 0)
            ev.update(read=int(pp.get("processed") or 0) - cache, total=int(pp["total"]) - cache)
        if turns_slow:
            reading["slow"] = ev["slow"] = True
            emit({"type": "notice", "level": "warn",
                  "text": f"The engine has been reading the prompt for {int(elapsed)} s, which is unusually slow. "
                          "The Monitor tab's Restart reloads the model."})
        emit(ev)

    def output_started() -> None:
        nonlocal first_out
        if not first_out:
            first_out = True
            if emit is not None and reading["sent"]:
                emit({"type": "progress", "phase": "done", "elapsed_s": int(time.time() - t0)})

    socks: list = []
    done = threading.Event()
    reading_lock = threading.Lock()

    def tick() -> None:
        # the server sends nothing while it loads the model or encodes a picture (live, 2026-11-15: the first line
        # came after 63 s): the time still shows, from here
        while not done.wait(5.0):
            if first_out:
                return
            with reading_lock:
                note_reading()
    if emit is not None:
        threading.Thread(target=tick, daemon=True).start()
    open_url = urllib.request.urlopen                # no Stop to wait for (the terminal REPL): as before
    if cancel is not None:
        open_url = urllib.request.build_opener(_ConnHTTPHandler(socks), _ConnHTTPSHandler(socks)).open
        threading.Thread(target=_cut_on_cancel, args=(socks, cancel, done), daemon=True).start()
    try:
        with open_url(req, timeout=600) as resp:
            for raw_line in resp:
                if cancel is not None and cancel.is_set():
                    finish_reason = "cancelled"
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    if line:
                        with reading_lock:
                            note_reading()
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("error"):
                        err = chunk["error"]
                        msg = err.get("message") if isinstance(err, dict) else str(err)
                        raise RuntimeError(f"Strata stream error: {msg}")

                    if isinstance(chunk.get("prompt_progress"), dict):
                        with reading_lock:
                            note_reading(chunk["prompt_progress"])
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content") or delta.get("content") or delta.get("tool_calls"):
                        output_started()
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                    # 1. Reasoning chunk
                    reasoning_chunk = delta.get("reasoning_content")
                    if reasoning_chunk and loop_guard:
                        reasoning_len += len(reasoning_chunk)
                        if reasoning_len >= next_loop_check:
                            next_loop_check = reasoning_len + LOOP_CHECK_EVERY
                            loop_sentence = thinking_loops("".join(full_reasoning) + reasoning_chunk)
                            if loop_sentence:
                                finish_reason = "loop"      # closing the stream stops the generation
                                break
                    if reasoning_chunk and emit:
                        tok_count += 1
                        reasoning_started = True
                        emit({"type": "thinking", "text": reasoning_chunk})
                        full_reasoning.append(reasoning_chunk)
                    elif reasoning_chunk:
                        tok_count += 1
                        if not reasoning_started:
                            sys.stdout.write(f"\n{C_ACCENT}🧠{C_RESET} {C_MUTED}Thinking:{C_RESET} {C_MUTED}")
                            reasoning_started = True
                        sys.stdout.write(reasoning_chunk)
                        sys.stdout.flush()
                        full_reasoning.append(reasoning_chunk)

                    # 2. Main content chunk
                    content_chunk = delta.get("content")
                    if content_chunk and emit:
                        tok_count += 1
                        emit({"type": "text", "text": content_chunk})
                        full_content.append(content_chunk)
                    elif content_chunk:
                        tok_count += 1
                        if reasoning_started and not reasoning_closed:
                            sys.stdout.write(f"{C_RESET}\n\n")
                            reasoning_closed = True
                        sys.stdout.write(content_chunk)
                        sys.stdout.flush()
                        full_content.append(content_chunk)

                    # 3. Tool call chunks
                    tc_deltas = delta.get("tool_calls")
                    if tc_deltas:
                        if reasoning_started and not reasoning_closed and not emit:
                            sys.stdout.write(f"{C_RESET}\n")
                            reasoning_closed = True
                        for tc_item in tc_deltas:
                            idx = tc_item.get("index", 0)
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc_item.get("id") or f"call_{idx}",
                                    "type": "function",
                                    "function": {
                                        "name": tc_item.get("function", {}).get("name", ""),
                                        "arguments": ""
                                    }
                                }
                            if tc_item.get("function", {}).get("name"):
                                tool_calls_dict[idx]["function"]["name"] = tc_item["function"]["name"]
                            if tc_item.get("function", {}).get("arguments"):
                                tool_calls_dict[idx]["function"]["arguments"] += tc_item["function"]["arguments"]

            if not emit:
                if reasoning_started and not reasoning_closed:
                    sys.stdout.write(f"{C_RESET}\n")
                if full_content:
                    sys.stdout.write("\n")
                sys.stdout.flush()

    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Strata API HTTP {e.code}: {err}")
    except RuntimeError:
        raise
    except Exception as e:
        if cancel is None or not cancel.is_set():
            raise RuntimeError(f"Connection failed to Strata at {endpoint}: {e}")
        finish_reason = "cancelled"                 # Stop cut the connection (_cut_on_cancel)
    finally:
        done.set()
    if finish_reason is None and cancel is not None and cancel.is_set():
        finish_reason = "cancelled"                 # the cut connection ended the stream before a finish reason

    dt = time.time() - t0
    rate = tok_count / dt if dt > 0 else 0
    parsed_tool_calls = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())]

    return {
        "reasoning": "".join(full_reasoning),
        "content": "".join(full_content) if full_content else None,
        "tool_calls": parsed_tool_calls,
        "finish_reason": finish_reason or ("tool_calls" if parsed_tool_calls else "stop"),
        "tokens": tok_count,
        "wall_time": dt,
        "rate": rate,
        "prompt_tokens": usage.get("prompt_tokens"),     # Strata reports the exact prompt size at the end
        "loop_sentence": loop_sentence,
    }


def _keep_socket(conn, socks: list):
    """Record the connection's socket once it connects: http.client lets go of it when the response starts."""
    connect = conn.connect

    def keep():
        connect()
        socks.append(conn.sock)
    conn.connect = keep
    return conn


class _ConnHTTPHandler(urllib.request.HTTPHandler):
    """urlopen's HTTP handler that keeps the socket it opens, so a Stop can cut it (see _cut_on_cancel)."""
    def __init__(self, socks: list):
        super().__init__()
        self.socks = socks

    def http_open(self, req):
        return self.do_open(lambda host, **kw: _keep_socket(http.client.HTTPConnection(host, **kw), self.socks), req)


class _ConnHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, socks: list):
        super().__init__()
        self.socks = socks

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _keep_socket(http.client.HTTPSConnection(host, **kw), self.socks),
                            req, context=self._context)


def _cut_on_cancel(socks: list, cancel, done: threading.Event) -> None:
    """Stop pressed: shut the model request's socket at once.  The stream loop only sees `cancel` when a line
    arrives, and while the server reads a long prompt or waits for another request a line comes every 10 s; the
    server notices the closed connection at its next heartbeat and stops the engine."""
    while not done.wait(0.2):
        if cancel.is_set():
            for sock in socks:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            return


def format_args_preview(args: dict) -> str:
    parts = []
    for k, v in args.items():
        val_str = str(v)
        if len(val_str) > 40:
            val_str = val_str[:37] + "..."
        parts.append(f"{k}={repr(val_str)}")
    return ", ".join(parts)
