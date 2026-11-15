"""Timeouts, limits, effort text and loop-detection helpers of the server.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import collections
import os
import re
from serve.late import server as _server
from serve.errors import EngineDied


# #458: the trailing effort turn ("effort_position": "end"); low is the template's own sentence, medium (which the
# template says nothing for: no xhigh sentence is medium there) says it, since the xhigh one stays at the top
EFFORT_TURN = "<|im_start|>system\n{}<|im_end|>\n"


EFFORT_TEXT = {"low": "Reasoning effort is set to low. Keep your thinking brief and focused, moving directly to the "
                      "conclusion without unnecessary elaboration.",
               "medium": "Reasoning effort is set to medium. Think as much as the task needs, without unnecessary "
                         "elaboration.",
               # the template's own xhigh sentence (chat_template.jinja), which #728's recovery swaps for the low one
               "xhigh": "Reasoning effort is set to xhigh. Please think carefully through the task, validate key "
                        "assumptions, consider plausible alternatives, and prioritize correctness, consistency, and "
                        "clarity in the final answer."}


VISION_START = "<|vision_start|>"


# #606: a reply that repeats one token this many times in a row is ended there ("length"): a model in a loop, or a
# broken state that answers one token forever (an issue saw 36,689 tokens of "!"). The config's "repeat_stop_tokens"
# sets it; 0 turns it off.
REPEAT_STOP_TOKENS = 256


ANSWER_ROOM_MIN_CAP = 1024    # 0.1.45: from this max_tokens on, thinking without a budget is closed early enough to leave room to answer


ANSWER_RESERVE_MIN = 512      # #984: the tokens kept for the answer when a thinking budget is cut down to fit max_tokens


# #123: what closes the thinking when it reaches reasoning_budget_tokens (the model's own end-of-thinking tag after it)
# #1053 (opt-in "reasoning_close_retry": true): a reply that ends on its stop token still inside <think>, with no answer
# and no call, is continued once with the thinking closed (the same way the budget's wrap-up closes it)
REASONING_CLOSE = "\n</think>\n\n"


REASONING_WRAP_UP = "\n\nI have thought about this long enough; time to give my answer.\n</think>\n\n"


# #728: opt-in handling of reasoning that repeats whole passages (which the single-token guard above cannot see).
# "reasoning_loop_recovery": "stop" ends the reply there; "recover" (or true) goes on from the same output with the
# low-effort instruction in place of the xhigh one.  Both off by default.
HIGH_EFFORT = EFFORT_TEXT["xhigh"]


LOW_EFFORT = EFFORT_TEXT["low"]


LOOP_CHECK_EVERY = 512           # output tokens between two looks at the reasoning (at a clean parser boundary)


LOOP_COVERAGE = 0.25             # the share of the last 2,000 words inside 12-word passages seen three times


LOOP_HISTORY_WORDS = 30000       # how far back the passages are counted (bounds the cost of a look)


LOOP_TAIL_CHARS = 2048           # chars at the end of the reasoning also checked for a short period (#1753)


LOOP_TAIL_PERIOD = 64            # a period at most this long in that tail reads as a fully repeated window


def reasoning_repeat_coverage(text):
    """Coverage of recent words by 12-word passages seen at least three times.

    Only reasoning is supplied. The history (the last LOOP_HISTORY_WORDS words) detects repeated verification passes
    separated by long code drafts; the recent window excludes old repetitions.  #1753: a loop can also be one long
    word (a 24k-digit string cycling an 11-digit pattern): the word split makes it a single word and no word count
    grows, and #606's token run never grows either (the tokenizer has no multi-digit tokens), so before the word
    count the last LOOP_TAIL_CHARS chars are checked for a period of at most LOOP_TAIL_PERIOD, and a periodic tail
    reads as full coverage: it is all of the recent output, repeated.
    """
    tail = text[-LOOP_TAIL_CHARS:].lower()
    if len(tail) == LOOP_TAIL_CHARS and any(tail[p:] == tail[:-p] for p in range(1, LOOP_TAIL_PERIOD + 1)):
        return 1.0
    words = re.findall(r"\w+|[^\w\s]", text.lower())[-LOOP_HISTORY_WORDS:]
    width, window = 12, 2000
    if len(words) < window:
        return 0.0
    grams = [tuple(words[i:i + width]) for i in range(len(words) - width + 1)]
    counts = collections.Counter(grams)
    start = max(0, len(words) - window)
    covered = set()
    for i in range(start, len(grams)):
        if counts[grams[i]] >= 3:
            covered.update(range(i, i + width))
    return len(covered) / (len(words) - start)


def focused_recovery_prompt(tok, ids, generated):
    """The prompt's ids with the xhigh effort sentence of the first system message replaced by the low one, then
    every token generated so far.  A splice of token ids: the prompt is never decoded and encoded again, so a literal
    `</think>` or vision marker in it (#537, #554) stays what it was.  None when the sentence is not there as whole
    tokens in the first system message (a user's text never counts).  No answer or end-of-thinking is inserted."""
    end = tok.encode(_server().IM_END, parse_special=True)
    if len(end) != 1 or end[0] not in ids:
        return None
    head = ids[:ids.index(end[0])]
    if not tok.decode(head).startswith("<|im_start|>system\n"):
        return None
    old, new = tok.encode(HIGH_EFFORT, parse_special=False), tok.encode(LOW_EFFORT, parse_special=False)
    for i in range(len(head) - len(old) + 1):
        if head[i:i + len(old)] == old:
            return ids[:i] + new + ids[i + len(old):] + list(generated)
    return None


LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")


QUEUE_BEAT_S = 10.0         # a request waiting for the single turn sends a keep-alive this often (#1619)


KEEPALIVE_S = 10.0          # a held-back tool argument leaves the stream quiet: ping at least this often


CTX_SLACK = 8               # `strata --serve` rejects prompt + max_new + 8 > context: keep the same margin here


# The live tok/s is a rate over a window, not a mean since the first token: a mean reads ~1/elapsed at the first
# token (the Monitor showed five-digit numbers) and then undershoots for the first second of every answer.
RATE_WINDOW_S = 2.0


RATE_MIN_SPAN_S = 0.25      # younger than this there is no rate yet: the mean so far, with the span floored here


# #481: a running request whose engine prints nothing (no T, PP or any other line) for this long has lost step with the
# server (the engine's main thread waits, untimed, for its next command): the engine is ended and the request fails;
# the next request starts it again.  The config's "engine_silence_s" sets it (0: wait forever, as before).
ENGINE_SILENCE_S = 300.0


# #4271: a streaming client that stops reading (a hung process, a network that dropped) leaves the thread that writes to
# it blocked once the socket buffers are full - and that thread holds the engine's turn.  A write that makes no progress
# for this long ends the request as a disconnect (the engine is stopped, the turn given back).  0: no limit, as before.
STREAM_WRITE_TIMEOUT_S = float(os.environ.get("STRATA_STREAM_WRITE_TIMEOUT_S", "60") or 0)


# Disk sessions: the longest allowance an engine may announce (`SWAIT <phase> <s>`) for one step that blocks in a
# single call (a file flush, the host->device transfer); the engine's own bound is the same (session_phase_limit_s).
SESSION_WAIT_MAX_S = 3600


# ... except while a prompt is read: a PP line comes once per chunk (up to 32768 tokens with --prefill auto, issue
# #282), and the slowest PCs read ~100 tok/s, so a first chunk can take minutes before the first line.  Until the first
# PP the wait adds the chunk's tokens at PP_FLOOR_TOK_S; after one, a chunk may take PP_SLACK x the last one's time.
PP_CHUNK_MAX = 32768


PP_FLOOR_TOK_S = 50.0


PP_SLACK = 3.0


# Reads that had no timeout (#1317).  A blocking read of the image encoder's pipe or of the engine's READY line that
# never returned held the request turn for good: the engine then sat idle in its command loop, so no watchdog could
# fire and every later request queued behind it (the "lost step" class of #481).  Generous on purpose: a cold model
# load, a slow disk or a slow CPU encode is not a hang.  Only a process that says nothing at all for this long is
# ended; the next request starts it again.
# STRATA_ENGINE_READY_S / STRATA_VISION_READY_S / STRATA_VISION_ENCODE_S override them (0 = wait for ever, as before).


def _timeout_env(name: str, default: float) -> float | None:
    try:
        v = float(os.environ.get(name, default))
    except ValueError:
        v = default
    return None if v <= 0 else v


# #1317 part 2: the quick watchdog for a FROZEN engine.  engine_silence_s (above) is generous on purpose: a slow PC reads a
# prompt chunk for minutes without a line.  But an engine that prints nothing for ENGINE_STALL_S and also uses no CPU time and
# moves no bytes of I/O in that time is not slow, it is idle or frozen (a deadlock in a CUDA call, a driver stall, a lost
# step), and waiting longer cannot help: it is ended, and the next request starts it again.  An engine that is silent but
# still working is never ended by this, only reported once (the recommendation: engine_silence_s, or this variable).
# STRATA_ENGINE_STALL_S overrides it (0 = off).  Needs psutil (setup installs it); without it nothing is ended.
ENGINE_STALL_S = _timeout_env("STRATA_ENGINE_STALL_S", 90.0)


# 2026-11-15: a request stopped mid-prompt (the user pressed Stop, rewound, or the client left) on an engine reading
# its prompt from disk did not end for minutes, and the prompt sent again waited behind it.  After a STOP the engine
# gets this long to end the request; then it is ended and the next request starts it again (about a minute).
# STRATA_ENGINE_CANCEL_S overrides it (0 = wait as before).
ENGINE_CANCEL_S = _timeout_env("STRATA_ENGINE_CANCEL_S", 15.0)


STALL_CPU_EPS_S = 0.5       # CPU seconds the engine may use in the whole stall window and still count as frozen


STALL_IO_EPS_B = 1 << 20    # bytes read or written in that window


def engine_frozen(base: tuple[float, int], now: tuple[float, int]) -> bool:
    """#1317: True when two (cpu seconds, io bytes) samples of the engine show no work between them."""
    return (now[0] - base[0]) <= STALL_CPU_EPS_S and (now[1] - base[1]) <= STALL_IO_EPS_B


VISION_READY_S = _timeout_env("STRATA_VISION_READY_S", 300.0)


VISION_ENCODE_S = _timeout_env("STRATA_VISION_ENCODE_S", 300.0)


MAX_START_WAIT = 1800.0     # seconds a start may wait for the model (#3949 #3459)


ENGINE_READY_S = _timeout_env("STRATA_ENGINE_READY_S", 900.0)


def calculate_start_wait(cfg: dict | None = None, model_path: str | None = None) -> float:
    """How long the start waits for the model to be ready (#3949 #3459): 10 minutes baseline,
    more for a big model (about 8 more seconds per GB above 40 GB, at most 30 minutes / 1800s).
    A config's engine_ready_s or STRATA_ENGINE_READY_S environment variable overrides it."""
    if cfg and cfg.get("engine_ready_s"):
        try:
            return min(MAX_START_WAIT, max(300.0, float(cfg["engine_ready_s"])))
        except (ValueError, TypeError):
            pass
    env_s = _timeout_env("STRATA_ENGINE_READY_S", 0.0)
    if env_s and env_s > 0:
        return env_s
    # Calculate disk size of model if possible
    model_gb = 0.0
    if model_path:
        try:
            p = Path(model_path)
            if p.is_file():
                model_gb = p.stat().st_size / 1e9
            elif p.is_dir():
                model_gb = sum(f.stat().st_size for f in p.glob("*") if f.is_file()) / 1e9
        except (OSError, ValueError):
            model_gb = 0.0
    if model_gb > 40.0:
        return min(MAX_START_WAIT, 600.0 + (model_gb - 40.0) * 8.0)
    return float(_server().ENGINE_READY_S or 900.0)


def batch_slots_on(engine) -> bool:
    """Does this engine run requests in batch slots ("parallel", whose `BT` lines carry no LP lines)?"""
    return any(int(getattr(e, "batch", 0) or 0) for e in (getattr(engine, "engines", None) or [engine]))


def died_note(e: EngineDied) -> str:
    return f"{e}; the next request restarts it" if getattr(e, "restarts", True) else str(e)
