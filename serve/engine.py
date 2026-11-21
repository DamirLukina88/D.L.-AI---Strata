"""The engine: the Engine protocol, MockEngine, StrataEngine (the resident `strata --serve` process) and its start/stall helpers.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
from serve import logit_bias as bias_api
from typing import Iterator
from typing import Protocol
import json
import math
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from serve.late import server as _server
from serve.errors import (
    EngineDied,
    EngineNonFinite,
    EngineSilent,
    EngineStuck,
    GpuBusy,
    SessionRefused,
)
from serve.request_stats import add_carry, carry_leg, prefill_leg_stats
from serve.tunables import (
    ENGINE_SILENCE_S,
    PP_CHUNK_MAX,
    PP_FLOOR_TOK_S,
    PP_SLACK,
    SESSION_WAIT_MAX_S,
    calculate_start_wait,
    engine_frozen,
)


# ------------------------------------------------------------------------------------------------ engines
class Engine(Protocol):
    max_context: int
    def generate(self, ids: list[int], max_new: int, sampling: dict, cancel: threading.Event) -> Iterator[int]: ...


class MockEngine:
    """Replays a scripted completion (text) as token ids, one per step, then the end-of-turn token.  Given a list of
    scripts, each request gets the next one and the last one repeats (a tool call, then the answer after it)."""

    def __init__(self, tokenizer, script: str | list[str], max_context: int = 32768, delay_s: float = 0.0):
        self.tok, self.max_context, self.delay = tokenizer, max_context, delay_s
        end = tokenizer.encode(_server().IM_END, parse_special=True)
        self.scripts = [tokenizer.encode(x, parse_special=True) + end for x in ([script] if isinstance(script, str)
                                                                                 else script)]
        self.script, self.turns = self.scripts[0], 0
        self.last_prompt: list[int] = []

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.last_prompt = list(ids)
        self.last_embeddings = embeddings
        if len(self.scripts) > 1:
            self.script = self.scripts[min(self.turns, len(self.scripts) - 1)]
            self.turns += 1
        for t in self.script[:max_new]:
            if cancel.is_set():
                return
            if self.delay:
                time.sleep(self.delay)
            yield t


def unload_wait(value, default: float) -> float:
    """#1997: the `wait` of POST /unload?wait=...: absent / 0 / false: 0 (answer "busy" at once, as before); 1 / true /
    yes: `default` seconds; a number of seconds above 1: that long (at most an hour)."""
    if value is None:
        return 0.0
    v = str(value).strip().lower()
    if v in ("", "0", "false", "no", "off"):
        return 0.0
    if v in ("1", "true", "yes", "on"):
        return default
    try:
        return min(3600.0, max(0.0, float(v)))
    except ValueError:
        return default


ENGINE_REQUEST = re.compile(
    # "+ 12288 of 98179 read": a request cancelled while its prompt was read (#471)
    r"prompt (?P<prompt>\d+) tokens = (?P<reused>\d+) reused \+ \d+(?: of \d+)? read in (?P<read>[\d.]+) ms "
    r"\((?P<pp>[\d.]+) tok/s\), "
    r"(?P<gen>\d+) generated in (?P<gen_ms>[\d.]+) ms \((?P<tg>[\d.]+) tok/s\)")


_echoing: set[str] = set()      # the logs echo_requests already follows (restart() runs StrataEngine.__init__ again)


DRAFT_HEAD_FAIL = "the draft head does not fit"


DRAFT_HEAD_HINT = ("a smaller draft vocabulary needs less VRAM: --draft-vocab cyrillic (English, code and the Cyrillic "
                   "script) or --draft-vocab en (English and code, ~215 MiB less than the default). Start once with "
                   "it - START-HERE.bat --draft-vocab en (Windows) or ./setup.sh --draft-vocab en - and the model "
                   "keeps it; or a smaller --context in setup.")


def start_failure_hint(log: str | None, offset: int) -> str:
    """#474: what to change when the engine stopped at the start because the MTP draft head did not fit the VRAM
    left: the engine's own `strata mtp:` lines after that failure (0.1.36+: what it needs, what is free, the smaller
    subsets), else the same advice in words for an older engine.  "" for any other failure: the log says why."""
    if not log:
        return ""
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    if DRAFT_HEAD_FAIL not in text:
        return ""
    said = [x.strip()[len("strata mtp: "):] for x in text.splitlines()
            if x.strip().startswith("strata mtp: ") and ("draft head over" in x or "hint:" in x)]
    return ". mtp: " + DRAFT_HEAD_FAIL + ". " + (" ".join(said) if said else "Hint: " + DRAFT_HEAD_HINT)


def start_log_tail(log: str | None, offset: int, n: int = 20) -> str:
    """#496: the last n lines this start wrote to the engine log, for the error when the engine ended before READY -
    whatever the failure, the engine's own reason is in them (people posted the traceback without the log).  "" when
    there is no log or nothing in it from this start."""
    if not log:
        return ""
    try:
        with open(log, "rb") as f:
            f.seek(0, 2)
            start = max(offset, f.tell() - 64 * 1024)   # enough for 20 lines, never an earlier start's
            f.seek(start)
            text = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    lines = text.splitlines()[1 if start > offset else 0:]   # not a line cut in half
    lines = [x.rstrip() for x in lines if x.strip()][-n:]
    if not lines:
        return ""
    return "\nthe engine log's last lines:\n" + "\n".join("  " + x for x in lines)


# Windows NTSTATUS exit codes of a process the system ended (a crash, not an error the engine reported)
_WIN_CRASH = {0xC000001D: "illegal instruction (the CPU lacks an instruction the program uses)",
              0xC0000005: "access violation", 0xC0000409: "stack buffer overrun / fast-fail",
              0xC0000135: "a DLL the program needs was not found", 0xC0000139: "entry point not found in a DLL",
              0xC0000142: "a DLL failed to initialize", 0xC000007B: "bad image (32-bit / 64-bit mix-up)",
              0xC00000FD: "stack overflow", 0xC0000094: "integer division by zero", 0xC0000096: "privileged instruction"}


def engine_exit_words(rc: int | None) -> str:
    """What a process's exit status says, in words: "killed by signal 4 (SIGILL, Illegal instruction)" (a negative status
    on Linux / macOS), a Windows NTSTATUS crash code, or "exit code N".  "" when there is no status."""
    if rc is None:
        return ""
    if rc < 0 and os.name != "nt":
        try:
            sig = signal.Signals(-rc)
            return f"killed by signal {-rc} ({sig.name}, {signal.strsignal(sig) or sig.name})"
        except (ValueError, AttributeError):
            return f"killed by signal {-rc}"
    code = rc & 0xFFFFFFFF
    if code in _WIN_CRASH:
        return f"exit code 0x{code:08X}: {_WIN_CRASH[code]}"
    if 0xC0000000 <= code < 0xD0000000:
        return f"exit code 0x{code:08X} (a system error status)"
    return f"exit code {rc}"


def engine_crashed(rc: int | None) -> bool:
    """True when the engine process was ended by the system (an illegal instruction, a bad memory access, the
    out-of-memory killer, a missing DLL ...) rather than leaving by itself: nothing a second try fixes."""
    if rc is None:
        return False
    if rc < 0 and os.name != "nt":
        return -rc in {int(getattr(signal, n)) for n in ("SIGILL", "SIGSEGV", "SIGBUS", "SIGFPE", "SIGKILL")
                       if hasattr(signal, n)}
    return 0xC0000000 <= (rc & 0xFFFFFFFF) < 0xD0000000      # an NTSTATUS error code


def cpu_isa_words() -> tuple:
    """(text, missing): the CPU's model and which of AVX / AVX2 / FMA / F16C it reports (Linux: /proc/cpuinfo), and the
    ones of those it lacks.  ("", []) where it cannot be read."""
    try:
        text = Path("/proc/cpuinfo").read_text(errors="replace")
    except OSError:
        return "", []
    model = next((x.split(":", 1)[1].strip() for x in text.splitlines() if x.lower().startswith("model name")), "")
    flags = next((x.split(":", 1)[1].split() for x in text.splitlines() if x.lower().startswith("flags")), [])
    have = ", ".join(f"{f} {'yes' if f in flags else 'NO'}" for f in ("avx", "avx2", "fma", "f16c", "avx512f"))
    missing = [f for f in ("avx", "avx2", "fma", "f16c") if f not in flags]
    return f"{model or 'this CPU'} ({have})", missing


def start_exit_note(rc: int | None) -> str:
    """The sentence the start error carries about how the engine process ended (the engine log is silent when the
    system ends it): "" without a status, else a line, with the CPU's AVX flags after an illegal instruction."""
    words = engine_exit_words(rc)
    if not words:
        return ""
    note = f"\nthe engine process ended: {words}"
    if rc is not None and ((rc < 0 and os.name != "nt" and -rc == int(getattr(signal, "SIGILL", 4))) or
                           (rc & 0xFFFFFFFF) == 0xC000001D):
        isa, missing = cpu_isa_words()
        note += "\n  An illegal instruction: the engine ran an instruction this CPU cannot execute"
        if isa and missing:
            note += f" ({', '.join(m.upper() for m in missing)} missing; {isa})"
        elif isa:
            note += f"; the CPU reports AVX, AVX2, FMA and F16C ({isa}), so this is a bug in the engine"
        note += ".  Please report it with the CPU model (github.com/Niko1221/Strata/issues)."
    return note


def start_log_marks(log: str | None, offset: int) -> list:
    """The GPU runtime failure texts (TRANSIENT_START_MARKS) this start wrote to the log: what lets a retry notice say the
    GPU runtime failed.  [] when none, or no log."""
    if not log:
        return []
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            text = f.read(64 * 1024).decode("utf-8", "replace")
    except (OSError, ValueError):
        return []
    return [m for m in TRANSIENT_START_MARKS if m in text]


# A start that ends at once with the GPU runtime's own failure and none of the engine's lines: on ROCm, a start right
# after the previous engine exited can fail inside the runtime's device/queue set-up while the old process's queues are
# still being torn down ("terminate called after throwing an instance of 'rocr::AMD::hsa_exception'", or an exit with
# nothing in the log).  Such a start is tried again after a short wait (STRATA_START_RETRIES, default 3; 0: never).
TRANSIENT_START_MARKS = ("hsa_exception", "HSA_STATUS_ERROR", "hsaKmt")


START_RETRIES = max(0, int(os.environ.get("STRATA_START_RETRIES", "3") or 0))


def transient_start_failure(log: str | None, offset: int, elapsed_s: float, rc: int | None = None) -> bool:
    """True when the start that wrote the log from `offset` failed the transient way above: within 30 s, and its lines
    are only the launcher's own "engine started" line plus (optionally) a GPU runtime failure.  An exit with no line
    at all counts only when it was not the engine's own error exit (1: it said why on stdout)."""
    if not log or elapsed_s > 30.0:
        return False
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            text = f.read(64 * 1024).decode("utf-8", "replace")
    except (OSError, ValueError):
        return False
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    engine_lines = [x for x in lines if not x.startswith("[strata]")]
    if any(m in text for m in TRANSIENT_START_MARKS):
        return all(x.startswith("terminate called") or x.startswith("what()") or
                   any(m in x for m in TRANSIENT_START_MARKS) for x in engine_lines)
    # it exited without writing a single line of its own - but not when the system ended it (an illegal instruction, a
    # bad memory access, the OOM killer, a missing DLL): that is a crash a second try repeats, and the retry notice
    # must not call it a GPU runtime start (#2324: an old CPU's illegal instruction was retried 3 times as "GPU
    # runtime" and the real reason never shown)
    return not engine_lines and rc != 1 and not engine_crashed(rc)


def end_leftover_engines(exe: str) -> None:
    """Before an engine starts: end the ones a lost server left running (strata_control/procs.py)."""
    if os.environ.get("STRATA_KEEP_LEFTOVERS") == "1":
        return
    try:
        from strata_control import procs
        say = lambda text: print(text, flush=True)        # noqa: E731
        settle = float(os.environ.get("STRATA_LEFTOVER_SETTLE_S", "10") or 10)
        stuck = [r["pid"] for r in procs.end_leftovers(say=say, settle=settle)["stuck"]]
        stuck += [r["pid"] for r in procs.end_orphans(exe, say=say, settle=settle) if r["outcome"] == "stuck"]
        if stuck:
            print(f"[strata] WARNING: the engine from an earlier run (process {', '.join(map(str, stuck))}) was told to stop "
                  f"but still holds its memory after {settle:.0f} s.", flush=True)
    except Exception:
        pass


def echo_requests(log_path: str, offset: int) -> None:
    """STRATA_REQUEST_LINES=1: one stdout line per finished request, from the engine's own summary in its log.

    The engine's stderr goes to the log file (the start narrator reads it), so a supervisor that only sees this
    process's output - a tray, llama-swap - has no per-request numbers. This re-states the engine's line with the
    total the two times make: `request prompt P cached C output O prompt_read R ms total S ms prefill X tok/s decode Y
    tok/s` (prompt_read: the time the engine spent reading the prompt's new tokens, not a time to first token).
    """
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.2)
                continue
            m = ENGINE_REQUEST.search(line)
            if m:
                read_ms, gen_ms = float(m["read"]), float(m["gen_ms"])
                print("[strata] request prompt %s cached %s output %s prompt_read %.0f ms total %.0f ms prefill %s "
                      "tok/s decode %s tok/s" % (m["prompt"], m["reused"], m["gen"], read_ms, read_ms + gen_ms, m["pp"],
                                                 m["tg"]), flush=True)


def experts_loading_words(args: list, size: str) -> str:
    """#505: what the start does with the experts, by the engine's flags (generate.cpp's option parsing): a RAM budget
    copies the hottest N GiB into RAM (--resident-budget-gib), the resident low-RAM mode the ones the GPU does not hold
    (--resident-experts), plain --mmap-experts reads them from the model files through the OS file cache (nothing is
    loaded into RAM up front); otherwise all of them go into RAM."""
    if "--resident-budget-gib" in args:
        try:
            n = f"up to {float(args[args.index('--resident-budget-gib') + 1]):g} GiB"
        except (IndexError, ValueError):
            n = "a RAM budget"
        return (f"loading the most-used experts into RAM ({n}; the rest are read from the model files as needed) "
                "and locking part of them for the GPU.")
    if "--resident-experts" in args:
        return (f"loading the experts the GPU does not hold into RAM (of {size}) and locking part of them for the "
                "GPU.")
    if "--mmap-experts" in args:
        return (f"mapping the experts from the model files ({size}, --mmap-experts): they are not loaded into RAM - "
                "the OS file cache reads them as the GPU's expert cache fills and as requests need them.")
    return f"loading the experts into RAM ({size}) and locking part of them for the GPU."


# The engine's memory guard, when the RAM it wanted for the experts is not available at the start (#467): it keeps
# what fits and reads the rest from the model files - every long prompt is then slow (2026-11-15: an image prompt read
# for 339 s).  "resident complement W GiB exceeds available RAM ... ; K GiB of the experts the GPU does not hold".
DEGRADED_START = re.compile(r"whole resident RAM mode does not fit .*?resident complement ([\d.]+) GiB.*?"
                            r"([\d.]+) GiB of the experts the GPU does not hold")


DEGRADED_HEADROOM_GIB = 4.0 + 1.0       # the engine's safety headroom, and a margin


def degraded_start(log_path: str | None, start: int) -> dict | None:
    """{"wanted_gib", "kept_gib", "since"} when this start's log lines carry the memory guard's warning, else None."""
    if not log_path:
        return None
    try:
        with open(log_path, "rb") as f:
            f.seek(max(start, os.path.getsize(log_path) - (8 << 20)))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    hits = list(DEGRADED_START.finditer(text))
    if not hits:
        return None
    m = hits[-1]
    return {"wanted_gib": float(m.group(1)), "kept_gib": float(m.group(2)), "since": round(time.time(), 1)}


def mem_available_gib() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1 << 20)
    except OSError:
        pass
    return 0.0


def narrate_start(log_path: str, offset: int, args: list, done: threading.Event, heartbeat=20.0) -> None:
    """While the engine starts, say in the server window what it is doing, from its log: the start reads tens of GB
    into RAM and locks part of it for the GPU, and on many PCs everything is slow or frozen for a minute or more -
    people closed the window thinking it had hung.  The warning comes at that step, not after it."""
    gb = 0.0
    if "--native" in args:                              # about the size of the experts it will read
        try:
            gb = os.path.getsize(args[args.index("--native") + 1]) / 1e9
        except (OSError, IndexError):
            pass
    size = f"about {gb:.0f} GB" if gb >= 1 else "tens of GB"
    loading = experts_loading_words(args, size)
    t0 = last = time.time()
    said = set()

    def say(key, text):
        nonlocal last
        if key not in said:
            said.add(key)
            last = time.time()
            print(text, flush=True)

    say("weights", "[strata] starting the engine: reading the model's weights ...")
    pos = offset
    while not done.wait(0.5):
        try:
            with open(log_path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
        except OSError:
            chunk = b""
        if chunk.count(b"\n"):
            cut = chunk.rfind(b"\n") + 1
            pos += cut
            for line in chunk[:cut].decode("utf-8", "replace").splitlines():
                if "PLE on" in line or "expert arena:" in line or "experts via mmap" in line:   # #505: mapped
                    say("arena", f"[strata] {loading}\n"
                                 "         YOUR PC CAN BE SLOW OR STOP RESPONDING FOR 1-3 MINUTES NOW - this is normal.\n"
                                 "         Please wait and don't close this window; the browser opens when it is ready.")
                elif " loaded " in line and "GiB at" in line:
                    say("loaded", "[strata] experts loaded: " + line.split(" loaded ", 1)[1].strip() +
                        f" ({time.time() - t0:.0f} s so far)")
                elif "expert cache " in line and " slots, " in line and "auto" not in line:
                    n = line.split("expert cache ", 1)[1].split(";")[0].replace(" slots,", " experts,").strip()
                    say("cache", f"[strata] filling the GPU's expert cache ({n}) ...")
                elif "session is up" in line:
                    say("up", "[strata] almost ready ...")
        if time.time() - last > heartbeat:
            last = time.time()
            print(f"[strata] still starting ({time.time() - t0:.0f} s) - please wait ...", flush=True)


class ConvCacheLog:
    """#596: the engine's conversation cache as its log tells it (the engine writes "strata serve: conversation
    cache: parked N tokens ...; parked=P bytes=B evictions=E" and "restored N tokens ...; parked=P bytes=B" to stderr,
    which is the log): read on from where it was last read, from the start of the engine's current run."""
    # #879: these two completed recovery messages follow ConversationCache::clear(), which removes every parked
    # entry and its retained K/V.  Keep history counters: the clear is not a cache park or restore event.
    CLEARED = re.compile(
        r"strata serve: after non-finite logits \(#879\): (?:the restored session replaces the live one; dropped \d+ parked "
        r"conversations?|dropped the live session, \d+ checkpoints?, \d+ parked conversations? and \d+ idle slots? "
        r"\(\d+ running slots? not kept after their reply\); reading this prompt from token 0)$")
    EVENT = re.compile(r"conversation cache: (parked|skipped|restored) (\d+) tokens.*?parked=(\d+) bytes=(\d+)"
                       r"(?: evictions=(\d+))?")
    DROPPED = re.compile(r"conversation cache: dropped \d+ superseded .*?parked=(\d+)")
    READ_MAX = 1 << 20                                  # at most the last MiB of new lines per read

    def __init__(self):
        self.key, self.pos = None, 0
        self.lock = threading.Lock()                    # polls come from several request / monitor threads at once
        self.reset()

    def reset(self):
        self.state = {"parked": 0, "bytes": 0, "evictions": 0, "parks": 0, "restores": 0, "last_event": None,
                      "last_tokens": None, "last_at": None}

    def poll(self, path, start) -> dict:
        """The state after the log's new lines; `start` is where the engine's current run began in it.  One poll at a
        time: a second one moved `pos` between the size check and the seek and raised ValueError (negative seek)."""
        with self.lock:
            return self._poll(path, start)

    def _poll(self, path, start) -> dict:
        if not path or start is None:
            return dict(self.state)
        if self.key != (path, start):                   # another start of the engine: its cache starts empty
            self.key, self.pos = (path, start), start
            self.reset()
        try:
            size = os.path.getsize(path)
            if size < self.pos:                         # the log was emptied or replaced
                self.pos = 0
            if size - self.pos > self.READ_MAX:
                self.pos = size - self.READ_MAX
            with open(path, "rb") as f:
                f.seek(self.pos)
                data = f.read(size - self.pos)
        except OSError:
            return dict(self.state)
        end = data.rfind(b"\n") + 1                     # whole lines only: the rest is read next time
        self.pos += end
        now = time.time()
        for line in data[:end].decode("utf-8", "replace").splitlines():
            if "conversation cache:" not in line:
                if self.CLEARED.fullmatch(line):
                    self.state["parked"] = self.state["bytes"] = 0
                continue
            m = self.EVENT.search(line)
            if m:
                st = self.state
                st["parked"], st["bytes"] = int(m.group(3)), int(m.group(4))
                if m.group(5) is not None:
                    st["evictions"] = int(m.group(5))
                if m.group(1) != "skipped":
                    st["parks" if m.group(1) == "parked" else "restores"] += 1
                    st["last_event"], st["last_tokens"], st["last_at"] = m.group(1), int(m.group(2)), now
                continue
            m = self.DROPPED.search(line)
            if m:
                self.state["parked"] = int(m.group(1))
        return dict(self.state)


def conversation_slots(engine) -> int | None:
    """The number of conversation slots the engine can keep at once (--conversation-cache-slots, or the INFO line's
    conversation_cache_slots). None when not set."""
    args = engine.spawn[1] if hasattr(engine, "spawn") else []
    if "--conversation-cache-slots" in args[:-1]:
        try:
            return int(args[args.index("--conversation-cache-slots") + 1])
        except ValueError:
            pass
    slots = (getattr(engine, "info", None) or {}).get("conversation_cache_slots")
    return slots if isinstance(slots, int) else None


def conversation_cache_view(info: dict, hist: list, totals: dict, parked: dict) -> dict:
    """#596: the Monitor's Conversation cache card: the parked conversations (the engine's opt-in
    --conversation-cache-mib: budget, slots, what its log says) and how much of the prompts the cache gave back."""
    mib = info.get("conversation_cache_mib")
    last = hist[-1] if hist else None
    return {"enabled": isinstance(mib, int) and mib > 0, "budget_mib": mib if isinstance(mib, int) else None,
            "slots": info.get("conversation_cache_slots"), **parked,
            "requests": len(hist), "requests_reused": sum(1 for r in hist if (r.get("reused") or 0) > 0),
            "reused_tokens": totals.get("reused", 0), "prompt_tokens": totals.get("prompt_tokens", 0),
            "last_reused": last.get("reused") if last else None,
            "last_prompt": last.get("prompt_tokens") if last else None}


_BTRACE = bool(os.environ.get("STRATA_BATCH_TRACE"))


def btrace(*a):
    if _BTRACE:
        print("[batch-trace]", threading.get_ident() % 10000, *a, file=sys.stderr, flush=True)


EOS_IDS = {248044, 248046}   # <|endoftext|>, <|im_end|>: the engine's default --eos-ids


# The engine's own words for a verifier that cannot go on (its GPU waits were released, or an earlier window never
# finished, #267): the process may stay alive and even print DONE, but it must not take another request.
FATAL_PREFIXES = ("ERR verify: timed out at layer ", "ERR verify batch: timed out at layer ",
                  "ERR verify: an earlier window never finished", "ERR verify batch: an earlier window never finished")


# Monitoring only (2026-11-15: 2 of 6 image requests that day ended on "verify: timed out at layer N"): one JSON line per
# fatal verify stall, with whether the request carried an image, so the pattern can be counted (dl_sessiond /status).
# main() sets it; None (tests that import this module) writes nothing
STALL_LOG: Path | None = None


def log_stall(line: str, engine) -> None:
    if _server().STALL_LOG is None:
        return
    m = re.search(r"at layer (\d+)", line)
    progress = getattr(engine, "progress", None) or (None, None)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": line[4:].strip()[:200],
           "layer": int(m.group(1)) if m else None, "prompt_tokens": progress[1],
           "image": bool(getattr(engine, "cur_image", False)), "degraded": bool(getattr(engine, "degraded", None))}
    try:
        _server().STALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_server().STALL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


class StrataEngine:
    """The resident engine: `strata --serve` reads `GEN <max_new> <ids>` lines and streams `T <id>` lines, then
    `DONE ...`.  Requests are serialized by the service's FIFO, so one pipe is enough.

    Per-request sampling rides the same line as engine-side keys between max_new and the ids
    (`temperature=F top_p=F top_k=N seed=N`, the engine's own spelling).  An absent temperature keeps the
    engine's default, which is greedy; `temperature=0` means the same thing, so it is not forwarded.
    """
    silence_s = ENGINE_SILENCE_S         # #481: main() sets the config's engine_silence_s (survives restart())
    silent_note = None                   # #481: why the server ended a silent engine (death_note says it)
    gpu_busy = None                      # #1317: () -> bool, "the GPU is working" (the telemetry's reading); a GPU at work is not frozen
    last_err = None                      # #997: an ERR that was its last stdout line (death_note says it)
    batch = 0                            # --batch: the engine's batch slots (0: one request at a time)

    # `last`: the figures of the engine's last DONE line.  With batch slots several requests run at once, each on its
    # own thread, so each one reads its own request's figures (Service.run records them); one at a time, the one dict.
    @property
    def last(self):
        if self.batch:
            tl = self.__dict__.setdefault("_tl", threading.local())
            if not hasattr(tl, "last"):
                tl.last = {}
            return tl.last
        return self.__dict__.get("_last", {})

    @last.setter
    def last(self, value):
        self.__dict__["_last"] = value
        if self.batch:
            tl = self.__dict__.setdefault("_tl", threading.local())
            tl.last = value

    def __init__(self, exe: str, args: list[str], cwd: str | None = None, log: str | None = None,
                 env: dict | None = None, lazy: bool = False, cpus: list[int] | None = None, _attempt: int = 0,
                 cfg: dict | None = None, retry_args=None, **kw):
        self.cfg = cfg
        self.spawn = (exe, list(args), cwd, log, env, False, cpus)   # to start it again after it died (issue #27)
        self.session_save_reclaim = '--session-save-reclaim' in args
        paths = {k: v for k, v in zip(args, args[1:]) if k in ("--native", "--pack")}
        self.model_path = paths.get("--native") or paths.get("--pack", "pack/full")
        self.log_path = log
        self.proc, self.pump, self.log = None, None, None
        self.ended, self.unloaded = True, True
        self.max_context = int(args[args.index("--max-context") + 1]) if "--max-context" in args else 4096
        self.can_stop = False            # the engine honours a STOP line mid-request (READY <ctx> stop)
        self.last = {}
        self.info = {}                   # INFO key=value facts (engine 0.1.8+): kv, expert slots, ... (Monitor tab)
        self.prefill_tok_s_mean = None
        self.progress = None             # (read, total) prompt tokens while a prompt is read, from PP lines
        self.progress_ms = 0             # PP's own milliseconds since the prompt started (its third field)
        self.reused = 0                  # RESUME: prompt tokens not read again (a client takes them out of the work)
        self.silent_note = None
        self.last_err = None
        try:                            # a ready-made engine's BUILD.json says its version
            self.info["version"] = json.loads((Path(exe).parent / "BUILD.json").read_text()).get("version")
        except (OSError, ValueError):
            self.info["version"] = None
        if lazy:
            return
        self.unloaded = False            # `ended` stays True until READY (below): not alive while starting (#344)
        self.log = open(log, "a", encoding="utf-8") if log else subprocess.DEVNULL
        loading = threading.Event()                     # set once READY: the narrator below stops
        log_start = os.path.getsize(log) if log else 0  # where this start's lines begin (start_failure_hint)
        self.log_start = log_start                      # #596: the Monitor's conversation cache reads from here
        if log:
            threading.Thread(target=_server().narrate_start, args=(log, os.path.getsize(log), args, loading),
                             daemon=True).start()
            # once per log: the follower keeps reading the same (appended) log across restarts and reloads
            if os.environ.get("STRATA_REQUEST_LINES") and os.path.abspath(log) not in _echoing:
                _echoing.add(os.path.abspath(log))
                threading.Thread(target=echo_requests, args=(log, os.path.getsize(log)), daemon=True).start()
        if log:                                          # #779: when an engine started (a crash report has the time)
            try:
                self.log.write(f"[strata] {time.strftime('%Y-%m-%d %H:%M:%S')} engine started: {exe} --serve "
                               f"{' '.join(args)}\n")
                self.log.flush()
            except OSError:
                pass
        self.max_context = 0                             # before the new process is visible: never its predecessor's
        pin = {}
        if cpus and hasattr(os, "sched_setaffinity"):    # replicas: this engine's own physical cores (serve/replicas.py)
            pin["preexec_fn"] = lambda: os.sched_setaffinity(0, cpus)
        spawned_at = time.monotonic()
        self.proc = _server().popen("the Strata engine", [exe, "--serve", *args], cwd=cwd, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8", errors="replace", bufsize=1, env=env, **pin)
        _server().contain(self.proc)                               # ends with the server, however it ends (Windows)
        proc = self.proc                                 # THIS start's process: a close() from another thread may set self.proc to None meanwhile (#4792)
        # the READY read has a timeout (#1317): the lines come from a thread, up to READY, so the rest of the stream
        # stays for _pump (one reader at a time)
        ready_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._ready_pump, args=(self.proc, ready_q), daemon=True).start()
        start_wait_s = calculate_start_wait(getattr(self, "cfg", None), self.model_path)
        ready_deadline = None if start_wait_s is None or start_wait_s <= 0 else time.monotonic() + start_wait_s
        timed_out = False
        while True:
            left = None if ready_deadline is None else ready_deadline - time.monotonic()
            if left is not None and left <= 0:
                timed_out = True
                break
            try:
                line = ready_q.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith("INFO "):
                for kv in line.split()[1:]:
                    k, _, v = kv.partition("=")
                    self.info[k] = int(v) if v.lstrip("-").isdigit() else v
            if line.startswith("READY"):
                f = line.split()
                self.max_context = int(f[1])
                self.can_stop = "stop" in f[2:]
                break
        loading.set()
        if self.max_context <= 0:
            if timed_out:                               # still loading, or hung: end it, so the turn is not held for good
                try:
                    proc.kill()
                except OSError:
                    pass
            try:                                        # its pipes and our handle on its log (the log stays)
                proc.wait(timeout=5)
                proc.stdin.close()
                proc.stdout.close()
                if log:
                    self.log.close()
            except (OSError, subprocess.TimeoutExpired):
                pass
            if not timed_out and _attempt < _server().START_RETRIES and \
                    _server().transient_start_failure(log, log_start, time.monotonic() - spawned_at, proc.returncode):
                wait_s = 2.0 * (2 ** _attempt)              # 2, 4, 8 s: the previous process's GPU queues go away
                exit_words = engine_exit_words(proc.returncode)
                if start_log_marks(log, log_start):         # the runtime said so itself (hsa_exception ...)
                    print(f"[strata] the engine stopped while the GPU runtime was starting (most often right after "
                          f"another engine exited, whose GPU queues were still being released"
                          f"{'; ' + exit_words if exit_words else ''}): starting it again in {wait_s:.0f} s "
                          f"(try {_attempt + 2} of {_server().START_RETRIES + 1})", flush=True)
                else:                                       # an exit with nothing in the log: say only what is known
                    print(f"[strata] the engine exited before it wrote anything to its log"
                          f"{' (' + exit_words + ')' if exit_words else ''}; it may be a GPU runtime that was not "
                          f"ready yet: starting it again in {wait_s:.0f} s (try {_attempt + 2} of {_server().START_RETRIES + 1})",
                          flush=True)
                time.sleep(wait_s)
                StrataEngine.__init__(self, exe, args, cwd, log, env, lazy, cpus, _attempt + 1, cfg=getattr(self, "cfg", None))
                return
            why = (f"the engine did not report READY within {start_wait_s:.0f} s" if timed_out else
                   "the engine exited before it was ready")
            # EngineDied, not bare RuntimeError: a request waiting on this load must end with a 503
            # through the request path's handler - a RuntimeError there left the turn with no answer (#1527)
            note = "" if timed_out else start_exit_note(proc.returncode)
            tail = start_log_tail(log, log_start)
            lines = [x for x in tail.split("\n")[2:] if x.strip()]
            if tail and lines and all(x.strip().startswith("[strata]") for x in lines):
                tail += "\n  (those are the launcher's own lines: the engine itself wrote nothing)"
            raise EngineDied(why + (f" (see {log})" if log else "") + note +
                             start_failure_hint(log, log_start) + tail)
        self.known_ctx = self.max_context   # survives a failed restart: requests keep their limit and restart it
        # (from PR #41, midhatn) a locally built engine can sit next to another release's BUILD.json: engines that
        # report their own version (INFO engine=, 0.1.8+) win, the manifest stays the fallback for older ones
        if self.info.get("engine"):
            self.info["version"] = str(self.info["engine"])
        self.ended = False                              # READY: alive from here (restart() set it True, #344)
        self.degraded = degraded_start(log, log_start)  # short of RAM at the start: /health says so, idle reload
        if self.degraded:
            print(f"[strata] WARNING: the engine started short of memory: {self.degraded['kept_gib']:g} of "
                  f"{self.degraded['wanted_gib']:g} GiB of experts in RAM, the rest read from disk (slow); it reloads "
                  "when idle and the memory is free", flush=True)
        # the engine's stdout on a thread, so a request can wait with a timeout (heartbeats, cancel checks)
        self.lines: queue.Queue = queue.Queue()
        # --batch: concurrent requests in the engine's batch slots (see generate_batched).  The engine says how many
        # it runs (INFO batch_slots=N: it may have fewer than asked, or none, when they do not fit)
        asked = next((int(args[args.index(k) + 1]) for k in ("--batch", "--slots") if k in args), 0)
        self.batch = int(self.info.get("batch_slots") or 0)
        if asked and self.batch != asked:
            print(f"[strata] parallel requests: {asked} asked, the engine runs {self.batch or 'one at a time'} "
                  "(its log says why)", flush=True)
        _bg = args[args.index("--batch-groups") + 1] if "--batch-groups" in args else "default"
        # no `--batch-groups` (the default on a layer split) or `auto`: the engine picks the groups and says so
        # (INFO batch_groups=G); a number is the group count asked for (1 = off)
        groups = int(self.info.get("batch_groups") or 1) if _bg in ("auto", "default") else int(_bg)
        groups = groups if self.batch and groups > 0 and self.batch % groups == 0 else 1
        gs = self.batch // groups if self.batch else 0
        # slots in the order that spreads requests over the pipeline's groups first: 0, gs, 2gs, .., 1, gs+1, ..
        self.slot_order = [g * gs + t for t in range(gs) for g in range(groups)]
        self.slot_group = [b // gs if gs else 0 for b in range(self.batch)]   # each slot's pipeline group
        self.slot_groups = groups
        # pipelined groups (the engine says how many it runs: INFO batch_groups; older engines: the args).  A pipelined
        # group's window spans its slots up to its last busy one, and the engine keeps no pipelined slot as a
        # conversation cache - see pick_slot
        groups_run = int(self.info.get("batch_groups") or groups)
        self.slot_gs = gs if groups > 1 and groups_run > 1 else 0
        self.slot_q = [queue.Queue() for _ in range(self.batch)]
        self.slot_busy = [False] * self.batch
        # #1603: who owns a busy flag.  slot_claims: slots a request of this server picked or reserved and has not
        # given back; slot_releasing: slots handed to the background BDONE wait.  A busy slot in neither has no owner
        # (its flag leaked) and would keep every later request waiting for a slot that nothing will free.
        self.slot_claims: set[int] = set()
        self.slot_releasing: set[int] = set()
        self._orphan_seen: dict[int, float] = {}
        # what each slot's sessions hold (prompt + every token a window fed), so a conversation's next turn goes to
        # the slot that has its start (the engine checks it again); when the slot was last used
        self.slot_held: list[list[int]] = [[] for _ in range(self.batch)]
        self.slot_used = [0.0] * self.batch
        self.slot_live: list[dict | None] = [None] * self.batch   # /metrics: the request in each slot
        # #1012: the admission state belongs to the server, not to one engine process.  restart() runs this again
        # while requests still wait on it (they hold these very objects), so it is made once and kept: new ones
        # would leave the waiters on a lock and a condition nobody notifies, with their counts missing from the
        # new lists.
        if "slot_cv" not in self.__dict__:
            self.slot_cv = threading.Condition()
            self.waiting = 0                            # requests waiting for the control lines (ctl)
            self.admitting = 0                          # #1603: ... and those that gave the lines back to wait for a slot
            self.wait_lens: list[list[int]] = []        # ... their prompt lengths (a long read gives way to short ones)
            self.ctl_epoch = 0                          # how often the control lines were taken
            self.ctl = threading.Lock()                 # one admission or solo request on the control lines at a time
        self.gen = self.__dict__.get("gen", 0) + 1      # which engine process this is (a request notes its own)
        self._ctl_erred = False                         # #1059: the control lines ended on an ERR
        self._yielded = None                            # (slot, tokens read): the last request on them gave way
        self.wlock = threading.Lock()                   # stdin writes from several request threads
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self):
        proc, lines = self.proc, self.lines             # this process's: a restart replaces both (#344)
        slot_q = self.slot_q
        log = getattr(self, "log", None)                # retain this process's log across a restart
        line = None
        for line in proc.stdout:
            # stderr already reaches the log; native ERR diagnostics use the protocol pipe.
            if line.startswith("ERR ") and log not in (None, subprocess.DEVNULL):
                try:
                    log.write(f"[strata] {time.strftime('%Y-%m-%d %H:%M:%S')} native {line.rstrip()}\n")
                    log.flush()
                except (OSError, ValueError):          # a closed/full log must not prevent EOF publication
                    pass
            # checked before batch routing: a fatal line is never a slot's own
            if line.startswith(FATAL_PREFIXES):
                log_stall(line, self)
                # release_gpu_waits invalidates the verifier, even if the native
                # process stays alive and prints DONE afterwards.
                if self.proc is proc:
                    self.silent_note = "Unrecoverable native verification failure: " + line[4:].strip()
                    self.ended = True
                try:
                    proc.terminate()
                except OSError:
                    pass
                break                           # publish EOF, never the trailing DONE
            if line.startswith(("BT ", "BDONE ")) and slot_q:   # --batch: a batch slot's own lines
                try:
                    slot_q[int(line.split()[1])].put(line)
                    continue
                except (IndexError, ValueError):
                    pass
            lines.put(line)
        if self.proc is proc:                           # a killed engine's pump must not mark its successor dead
            self.ended = True                           # its output closed: it is gone, even before the OS says so
            if line and line.startswith("ERR"):         # #997 #890: why it exited, though no request may read it
                self.last_err = line[4:].strip()        # (a failed batch window: every request reads its slot)
        lines.put(None)
        for q in slot_q:
            q.put(None)

    def death_note(self) -> str:
        """Why the engine most likely ended, from the end of its log: its own watchdog (issue #29), else RAM."""
        if getattr(self, "silent_note", None):          # #481: the server ended it, not the OS or the engine itself
            return self.silent_note
        tail = wide = ""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 262144))
                wide = f.read().decode("utf-8", "replace")
            tail = wide[-4096:]
        except (OSError, TypeError):
            pass
        # #1705: STRATA_VERIFY_TRACE dumps are ~30 KB and push the watchdog's line out of a 4 KB tail
        for line in reversed(wide.splitlines()):
            if "issue #29" in line:
                return ("The engine stopped itself because it had stopped making progress - a hang it caught. Its log "
                        "line: " + line.strip() + " - please report it at github.com/Niko1221/Strata/issues.")
        if (self.last_err or "").startswith("fatal GPU error"):    # #4350: the engine ended itself; the next request starts it again
            return ("The graphics card reported a fatal error (" + self.last_err[len("fatal GPU error:"):].strip()[:160] + "), so the engine "
                    "ended. The next request starts it again. If this repeats, please report it at github.com/Niko1221/Strata/issues "
                    "with the log.")
        proc = self.proc                                 # None while a restart has not started the next one yet
        rc = proc.poll() if proc is not None else None
        if rc is not None and rc >= 0 and self.last_err:  # its own last words on stdout: they say why
            return (f"The engine exited (code {rc}) after it reported: {self.last_err} - please report it at "
                    "github.com/Niko1221/Strata/issues with the log.")
        last = next((x.strip() for x in reversed(tail.splitlines()) if x.strip().startswith(("strata", "ERR"))), "")
        if rc is not None and rc >= 0 and last:          # it ended by itself: its own last words say why (#215)
            return (f"The engine exited (code {rc}). Its last log line: {last} - if that does not explain it, please "
                    "report it at github.com/Niko1221/Strata/issues with the log.")
        return ("The usual cause is running out of RAM: Linux then ends the biggest program (check: sudo dmesg | "
                "grep -i -E 'killed process|out of memory'); Windows slows down instead. Close other programs or use a "
                "smaller model (Q2_0 / IQ2_XS).")

    def alive(self) -> bool:
        proc = self.proc                                 # read once: restart() / close() may set it to None meanwhile
        return proc is not None and not getattr(self, "ended", False) and proc.poll() is None

    def exit_code(self):
        if self.proc is None:
            return None
        try:
            return self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return None

    def unload(self):
        """Release GPU/RAM between requests, retaining the spawn config for automatic reloading."""
        self.close()
        self.unloaded = True

    RESTART_RETRY_S = 15.0   # between the tries of restart(): a dying engine's VRAM may take a while to come back

    @staticmethod
    def _ready_pump(proc, out: queue.Queue) -> None:
        """The engine's first lines up to READY, for a read that can time out; None when its output closed first."""
        done = False
        try:
            for line in proc.stdout:
                out.put(line)
                if line.startswith("READY"):
                    done = True
                    return
        except (OSError, ValueError):                   # the pipe closed under us (the engine was killed)
            pass
        finally:
            if not done:
                out.put(None)

    def restart(self, tries: int = 3):
        """Start the engine again (the same command) after it died; the new process has its own line queue.
        close() ends and waits for the old process first (EngineStuck when it cannot be ended).  A start that still
        exits before READY - a dead engine's VRAM can take a while to come back, notably on ROCm - is retried
        (PR #637)."""
        info = dict(self.info)
        self.starting = True                     # prepare() answers 503 "starting" meanwhile (#344)
        try:
            self.close()
            for i in range(tries):
                # #344: not alive until READY - __init__ sets max_context to 0 and blocks until the engine says
                # READY, and a request that saw alive() in that window skipped load() and failed with "context
                # (0)".  __init__ clears `ended` itself once READY (before its pump thread can set it again).
                self.ended = True
                try:
                    self.__init__(*self.spawn)
                    break
                except RuntimeError:
                    try:
                        self.proc.wait(timeout=60)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                    if i == tries - 1:
                        raise
                    print(f"[strata] the engine did not start (try {i + 1} of {tries}); again in "
                          f"{self.RESTART_RETRY_S:g} s", flush=True)
                    time.sleep(self.RESTART_RETRY_S)
        finally:
            self.starting = False
            # a lazy first start never reached the post-READY __init__ where slot_cv is made (#1527)
            if "slot_cv" in self.__dict__ or hasattr(self, "slot_cv"):
                slot_cv = getattr(self, "slot_cv", None)
                if slot_cv is not None:
                    with slot_cv:                   # #1012: wake the requests that waited through it: they go on with the
                        slot_cv.notify_all()        # new engine, or (it did not start) end with a clean EngineDied
        self.info = {**info, **self.info}

    def _parse_done(self, line):
        f = line.split()
        self.last = {"generated": int(f[1]), "prompt_tokens": int(f[2]), "prompt_ms": float(f[3]),
                     "decode_ms": float(f[4]), "finish": f[5]}
        if len(f) >= 9:                                   # the conversation cache's fields (engine 0.1.3+)
            self.last.update(drafts_accepted=int(f[6]), drafts_offered=int(f[7]), reused=int(f[8]))
        if len(f) >= 11:                                  # decode hit rate fields
            self.last.update(hits=int(f[9]), lookups=int(f[10]))
        if len(f) >= 14:                                  # the expert tiers (engine 0.1.31+): RAM / file blobs, file MB
            self.last.update(ram_blobs=int(f[11]), file_blobs=int(f[12]), file_mb=float(f[13]))
        if len(f) >= 15:                                  # #471 (engine 0.1.36+): the prompt tokens actually read
            self.last.update(prompt_read=int(f[14]))
        if len(f) >= 16:                                  # #588 (engine 0.1.39+): routed experts read over PCIe
            self.last.update(offloaded=int(f[15]))

    def vram(self, reserve_mib: int | None, timeout: float = 120.0) -> dict:
        """#533: `VRAM <reserve_mib>` between requests (the caller holds the service's FIFO): the engine shrinks its
        expert cache until that much VRAM is free, or grows it back when more is free; None: back to the reserve it
        started with.  -> the engine's figures (expert_slots, expert_cache_mib, vram_free_mib, ...); raises ValueError
        with the engine's reason (e.g. it was not started with --vram-elastic), EngineDied when it ended."""
        if not self.alive():
            raise EngineDied("the engine is not running")
        self.proc.stdin.write("VRAM" + ("" if reserve_mib is None else f" {int(reserve_mib)}") + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                raise EngineDied("the engine did not answer the VRAM command") from None
            if line is None:
                raise EngineDied("the engine ended")
            line = line.strip()
            if line.startswith("ERR"):
                raise ValueError(line[4:].strip() or "the engine refused the VRAM command")
            if line.startswith("VRAM "):
                out = {}
                for kv in line.split()[1:]:
                    k, _, v = kv.partition("=")
                    out[k] = int(v) if v.lstrip("-").isdigit() else v
                self.info.update({k: out[k] for k in ("expert_slots", "vram_free_mib") if k in out})
                self.info["vram"] = out
                return out
            if time.time() > deadline:
                raise EngineDied("the engine did not answer the VRAM command")

    @staticmethod
    def sampling_keys(sampling: dict) -> str:
        keys = ""
        t = sampling.get("temperature")
        if isinstance(t, (int, float)) and float(t) > 0.0:
            keys += f" temperature={float(t)!r}"
        tp = sampling.get("top_p")
        if isinstance(tp, (int, float)) and float(tp) < 1.0:
            keys += f" top_p={float(tp)!r}"
        tk = sampling.get("top_k")
        if isinstance(tk, int) and not isinstance(tk, bool) and tk >= 0:
            # the engine's sampled path keeps at most 64 candidates: 0 ("off") and wider lists get all 64
            keys += f" top_k={tk if 1 <= tk <= 64 else 64}"
        mp = sampling.get("min_p")
        if isinstance(mp, (int, float)) and 0.0 < float(mp) <= 1.0:
            keys += f" min_p={float(mp)!r}"
        rp = sampling.get("repetition_penalty")
        rp_on = isinstance(rp, (int, float)) and float(rp) != 1.0
        pf = sampling.get("frequency_penalty")
        pf_on = isinstance(pf, (int, float)) and float(pf) != 0.0
        pp = sampling.get("presence_penalty")
        pp_on = isinstance(pp, (int, float)) and float(pp) != 0.0
        if rp_on:
            keys += f" penalty_repeat={float(rp)!r}"
        if pf_on:
            keys += f" penalty_freq={float(pf)!r}"
        if pp_on:
            keys += f" penalty_present={float(pp)!r}"
        if rp_on or pf_on or pp_on:
            # a penalty without a window counts over nothing: the engine's default is the last 64 tokens
            pln = sampling.get("penalty_last_n")
            if isinstance(pln, int) and not isinstance(pln, bool) and pln > 0:
                keys += f" penalty_last_n={pln}"
            else:
                keys += " penalty_last_n=64"
        seed = sampling.get("seed")
        if isinstance(seed, int) and seed > 0:
            keys += f" seed={seed}"
        # setup's calibration (tools/calibrate.py): engine settings for this request only, measured without a restart
        tune = sampling.get("strata_tune")
        if isinstance(tune, dict):
            for k in ("pcie_frac", "spec_min_p"):
                v = tune.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0:
                    keys += f" {k}={float(v)!r}"
            # --aux-cpus for this request: 1 puts the engine's threads that are neither pool workers nor the host on the
            # spare CPUs, 0 leaves them where they were created (true/false or 1/0; the engine started without a spare CPU
            # ignores a 1).  Anything else is not sent.
            ac = tune.get("aux_cpus")
            if isinstance(ac, bool) or (isinstance(ac, (int, float)) and ac in (0, 1)):
                keys += f" aux_cpus={int(ac)}"
        # "strata_checkpoint": false - a one-shot call (a classification, a probe) whose turn no later request
        # extends: no conversation checkpoint for it (#830).  It still reuses a cached prefix.  Absent = as before.
        if sampling.get("strata_checkpoint") is False:
            keys += " ckpt=0"
        # #2228: the pictures' keys (hex, in prompt order): the engine matches a picture by them, not by its embeddings
        ik = sampling.get("strata_img_keys")
        if isinstance(ik, list) and ik and all(isinstance(k, str) and k and all(c in "0123456789abcdef" for c in k)
                                               for k in ik):
            keys += " img_keys=" + ",".join(ik)
        # "strata_prefix" (resolved by Service.resolve_prefix to {"tokens": N}): the first N prompt tokens are a shared
        # prefix - the engine pins the checkpoint there.  Absent or unresolved = as before.
        prefix = sampling.get("strata_prefix")
        if isinstance(prefix, dict):
            pn = prefix.get("tokens")
            if isinstance(pn, int) and not isinstance(pn, bool) and pn > 0:
                keys += f" pin={pn}"
        return keys + StrataEngine.projection_key(sampling) + bias_api.engine_key(sampling.get("logit_bias"))

    @staticmethod
    def projection_key(sampling: dict) -> str:
        """`cvec=0|1`: the experimental-speed-projection control vector for this request, when the engine was
        started with one (--control-vector-scaled; an engine without one ignores the key).  Absent = on."""
        on = sampling.get("experimental_speed_projection")
        return f" cvec={int(on)}" if isinstance(on, bool) else ""

    def _send(self, text: str):
        btrace("send>", text[:60])
        try:
            with self.wlock:
                self.proc.stdin.write(text + "\n")
                self.proc.stdin.flush()
        except (OSError, AttributeError):                # the pipe is gone (or a restart's close() took the process):
            raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})") from None

    def _control(self, cancel, on_token, stop_when=None, on_quiet=None):
        """Reads the control lines of the request on them (GEN / BGEN), yielding None heartbeats.  Calls on_token(id)
        for each `T`; returns ("done", None) at DONE, or ("badm", continues) at BADM (after DONE).  `stop_when()`
        true sends STOP once (the request is then read to its DONE).  `on_quiet()` runs whenever the engine has been
        quiet for half a second: between two PP lines of a read whose chunks take longer than that."""
        stopped = False
        beat = time.monotonic()
        while True:
            try:
                # A client can leave before the first PP/token.  Poll its Event as often as _take_control does;
                # the ten-second HTTP heartbeat is independent of how promptly STOP reaches the engine.
                line = self.lines.get(timeout=0.5)
            except queue.Empty:
                if cancel.is_set() and not stopped:
                    self._send("STOP")
                    stopped = True
                if on_quiet is not None:
                    on_quiet()
                if time.monotonic() - beat >= 10.0:
                    beat = time.monotonic()
                    yield None
                continue
            beat = time.monotonic()
            if line is None:
                raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})")
            if not line.startswith(("PP ", "INFO")):
                btrace("ctl<", self._ctl_mode, line.strip()[:60])
            if line.startswith("T "):
                on_token(int(line[2:]))
                if not stopped and (cancel.is_set() or (stop_when is not None and stop_when())):
                    self._send("STOP")
                    stopped = True
                yield False                              # a token is pending (not a heartbeat)
            elif line.startswith("PP "):
                f = line.split()
                if len(f) >= 3 and f[1].isdigit() and f[2].isdigit():
                    self.progress = (int(f[1]), int(f[2]))
                    self.progress_ms = float(f[3]) if len(f) >= 4 else 0.0
                    self.prefill_tok_s_mean = float(f[4]) if len(f) >= 5 else None
                if not stopped and cancel.is_set():
                    # #879: a Stop during the prompt read went out only after the first token (or after 10 s of
                    # silence, which a stream of PP lines never allows): the engine read the whole prompt first
                    self._send("STOP")
                    stopped = True
                yield None
            elif line.startswith("DONE"):
                self._parse_done(line)
                self._last_done = line
            elif line.startswith("BADM "):
                f = line.split()
                self._ctl_result = ("badm", len(f) >= 3 and f[2] == "1")
                return
            elif line.startswith("YIELDED "):            # the read gave way (BYIELD): <slot> <tokens read>
                f = line.split()
                if len(f) >= 3 and f[1].lstrip("-").isdigit() and f[2].isdigit():
                    self._yielded = (int(f[1]), int(f[2]))
            elif line.startswith("ERR"):
                self._ctl_erred = True                   # #1059: the engine refused it and is idle: no DONE follows
                self._raise_if_fatal_gpu(line)
                raise ValueError(line[4:].strip())
            if line.startswith("DONE") and self._ctl_mode == "solo":
                self._ctl_result = ("done", None)
                return

    def _done_finish(self) -> str | None:
        """The finish field of the DONE line the control lines read last (None: none since it was cleared)."""
        f = (getattr(self, "_last_done", None) or "").split()
        return f[5] if len(f) > 5 else None

    def _drain_control(self, until: str, timeout: float = 300.0, born: int | None = None):
        """After a consumer left early: read the control lines up to the next `until` line (DONE or BADM) so the next
        request does not read this one's leftovers.  Returns that line (None: the engine ended or never answered).
        `born`: the engine process (self.gen) the request started on; once that one is gone there is nothing to
        drain - its end line was read already (by the request's own EngineDied), and waiting for another one held
        a request that had failed for the whole 300 s (#1012), or read the lines of the engine that replaced it."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if born is not None and (self.gen != born or not self.alive()):
                return None
            try:
                line = self.lines.get(timeout=max(0.1, min(1.0, end - time.monotonic())))
            except queue.Empty:
                continue
            if line is None:
                return None
            if line.startswith("DONE"):
                self._parse_done(line)
            if line.startswith(until) or line.startswith("ERR"):
                return line
        return None

    def _raise_if_fatal_gpu(self, line: str) -> None:
        """#4350: the engine's ERR line "fatal GPU error: ..." means it is ending (its GPU context is gone).  The request in flight fails
        as an engine death (a 503 the client can send again), not as a bad request (400), and the engine counts as ended, so the next
        request starts it again at once instead of finding a closed pipe."""
        text = line[4:].strip()
        if not text.startswith("fatal GPU error"):
            return
        self.last_err = text
        self.ended = True
        raise EngineDied("the GPU reported a fatal error and the engine ended: " + text[len("fatal GPU error:"):].strip()[:200])

    def _apply_bdone(self, f: list[str]) -> None:
        """BDONE counts the admission token too, but its clock starts after the admission's DONE."""
        if len(f) >= 5 and isinstance(self.last, dict):
            admission_ms = self.last.get("decode_ms")
            self.last = {**self.last, "finish": f[3],
                         "decode_ms": admission_ms + float(f[4]) if admission_ms is not None else None,
                         "generated": int(f[2]) if f[2].isdigit() else None}

    def _bdone_after_eos(self, slot: int, wait_s: float = 2.0):
        """#1869: a request in a slot whose consumer left at the stop token has its BDONE right behind it (the engine prints it
        in the same window).  Read it here, so the request's figures are the slot leg's (the background wait would eat it,
        and the request kept the admission's single token).  None when it does not come in `wait_s`: then the background
        wait takes over."""
        if slot >= len(self.slot_q):
            return None
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            try:
                line = self.slot_q[slot].get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                return None
            if line is None:
                return None
            if line.startswith("BDONE "):
                return line
        return None

    def _release_slot_when_done(self, slot: int, stream: list[int] | None = None):
        """A slot whose consumer left (a stop token, a stop string, a disconnect): BSTOP it and free it once the engine
        says BDONE (in the background).  `stream`: the prompt and every token of it so far - with the tokens still to
        come before BDONE, all but the last are what the slot holds then (the next turn of its conversation)."""
        if slot >= len(self.slot_q):                    # the engine restarted with fewer slots: this one is gone
            return
        try:
            self._send(f"BSTOP {slot}")
        except EngineDied:
            pass
        q, busy, held = self.slot_q[slot], self.slot_busy, self.slot_held   # this process's: restart() replaces them
        releasing = self.slot_releasing
        releasing.add(slot)

        def wait():
            end = time.monotonic() + 600.0
            tail = list(stream or [])
            while time.monotonic() < end:
                try:
                    line = q.get(timeout=5.0)
                except queue.Empty:
                    continue
                if line is None:
                    tail = []
                    break
                if line.startswith("BT "):
                    try:
                        tail.append(int(line.split()[2]))
                    except (IndexError, ValueError):
                        tail = []
                if line.startswith("BDONE "):
                    if line.split()[3:4] == ["nonfinite"]:   # #879: the engine dropped the slot's state
                        tail = []
                    break
            held[slot] = tail[:-1] if stream and tail else []
            with self.slot_cv:
                busy[slot] = False
                releasing.discard(slot)
                self.slot_cv.notify_all()
        threading.Thread(target=wait, daemon=True).start()

    BGEN_REFUSALS_MAX = 6    # #1994: how often one request tries another slot after the engine refused a BGEN
    SLOT_PARK_S = 2.0        # ... and how long a refused slot stays out of the picks

    def _park_slot(self, slot: int) -> None:
        """#1994: the engine refused a BGEN for `slot`.  Keep it busy here for SLOT_PARK_S (no request owns it), then
        give it back: the engine's view has caught up, or the next refusal parks it again."""
        with self.slot_cv:
            self.slot_claims.discard(slot)
            self.slot_busy[slot] = True
        busy = self.slot_busy

        def free():
            with self.slot_cv:
                if slot not in self.slot_claims and slot not in self.slot_releasing:
                    busy[slot] = False
                self.slot_cv.notify_all()
        t = threading.Timer(self.SLOT_PARK_S, free)
        t.daemon = True
        t.start()

    ORPHAN_SLOT_S = 3.0   # #1603: a busy flag nobody owns this long is a leak and is given back

    def _reap_orphan_slots(self) -> list[int]:
        """#1603: free the slots whose busy flag has no owner (no request holds or reserves them and no BDONE wait is
        running for them).  The caller holds slot_cv.  A flag that leaked kept every later request waiting for a slot
        that nothing would free - with nothing running, nothing queued and nothing for the frozen-engine check to see.
        A slot is only given back after it has looked ownerless for ORPHAN_SLOT_S, so a flag set a moment before its
        owner registers is never taken."""
        now = time.monotonic()
        freed = []
        for b, busy in enumerate(self.slot_busy):
            if busy and b not in self.slot_claims and b not in self.slot_releasing:
                first = self._orphan_seen.setdefault(b, now)
                if now - first >= self.ORPHAN_SLOT_S:
                    self.slot_busy[b] = False
                    self._orphan_seen.pop(b, None)
                    freed.append(b)
            else:
                self._orphan_seen.pop(b, None)
        if freed:
            print(f"[strata] parallel: slot(s) {', '.join(map(str, freed))} were marked busy with no request using them "
                  "(issue #1603); freed, the waiting request goes on", flush=True)
            self.slot_cv.notify_all()
        return freed

    YIELDS_MAX = 2   # #656: how often one request's prompt read gives way to a shorter waiting one

    def _take_control(self, cancel, plen: int, after_epoch: int | None = None):
        """Waits for the control lines (one prompt read at a time), yielding None heartbeats; False when cancelled.
        `after_epoch`: a request whose read gave way lets the requests waiting then go first."""
        entry = [plen]
        with self.slot_cv:
            self.waiting += 1
            self.wait_lens.append(entry)
        beat = time.monotonic()
        try:
            while True:
                if not self.alive() and not getattr(self, "starting", False):
                    # #1012: the engine is gone and nobody is starting it again: this request was not sent, so it
                    # ends now (a clean 503) instead of waiting for control lines nothing will answer on.  While a
                    # restart is under way it keeps waiting and goes on with the new engine.
                    raise EngineDied("the engine stopped while this request waited; it was not sent")
                with self.slot_cv:
                    turn = after_epoch is None or self.ctl_epoch > after_epoch or self.waiting <= 1
                if turn and self.ctl.acquire(timeout=0.5):
                    if self.alive():
                        break
                    self.ctl.release()                  # it died (or is being restarted) while this one was getting
                    turn = False                        # the lines: not the engine this request was meant for
                if not turn:
                    with self.slot_cv:
                        # #4738 (PR #4738's approach): the turn was read, and the lock given up, before this wait: a
                        # notification sent in between is gone.  Read it again under the lock and only wait when this
                        # request still has to.
                        eligible = after_epoch is None or self.ctl_epoch > after_epoch or self.waiting <= 1
                        if not eligible or not self.alive():
                            self.slot_cv.wait(timeout=0.5)
                if cancel.is_set():
                    return False
                if time.monotonic() - beat >= 10.0:     # a heartbeat every 10 s, as the engine's own wait
                    beat = time.monotonic()
                    yield None
        finally:
            with self.slot_cv:
                previous_waiting = self.waiting
                self.waiting = max(0, self.waiting - 1)
                if entry in self.wait_lens:
                    self.wait_lens.remove(entry)
                if previous_waiting > 1 and self.waiting <= 1:
                    # a waiter that leaves (cancelled, closed) can make another one the next in turn: tell it
                    self.slot_cv.notify_all()
        with self.slot_cv:
            self.ctl_epoch += 1
            self.slot_cv.notify_all()
        return True

    SOLO_AGAIN_MAX = 2      # how often a request left alone in a slot goes back to the solo path
    SOLO_AGAIN_MIN_LEFT = 32  # ... only with at least this many tokens still allowed (max_tokens)

    def _may_go_solo(self, left: int, times: int, embeddings) -> bool:
        """A request decoding in a slot that is alone now (no other slot busy, nobody waiting) goes back to the solo
        path with its MTP drafts: the engine continues it from the slot's sessions (its slot cache; INFO
        slot_cache=1).  STRATA_PARALLEL_SOLO=0 keeps it in the slot."""
        if (embeddings or times >= self.SOLO_AGAIN_MAX or left < self.SOLO_AGAIN_MIN_LEFT or
                not (self.info or {}).get("slot_cache") or os.environ.get("STRATA_PARALLEL_SOLO") == "0"):
            return False
        with self.slot_cv:
            return sum(1 for b in self.slot_busy if b) == 1 and self.waiting == 0

    def _shorter_waiting(self, plen: int) -> bool:
        """#656: someone waits for the control lines with a prompt under half this one's: worth giving way to."""
        with self.slot_cv:
            return any(e[0] * 2 <= plen for e in self.wait_lens)

    def generate_batched(self, ids, max_new, sampling, cancel, embeddings=None):
        """--batch.  Alone (no slot busy, nobody waiting): the solo path (GEN, with drafts: the fastest stream)
        - and when another request arrives meanwhile, this one is STOPped and continues in a batch slot (BGEN with
        its prompt + what it generated: the engine reuses that prefix).  Otherwise: BGEN into a free slot, then the
        slot's own BT lines until BDONE.  Several requests run at once; the control lines (prompt reading, admission)
        are taken one request at a time - and a long prompt read gives way at a chunk boundary to a waiting request
        with a much shorter prompt (#656: `BYIELD <slot>`; the part read waits in a slot and the read goes on after).
        A consumer that stops early leaves the engine in step: the solo request is STOPped and read to its DONE, an
        admission to its BADM, a slot is BSTOPped and freed at its BDONE."""
        self.cur_image = bool(embeddings)                # log_stall: did the request carry an image
        if not self.alive():
            raise EngineDied("the engine is unavailable; this request was not sent")
        self.progress, self.progress_ms, self.reused = None, 0, 0
        born = self.gen                                 # the engine process this request is sent to
        keys = self.sampling_keys(sampling or {})
        out: list[int] = []
        pending: list[int] = []
        prompt, left = list(ids), int(max_new)
        reused0 = None      # the first read's reused tokens: a continued leg's count includes this request's own output
        carry = {}          # #1869: the figures of the legs that ended in a hand-back to the solo path (the final DONE adds to them)
        ok = yield from self._take_control(cancel, len(prompt))
        if not ok:
            return
        holding, born = True, self.gen                  # (the engine it now has the control lines of)
        btrace("ctl acquired")
        slot, gen0, reserved = None, None, None
        yielded_legs = []    # prompt reads that gave way before producing output
        admission_pending, admission_before = False, None   # the admission's DONE is partial until BADM 0 or BDONE
        phase = "none"            # solo -> (admit -> slot) ; "done" once the engine has finished with this request
        stop_sent = False
        yields, solo_again, refused = 0, 0, 0
        admit_wait, admit_since, admit_said = False, 0.0, False   # #1603: waiting for a slot, since when, said
        try:
            while True:   # a request in a slot that is left alone goes back to the solo path
                if not holding:
                    ok = yield from self._take_control(cancel, len(prompt))
                    if not ok:
                        return
                    holding, born = True, self.gen                  # (the engine it now has the control lines of)
                with self.slot_cv:
                    alone = not any(self.slot_busy) and self.waiting == 0
                if alone and left > 1:
                    head = f"GENI {left}{keys} {embeddings}" if embeddings else f"GEN {left}{keys}"
                    self._last_done = None                  # (#879: this request's DONE decides below)
                    self._send(f"{head} {','.join(str(int(t)) for t in prompt)}")
                    phase = "solo"
                    self._ctl_mode, self._ctl_result, self._yielded = "solo", None, None
                    self._ctl_erred = False
                    def others():
                        with self.slot_cv:
                            return self.waiting > 0

                    def give_way():   # at a PP line, and between two far apart (the engine takes it at its next boundary)
                        nonlocal reserved
                        if (reserved is None and not out and not embeddings and yields < self.YIELDS_MAX and
                                self._shorter_waiting(len(prompt))):
                            with self.slot_cv:          # the slot the part read will wait in
                                reserved = self.pick_slot(prompt)
                                if reserved is not None:
                                    self.slot_busy[reserved] = True
                                    self.slot_claims.add(reserved)
                            if reserved is not None:
                                self._send(f"BYIELD {reserved}")
                    for x in self._control(cancel, pending.append, stop_when=others, on_quiet=give_way):
                        while pending:
                            t = pending.pop(0)
                            out.append(t)
                            yield t
                        if x is None:                       # a heartbeat (False: a token, flushed above)
                            give_way()
                            yield None
                    phase = "none"                          # its DONE is read
                    while pending:
                        t = pending.pop(0)
                        out.append(t)
                        yield t
                    if self._done_finish() == "nonfinite":    # #879 (never promoted to a slot)
                        raise EngineNonFinite("the engine's logits became non-finite (#879)")
                    if self._yielded is not None and reserved is not None and self._yielded[0] == reserved:
                        yielded_legs.append(self.last)
                        slot, reserved = reserved, None     # gave way: the read goes on in that slot (below)
                    elif reserved is not None:              # it did not give way: the slot is free again
                        with self.slot_cv:
                            self.slot_busy[reserved] = False
                            self.slot_claims.discard(reserved)
                            self.slot_cv.notify_all()
                        reserved = None
                    if slot is None:
                        finish = (self.last or {}).get("finish") if isinstance(self.last, dict) else None
                        left = int(max_new) - len(out)
                        if cancel.is_set() or left <= 0 or finish in ("stop", "length") or (out and out[-1] in _server().EOS_IDS):
                            return
                        if reused0 is None:
                            reused0 = (self.last or {}).get("reused")
                        carry_leg(carry, self.last)         # #1869: the solo leg's figures; the slot's admission (a copy of
                                                            # the held prefix: prompt_read 1) and BDONE replace them
                        prompt = list(ids) + out            # promoted: it continues in a batch slot from here
                while True:
                    if slot is None:
                        # a free slot (they free themselves at BDONE, which needs no control lines): the one that holds
                        # the start of this prompt (its conversation's last turn), else the one used longest ago.
                        # With none free the control lines are given back while waiting: a slot can be held by a read
                        # that gave way (BYIELD) and needs them to go on, so waiting with them is a deadlock - long,
                        # long, short at 0.25 s steps under parallel: 2 (ENGINE_REVIEW finding 1, reproduced in 0.1.41).
                        while True:
                            with self.slot_cv:
                                slot = self.pick_slot(prompt)
                                if slot is not None:
                                    self.slot_busy[slot] = True
                                    self.slot_claims.add(slot)
                                    if admit_wait:
                                        admit_wait = False
                                        self.admitting = max(0, self.admitting - 1)
                                    break
                                if not admit_wait:          # #1603: counted while it waits for a slot (it holds no
                                    admit_wait, admit_since = True, time.monotonic()   # control lines then)
                                    self.admitting += 1
                            if holding:
                                self.ctl.release()
                                holding = False
                            with self.slot_cv:
                                if self.pick_slot(prompt) is None:
                                    if (_server().ENGINE_STALL_S or 0) > 0 and time.monotonic() - admit_since >= _server().ENGINE_STALL_S:
                                        # the stall check of #1317 only watches a request on the control lines; one
                                        # waiting here is covered by looking for a slot nobody owns, and by saying so
                                        if not admit_said:
                                            admit_said = True
                                            busy = [b for b, v in enumerate(self.slot_busy) if v]
                                            print(f"[strata] parallel: a request has waited {time.monotonic() - admit_since:.0f} s "
                                                  f"for a free slot (busy: {busy}, in use: {sorted(self.slot_claims)}, "
                                                  f"ending: {sorted(self.slot_releasing)}) (issue #1603)", flush=True)
                                    self._reap_orphan_slots()
                                if self.pick_slot(prompt) is None:
                                    self.slot_cv.wait(timeout=1.0)
                            if cancel.is_set():
                                return
                            if not holding:
                                ok = yield from self._take_control(cancel, len(prompt))
                                if not ok:
                                    return
                                holding, born = True, self.gen
                    if self._yielded is not None:           # it gave way: the others waiting then go first
                        self.slot_held[slot] = list(prompt[:self._yielded[1]])
                        self._yielded = None
                        yields += 1
                        self.ctl.release()
                        holding = False
                        with self.slot_cv:
                            epoch = self.ctl_epoch
                        ok = yield from self._take_control(cancel, len(prompt), after_epoch=epoch)
                        if not ok:
                            return
                        holding, born = True, self.gen                  # (the engine it now has the control lines of)
                    while not self.slot_q[slot].empty():
                        self.slot_q[slot].get_nowait()
                    head = f"BGENI {slot} {left}{keys} {embeddings}" if embeddings else f"BGEN {slot} {left}{keys}"
                    live = {"slot": slot, "state": "reading", "prompt_tokens": len(prompt), "generated": 0,
                            "started": time.time(), "first_token": None}
                    self.slot_live[slot] = live
                    self._last_done = None                  # (#879: this admission's DONE decides below)
                    self._send(f"{head} {','.join(str(int(t)) for t in prompt)}")
                    self.slot_held[slot] = []               # the admission overwrites what the slot held
                    admission_pending, admission_before = True, self.last
                    phase = "admit"
                    self._ctl_mode, self._ctl_result, self._yielded = "batch", None, None
                    self._ctl_erred = False
                    asked = False

                    def ask():        # as give_way above, for the slot this admission reads into
                        nonlocal asked
                        if (not asked and not embeddings and yields < self.YIELDS_MAX and
                                self._shorter_waiting(len(prompt))):
                            self._send(f"BYIELD {slot}")
                            asked = True
                    try:
                        for x in self._control(cancel, pending.append, on_quiet=ask):
                            while pending:
                                t = pending.pop(0)
                                out.append(t)
                                yield t
                            if x is None:
                                ask()
                                yield None
                    except ValueError as e:
                        # #1994: the engine says this slot is not free (its view and ours differ for a moment, or a
                        # slot it still holds).  That is not the request's fault and nothing was read: park the slot
                        # for a moment (busy here too), and wait for another one - never a 400 for the conversation.
                        if not (self._ctl_erred and str(e).startswith("BGEN:") and left >= 1 and not cancel.is_set()):
                            raise
                        refused += 1
                        print(f"[strata] parallel: the engine refused slot {slot} ({e}); trying another slot "
                              f"({refused}/{self.BGEN_REFUSALS_MAX}) (issue #1994)", flush=True)
                        if refused > self.BGEN_REFUSALS_MAX:
                            raise GpuBusy("the engine's batch slots are not free right now; try again in a moment",
                                      retry_after=5) from e
                        self.slot_live[slot] = None
                        self.slot_held[slot] = []
                        phase = "none"
                        self._ctl_erred = False
                        self._park_slot(slot)
                        slot = None
                        continue
                    cont = bool(self._ctl_result and self._ctl_result[1])
                    admission_pending = cont
                    phase = "slot" if cont else "none"
                    while pending:
                        t = pending.pop(0)
                        out.append(t)
                        yield t
                    if not cont and self._done_finish() == "nonfinite":   # #879
                        raise EngineNonFinite("the engine's logits became non-finite (#879)")
                    if not cont and self._yielded is not None and self._yielded[0] == slot and not cancel.is_set():
                        yielded_legs.append(self.last)
                        continue                            # gave way: again once the shorter request is in
                    break
                self.ctl.release()
                holding = False
                if not cont:
                    return
                live.update(state="decoding", first_token=time.time(), generated=len(out))
                gen0 = len(out) - 1                         # the admission's own token: the slot feeds it first
                going_solo = False
                while True:
                    try:
                        line = self.slot_q[slot].get(timeout=10.0)
                    except queue.Empty:
                        if cancel.is_set() and not stop_sent:
                            self._send(f"BSTOP {slot}")
                            stop_sent = True
                        yield None
                        continue
                    if line is None:
                        phase = "none"
                        raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})")
                    if line.startswith("BT "):
                        t = int(line.split()[2])
                        out.append(t)
                        live["generated"] = len(out)
                        if cancel.is_set():
                            if not stop_sent:
                                self._send(f"BSTOP {slot}")
                                stop_sent = True
                            continue
                        yield t
                        if not going_solo and not stop_sent and self._may_go_solo(int(max_new) - len(out), solo_again,
                                                                                  embeddings):
                            self._send(f"BSTOP {slot}")         # alone now: on with the drafts (below)
                            going_solo = True
                    elif line.startswith("BDONE "):
                        phase = "none"
                        f = line.split()
                        self._apply_bdone(f)
                        admission_pending = False
                        # what the slot's sessions hold now: the prompt and every token fed (all but the last one)
                        self.slot_held[slot] = list(prompt) + out[gen0:-1] if len(out) > gen0 else []
                        if f[3:4] == ["nonfinite"]:              # #879: the engine dropped the slot's state
                            self.slot_held[slot] = []
                            raise EngineNonFinite("the engine's logits became non-finite (#879)")
                        if (going_solo and f[3:4] == ["cancel"] and not cancel.is_set() and len(out) < int(max_new)
                                and not (out and out[-1] in _server().EOS_IDS)):
                            # the solo path continues it: the engine copies the slot's sessions back (all but the
                            # last token are in them) and decodes with MTP drafts again
                            carry_leg(carry, self.last)         # #1869: the solo path's DONE replaces these figures
                            self.slot_live[slot] = None
                            self.slot_used[slot] = time.time()
                            with self.slot_cv:
                                self.slot_busy[slot] = False
                                self.slot_claims.discard(slot)
                                self.slot_cv.notify_all()
                            slot, gen0 = None, None
                            if reused0 is None:
                                reused0 = (self.last or {}).get("reused")
                            prompt, left = list(ids) + out, int(max_new) - len(out)
                            solo_again += 1
                            btrace("back to the solo path")
                            break
                        return
        finally:
            # a consumer that left early (or an error): keep the engine and this server in step
            btrace("finally phase", phase, "slot", slot, "holding", holding)
            try:
                if phase in ("solo", "admit") and (self.gen != born or not self.alive()):
                    phase = "none"                      # #1012: its engine is gone: nothing to stop or drain
                if phase in ("solo", "admit") and self._ctl_erred:
                    phase = "none"                      # #1059: it ended on the engine's ERR: no DONE to wait 300 s for
                if phase == "solo":
                    self._send("STOP")
                    self._drain_control("DONE", born=born)
                elif phase == "admit":
                    line = self._drain_control("BADM", born=born)
                    if line and line.startswith("BADM ") and line.split()[2:3] == ["1"]:
                        phase = "slot"
            except EngineDied:
                pass
            bdone_in = False
            if phase == "slot" and slot is not None and out and out[-1] in _server().EOS_IDS and self.gen == born:
                bd = self._bdone_after_eos(slot)            # (#1869) the slot's figures, not the admission's
                if bd is not None:
                    self._apply_bdone(bd.split())
                    bdone_in = True
            ended_on_yield = bool(yielded_legs and self.last is yielded_legs[-1])
            if admission_pending and isinstance(self.last, dict) and (self.last is not admission_before or carry):
                # A background drain owns the rest. The admission's one token and time are not this request's totals.
                self.last = {**self.last, "generated": None, "decode_ms": None}
            if reused0 is not None and isinstance(self.last, dict):
                self.last = {**self.last, "reused": reused0}
            if carry and isinstance(self.last, dict):
                self.last = add_carry(carry, self.last)
            earlier_reads = yielded_legs[:-1] if ended_on_yield else yielded_legs
            if earlier_reads and isinstance(self.last, dict):
                self.last = prefill_leg_stats(earlier_reads, self.last, len(prompt))
            if holding:
                self.ctl.release()
            if admit_wait:
                with self.slot_cv:
                    self.admitting = max(0, self.admitting - 1)
            if reserved is not None:
                with self.slot_cv:
                    self.slot_busy[reserved] = False
                    self.slot_claims.discard(reserved)
                    self.slot_cv.notify_all()
            if slot is not None:
                self.slot_live[slot] = None
                self.slot_used[slot] = time.time()
                if phase == "slot" and bdone_in:
                    stream = list(prompt) + out[gen0:] if gen0 is not None and len(out) > gen0 else None
                    self.slot_held[slot] = stream[:-1] if stream else []     # as the BDONE wait leaves it
                    with self.slot_cv:
                        self.slot_busy[slot] = False
                        self.slot_claims.discard(slot)
                        self.slot_cv.notify_all()
                elif phase == "slot":
                    self.slot_held[slot] = []
                    stream = list(prompt) + out[gen0:] if gen0 is not None and len(out) > gen0 else None
                    self._release_slot_when_done(slot, stream)    # freed at its BDONE
                    self.slot_claims.discard(slot)                # (the BDONE wait owns it now)
                else:
                    with self.slot_cv:
                        self.slot_busy[slot] = False
                        self.slot_claims.discard(slot)
                        self.slot_cv.notify_all()

    slot_groups = 1         # --batch-groups (set when the engine starts)
    SLOT_PREFIX_MIN = 512   # a held prefix shorter than this is not worth unbalancing the pipeline's groups

    def pick_slot(self, prompt: list[int]) -> int | None:
        """A free slot for `prompt` (the caller holds slot_cv): the one whose held tokens are the longest start of the
        prompt (the engine then reads only the rest), else an empty one, else the one used longest ago - so the
        conversations other slots hold stay for their next turns.  None: every slot is busy."""
        free = [b for b in self.slot_order if not self.slot_busy[b]]
        if not free:
            return None
        gs = getattr(self, "slot_gs", 0)
        if gs:
            # pipelined groups: the engine keeps no pipelined slot as a conversation cache, so nothing is worth keeping
            # free for a next turn.  A group's window spans its slots up to its last busy one, so first fill a hole
            # below a busy slot of the same group (it costs no extra row), then follow the spreading order
            # (reported on #793: least-recently-used picks left leading holes, [_ B], that cost a whole row each)
            def fills_hole(b):
                g0 = b - b % gs
                return any(self.slot_busy[x] for x in range(b + 1, g0 + gs))
            return min(free, key=lambda b: (not fills_hole(b), self.slot_order.index(b)))
        def held_prefix(b):
            h = self.slot_held[b]
            return len(h) if h and len(h) < len(prompt) and prompt[:len(h)] == h else 0
        best = max(free, key=held_prefix)
        # without --batch-groups a held prefix of any length is taken, as before
        if held_prefix(best) >= (self.SLOT_PREFIX_MIN if self.slot_groups > 1 else 1):
            return best
        # with --batch-groups: the group with the fewest busy slots first, so the requests spread over the
        # pipeline's stages (two requests in one group leave the other stage idle); then empty, then least recent
        busy_in = {}
        for b in range(self.batch):
            if self.slot_busy[b]:
                busy_in[self.slot_group[b]] = busy_in.get(self.slot_group[b], 0) + 1
        return min(free, key=lambda b: (busy_in.get(self.slot_group[b], 0) if self.slot_groups > 1 else 0,
                                        bool(self.slot_held[b]), self.slot_used[b]))

    def slots_view(self) -> list[dict]:
        """/metrics: each batch slot - idle (with the tokens it holds for a next turn), reading or decoding."""
        now, view = time.time(), []
        for b in range(self.batch):
            r = self.slot_live[b]
            if r is None:
                view.append({"slot": b, "state": "idle", "held_tokens": len(self.slot_held[b])})
                continue
            ft = r.get("first_token")
            view.append({"slot": b, "state": r["state"], "prompt_tokens": r["prompt_tokens"],
                         "generated": r["generated"], "elapsed_s": round(now - r["started"], 1),
                         "tok_s": round(r["generated"] / max(1e-6, now - ft), 1) if ft else None})
        return view

    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        """Yields token ids, and None as a heartbeat every 10 s while the engine is quiet (reading a long prompt):
        the HTTP layer turns it into an SSE comment, which keeps clients' watchdogs calm and notices a client that
        has gone.  A consumer that stops early (or `cancel`) makes the engine STOP, so it does not run to max_new."""
        if not self.alive():
            raise EngineDied("the engine is unavailable; this request was not sent")
        bias_api.validate_request(sampling or {}, self, None)
        if getattr(self, "batch", 0):
            yield from self.generate_batched(ids, max_new, sampling, cancel, embeddings)
            return
        self.progress, self.progress_ms, self.reused = None, 0, 0
        self.prefill_tok_s_mean = None
        self.cur_image = bool(embeddings)                # log_stall: did the request carry an image
        # an image request takes the same sampling keys as text (#75: it used to decode greedily whatever was asked)
        head = f"GENI {int(max_new)}{self.sampling_keys(sampling or {})} {embeddings}" if embeddings else \
            f"GEN {int(max_new)}{self.sampling_keys(sampling or {})}"
        try:
            self.proc.stdin.write(f"{head} {','.join(str(int(t)) for t in ids)}\n")
            self.proc.stdin.flush()
        except OSError:                                  # the pipe is gone: the engine died (not the client)
            raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})") from None
        done = False
        # #481: how long the engine may stay silent from here.  Until the first line: the request's first prompt
        # chunk at the slowest prompt reading on top of silence_s; a PP line resets it to its own chunk's time.
        silence = float(self.silence_s or 0)
        allow = silence + min(len(ids), PP_CHUNK_MAX) / PP_FLOOR_TOK_S if silence > 0 else 0.0
        heard, read_to = time.monotonic(), 0
        beat = heard
        stall_s = _server().ENGINE_STALL_S or 0.0
        stall_state: dict = {}
        try:
            while True:
                wait = 10.0
                if allow > 0:
                    wait = min(wait, allow - (time.monotonic() - heard))
                    if wait <= 0:
                        done = True                       # no STOP and no drain: nothing is listening
                        raise self._silent(f"the engine said nothing for {time.monotonic() - heard:.0f} s during "
                                           "the request")
                try:
                    line = self.lines.get(timeout=min(wait, 0.5))
                except queue.Empty:
                    if cancel.is_set():
                        return
                    if stall_s > 0:
                        try:
                            self._stall_check(heard, stall_state, stall_s)
                        except EngineSilent:
                            done = True                   # as above: nothing is listening
                            raise
                    if allow > 0 and time.monotonic() - heard >= allow:
                        continue                          # enforce the expired deadline before another heartbeat
                    if time.monotonic() - beat >= 10.0:
                        beat = time.monotonic()
                        yield None                        # polling cancellation does not add HTTP heartbeats
                    continue
                if line is None:
                    done = True
                    raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})")
                heard = time.monotonic()                  # any line is output: T, PP, RESUME, INFO ...
                beat = heard
                if stall_state:
                    stall_state.clear()
                if line.startswith("T "):
                    allow = silence
                    if cancel.is_set():
                        return
                    yield int(line[2:])
                elif line.startswith("PP "):
                    f = line.split()
                    if len(f) >= 3 and f[1].isdigit() and f[2].isdigit():
                        self.progress = (int(f[1]), int(f[2]))             # prompt progress, one per chunk: also a heartbeat (the
                        self.progress_ms = float(f[3]) if len(f) >= 4 else 0.0
                        self.prefill_tok_s_mean = float(f[4]) if len(f) >= 5 else None
                        rate, chunk = self.prefill_tok_s_mean or 0.0, int(f[1]) - read_to
                        read_to = int(f[1])
                        if silence > 0 and rate > 0 and chunk > 0:   # #481: the next chunk, as long as this one
                            allow = max(silence, PP_SLACK * chunk / rate)
                    if cancel.is_set():                   # lines reset the 10 s wait, so without this a long prompt
                        return                            # would send no keep-alives at all)
                    yield None
                elif line.startswith("RESUME "):          # the reused tokens: the first chunk starts after them
                    try:
                        read_to = self.reused = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("DONE"):
                    self._parse_done(line)
                    done = True
                    if self.last.get("finish") == "nonfinite":   # #879
                        raise EngineNonFinite("the engine's logits became non-finite (#879)")
                    return
                elif line.startswith("ERR"):
                    done = True
                    self._raise_if_fatal_gpu(line)
                    self._swallow_trailing_done(self.lines)   # an engine that ended the request on ERR may still print its DONE
                    raise ValueError(line[4:].strip())
        finally:
            if not done:                                  # the consumer stopped early: stop the engine, drain to DONE
                # the engine can be ended or restarted on another thread meanwhile: Engine.close() closes stdin (a
                # write then raises ValueError) before it clears `proc` (None then) - the STOP has nobody to reach, and
                # the request's own outcome must not be replaced by that error
                proc = self.proc
                if self.can_stop and proc is not None:
                    try:
                        proc.stdin.write("STOP\n")
                        proc.stdin.flush()
                    except (OSError, ValueError):
                        pass
                # #481: never an untimed wait here - it holds the request FIFO, and an engine that lost step never
                # answers.  An engine that honours STOP gets the current allowance in all (a STOP during a prompt
                # chunk is seen after it); an older one runs on to max_new, so each line only has to come in time.
                heard = time.monotonic()
                cap = _server().ENGINE_CANCEL_S or 0.0
                cap_at = heard + cap if cap > 0 else None      # a fixed limit from the STOP, whatever lines come
                while True:
                    left = allow - (time.monotonic() - heard) if allow > 0 else None
                    if cap_at is not None:
                        left = min(left, cap_at - time.monotonic()) if left is not None else cap_at - time.monotonic()
                    try:
                        if left is not None and left <= 0:
                            raise queue.Empty
                        line = self.lines.get(timeout=left)
                    except queue.Empty:
                        took = time.monotonic() - (cap_at - cap if cap_at is not None else heard)
                        raise self._silent("the engine did not finish the request after it was stopped (STOP) "
                                           f"within {took:.0f} s") from None
                    if line is None or line.startswith("ERR"):
                        break
                    if line.startswith("DONE"):
                        self._parse_done(line)
                        break
                    if not self.can_stop:
                        heard = time.monotonic()

    @staticmethod
    def _swallow_trailing_done(lines_q, wait: float = 0.3) -> None:
        """A request that ends on `ERR ...` is over, but an engine that also prints the request's `DONE` after it (upstream's
        DeepSeek engine did, after its NaN stop) would hand that DONE to the NEXT request as its own: 0 tokens at once, and every
        answer after it one request late.  So a short wait for a trailing DONE (or ERR) of the same request, taken off the queue
        and dropped, before the request is reported failed and the FIFO released.  An engine that prints only the ERR costs the wait."""
        end = time.monotonic() + wait
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            try:
                late = lines_q.get(timeout=left)
            except queue.Empty:
                return
            if late is None or late.startswith(("DONE", "ERR")):
                return

    def _activity(self) -> tuple[float, int] | None:
        """#1317: (CPU seconds, I/O bytes) the engine process has used so far, or None when they cannot be read."""
        try:
            import psutil
            pr = psutil.Process(self.proc.pid)
            t = pr.cpu_times()
            io = pr.io_counters()
            return (t.user + t.system, io.read_bytes + io.write_bytes)
        except Exception:  # noqa: BLE001 - psutil missing, the process gone, no permission: no reading
            return None

    def _stall_check(self, heard: float, state: dict, stall_s: float) -> None:
        """#1317: called while the engine is silent.  Takes a baseline soon after the last line, and at stall_s of silence
        compares: no CPU and no I/O in all that time -> the engine is ended (EngineSilent); work going on -> one warning."""
        age = time.monotonic() - heard
        if state.get("base") is None:
            state["base"] = self._activity()
            return
        if age < state.get("next", stall_s) or state["base"] is None:
            return
        now = self._activity()
        try:
            gpu_working = bool(self.gpu_busy()) if self.gpu_busy is not None else False
        except Exception:  # noqa: BLE001 - a telemetry hiccup must not decide anything
            gpu_working = False
        if now is not None and not gpu_working and engine_frozen(state["base"], now):
            raise self._silent(f"the engine said nothing for {age:.0f} s and used no CPU or disk in that time (frozen; "
                               "STRATA_ENGINE_STALL_S sets this, 0 = off)")
        if now is not None:   # working: look again after another window from here, and say so once
            state["base"], state["next"] = now, age + stall_s
            if not state.get("warned"):
                state["warned"] = True
                print(f"[strata] the engine has said nothing for {age:.0f} s but is still working; it is not ended (the "
                      "limit is engine_silence_s). If it is stuck, \"engine_silence_s\" can be set lower.", flush=True)
        else:
            state["next"] = float("inf")   # no reading (psutil missing): nothing to decide on

    def _silent(self, what: str) -> EngineSilent:
        """#481: end an engine that lost step with the server (its main thread waits for a command the server never
        sends), so the next request starts it again: killed now, its GPU and RAM go back with the process."""
        self.silent_note = ("The engine and the server lost step (issue #481; a very slow PC can raise "
                            "\"engine_silence_s\" in the config, 0 = wait forever). If it happens again, please add "
                            "the end of the engine log to github.com/Niko1221/Strata/issues/481.")
        self.ended = True                               # not alive from now: the next request restarts it
        proc = self.proc
        try:
            proc.kill()
            proc.wait(timeout=20)                       # restart() -> close() handles one that is still exiting
        except (OSError, AttributeError, subprocess.TimeoutExpired):
            pass
        return EngineSilent(f"{what}; the server ended the engine")

    def session_file(self, action: str, path: str) -> dict:
        """Disk sessions: `SAVE <path>` / `RESTORE <path>` between requests (the caller holds the service FIFO).
        -> {"tokens", "bytes", "ms"}.  SessionRefused (kind, published) when the engine refused or failed the file and
        is still in step (`SERR <kind> <0|1> <reason>`).  Any line this exchange does not allow - an unknown or
        malformed one, a bare ERR, an answer with negative counts or a non-finite time - means the two sides lost
        step: the engine is ended (EngineDied) and the next request starts it again.  EngineDied also when it ended
        by itself (a restore transfer that failed after the device state changed ends it on purpose: FATAL), and
        EngineSilent (#481) when it printed nothing valid for engine_silence_s - a SESSION progress line (one per
        block of the file moved, at most 16 MiB) counts only when its numbers are.  `SWAIT <phase> <seconds>` announces
        a step that blocks in one call (a flush, the device transfer): until the next line the wait is that step's
        explicit allowance (at most SESSION_WAIT_MAX_S) when it is longer than engine_silence_s - no more, so a step
        that never ends is still ended."""
        if action not in ("save", "restore") or any(c in path for c in "\r\n\0"):
            raise ValueError("invalid session command")
        try:
            self.proc.stdin.write(f"{'SAVE' if action == 'save' else 'RESTORE'} {path}\n")
            self.proc.stdin.flush()
        except OSError:
            raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})") from None
        silence = float(self.silence_s or 0)
        heard = time.monotonic()
        want = "SAVED" if action == "save" else "RESTORED"

        def out_of_step(line: str) -> EngineDied:
            self.ended = True                               # not alive from now: the next request restarts it
            try:
                self.proc.kill()
                self.proc.wait(timeout=20)
            except (OSError, AttributeError, subprocess.TimeoutExpired):
                pass
            return EngineDied(f"the engine answered a session {action} with {line.strip()[:200]!r}; "
                              "the server ended the engine")

        def count(s: str) -> int:
            if not s.isdigit():                             # no sign, no blank, no fraction
                raise ValueError
            return int(s)

        last_done = -1
        allow = 0.0                                         # the announced blocking step's allowance, seconds
        while True:
            limit = max(silence, allow)
            left = limit - (time.monotonic() - heard) if silence > 0 else None
            try:
                if left is not None and left <= 0:
                    raise queue.Empty
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise self._silent(f"the engine said nothing for {limit:.0f} s during a session {action}"
                                   + (f" (in a blocking step allowed {allow:.0f} s)" if allow > silence else "")) from None
            if line is None:
                raise EngineDied(f"the engine stopped unexpectedly (exit code {self.exit_code()})")
            f = line.split()
            head = f[0] if f else ""
            if head == "SESSION":                          # a large file moving: progress, and a heartbeat
                try:
                    if len(f) != 3:
                        raise ValueError
                    done, total = count(f[1]), count(f[2])
                    if done > total or done < last_done:
                        raise ValueError
                except ValueError:
                    raise out_of_step(line) from None
                last_done = done
                heard, allow = time.monotonic(), 0.0
                continue
            if head == "SWAIT":                            # a blocking step starts: its bounded allowance
                try:
                    if len(f) != 3 or not f[1].isalpha() or not f[1].isascii():
                        raise ValueError
                    seconds = count(f[2])
                    if not 0 < seconds <= SESSION_WAIT_MAX_S:
                        raise ValueError
                except ValueError:
                    raise out_of_step(line) from None
                heard, allow = time.monotonic(), float(seconds)
                continue
            if head == "FATAL":
                raise EngineDied(line[6:].strip() or "the engine ended during a session restore")
            if head == "SERR":
                parts = line.rstrip("\r\n").split(" ", 3)
                if len(parts) != 4 or parts[1] not in SessionRefused.STATUS or parts[2] not in ("0", "1"):
                    raise out_of_step(line)
                raise SessionRefused(parts[1], parts[3].strip(), parts[2] == "1")
            if head == want:
                try:
                    if len(f) != 4:
                        raise ValueError
                    tokens, size, ms = count(f[1]), count(f[2]), float(f[3])
                    if not math.isfinite(ms) or ms < 0:
                        raise ValueError
                except ValueError:
                    raise out_of_step(line) from None
                return {"tokens": tokens, "bytes": size, "ms": ms}
            if head == "INFO" or head == "WARN":          # engine log lines may interleave; they are not answers
                heard = time.monotonic()
                continue
            raise out_of_step(line)

    def close(self):
        """End the engine process: QUIT first (the engine frees its memory itself - unpinning tens of GB can take
        a while), then terminate, then kill, each given 20 s.  Raises EngineStuck when it still runs after all three."""
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write("QUIT\n")
                    self.proc.stdin.flush()
                    self.proc.stdin.close()  # Windows' detached stdin reader must see EOF before shutdown
                    self.proc.wait(timeout=20)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.proc.terminate()
                    self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                raise EngineStuck("Strata is still releasing GPU/RAM; retry unloading after it exits") from None
        except OSError:
            pass
        finally:
            if self.proc.poll() is not None:
                if self.pump is not None and self.pump.ident is not None:   # a restart can stop before starting it
                    self.pump.join(timeout=2)
                try:
                    self.proc.stdin.close()             # buffered data may flush again after the engine has exited
                except OSError:
                    pass
                self.proc.stdout.close()
                if self.log not in (None, subprocess.DEVNULL):
                    self.log.close()
                self.proc = None
                self.ended = True
                self.progress, self.last = None, {}
                self.progress_ms, self.reused = 0, 0
                v = self.info.get("version")
                self.info = {"version": v} if v is not None else {}
