"""The context window: budget, shrinking, compacting, capping tool results.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import urllib.request
try:
    from .dl_common import (
    C_MUTED,
    C_RESET,
    _switch,
    cli as _cli,
    dl_profile,
    tuned,
)
except ImportError:
    from dl_common import (
    C_MUTED,
    C_RESET,
    _switch,
    cli as _cli,
    dl_profile,
    tuned,
)


# ---------------------------------------------------------------------------------------------------- context budget
CONTEXT_RESERVE = int(os.environ.get("DL_CONTEXT_RESERVE") or 16000)   # tokens kept free for the model's reply


CHARS_PER_TOKEN = 2.8          # measured 2026-10-14: a 212 kB D.L. session was 65,575 prompt tokens (~2.9), rounded down


ELIDED = ("[{n:,} chars removed by D.L. CLI to fit the context. This is a stand-in, not the content: never copy it "
          "into a tool call; view_file the file for its current text]")


# Any stand-in trimming leaves: ELIDED (old and new wording) and the "[... N chars removed ...]" in a long tool result.
STAND_IN = re.compile(r"\[(?:\.\.\. )?[\d,]+ chars removed by D\.L\. CLI to fit the context[^\]\n]*\]")


DROPPED = ("[D.L. CLI: {n} earlier messages were removed to fit the context window. Files on disk are current; "
           "use view_file to read them again instead of relying on memory of earlier content. The user's own "
           "messages are all still here, and your memory files (AGENTS.md, the active plan's Progress, the wiki's "
           "pages) are in the system prompt's project_memory section: re-read the parts you need now.]")


BIG_ARGS = ("CodeContent", "ReplacementContent", "TargetContent", "content")


_ctx_cache: dict[str, int] = {}


def context_window(url: str, api_key: str) -> int:
    """The model's context in tokens (Strata /health max_context), cached per server; 65536 when unknown."""
    if url not in _ctx_cache:
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/health",
                                         headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
            with urllib.request.urlopen(req, timeout=5) as r:
                n = int(json.loads(r.read().decode("utf-8")).get("max_context") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return 65536                 # not cached: a starting engine reports 0
        _ctx_cache[url] = n
    return _ctx_cache[url]


def sync_model_profile(url: str, api_key: str, emit=None) -> None:
    """At the start of a request: the settings profile of the model the server runs now (/health "model"), so a model
    swap or an edited profile takes effect on the next request.  A changed model also forgets the cached context size.
    A server that does not answer keeps the profile in use."""
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/health",
                                     headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        with urllib.request.urlopen(req, timeout=3) as r:
            model = json.loads(r.read().decode("utf-8")).get("model")
    except Exception:
        return
    if not model:
        return
    before = dl_profile.active()["model"]
    if dl_profile.use_model(model):
        if before != model:
            _ctx_cache.pop(url, None)
        if emit is not None and (before is not None or dl_profile.active()["settings"]):
            emit({"type": "notice", "level": "info", "text": dl_profile.describe()})


_degraded_told: set = set()


def degraded_notice(url: str, api_key: str, emit) -> None:
    """Once per engine start: a notice when the engine started short of memory and reads part of the model from disk
    (/health "degraded", audit 2026-11-15: an image prompt then read for 339 s with nothing on screen)."""
    if emit is None:
        return
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/health",
                                     headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        with urllib.request.urlopen(req, timeout=3) as r:
            d = json.loads(r.read().decode("utf-8")).get("degraded")
    except Exception:
        return
    if not isinstance(d, dict) or d.get("since") in _degraded_told:
        return
    _degraded_told.add(d.get("since"))
    emit({"type": "notice", "level": "warn",
          "text": (f"The engine started short of memory: {d.get('kept_gib', '?')} of {d.get('wanted_gib', '?')} GiB of "
                   "the model are in RAM, the rest is read from disk, so replies (pictures most) are slow. It reloads "
                   "by itself when it is idle and memory is free again, or use /restart.")})


def _msg_chars(m: dict) -> int:
    n = len(m.get("content") or "") if isinstance(m.get("content"), str) else len(json.dumps(m.get("content") or ""))
    n += len(m.get("reasoning_content") or "")
    for tc in m.get("tool_calls") or []:
        n += len(tc.get("function", {}).get("arguments") or "") + 40
    return n + 12


def estimate_prompt_tokens(messages: list[dict], tools: list[dict] | None, measured: tuple[int, int] | None = None) -> int:
    """measured = (messages the last request had, its prompt tokens from Strata): exact for that part, only the
    messages added since are estimated from their length."""
    if measured and measured[0] <= len(messages):
        return measured[1] + int(sum(_msg_chars(m) for m in messages[measured[0]:]) / CHARS_PER_TOKEN)
    chars = sum(_msg_chars(m) for m in messages) + (len(json.dumps(tools)) if tools else 0)
    return int(chars / CHARS_PER_TOKEN)


def _shrink(m: dict, arg_max: int, result_max: int, stats: dict) -> None:
    """Drop one message's reasoning, old file contents in its tool calls, and the middle of a long tool result."""
    if m.get("reasoning_content"):
        stats["reasoning"] += 1
        del m["reasoning_content"]
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = None
        if not isinstance(args, dict):
            if len(fn.get("arguments") or "") > arg_max:
                fn["arguments"] = json.dumps({"note": ELIDED.format(n=len(fn["arguments"]))})
                stats["file_contents"] += 1
            continue
        changed = False
        for k in BIG_ARGS:
            v = args.get(k)
            if isinstance(v, str) and len(v) > arg_max and "removed by D.L. CLI" not in v[:80]:
                args[k] = ELIDED.format(n=len(v))
                changed = True
        if changed:
            fn["arguments"] = json.dumps(args, ensure_ascii=False)
            stats["file_contents"] += 1
    if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > result_max:
        c = m["content"]
        head, tail = int(result_max * 0.7), int(result_max * 0.2)
        m["content"] = f"{c[:head]}\n[... {len(c) - head - tail:,} chars removed by D.L. CLI to fit the context ...]\n{c[-tail:]}"
        stats["tool_results"] += 1


def _units(messages: list[dict], start: int, stop: int) -> list[tuple[int, int]]:
    """[start, stop) cut into removable units: an assistant message with the tool results that answer it, or one
    message.  Removing whole units keeps every tool call paired with its result."""
    out, i = [], start
    while i < stop:
        j = i + 1
        if messages[i].get("role") == "assistant" and messages[i].get("tool_calls"):
            while j < len(messages) and messages[j].get("role") == "tool":
                j += 1
            if j > stop:            # its results run on past stop (the last round, 2+ parallel calls): not removable,
                break               # or the call went and its results stayed, answering nothing
        out.append((i, j))
        i = j
    return out


def is_cli_note(m: dict) -> bool:
    """A user-role message D.L. CLI wrote itself (trim note, text-tool-call note, turn cap, done check), not the
    user's words.  Every such note starts with "[D.L. CLI"; the user's own messages start with with_now's "[Now:"."""
    if m.get("role") != "user":
        return False
    c = m.get("content")
    if isinstance(c, str):
        return c.startswith("[D.L. CLI")
    if isinstance(c, list):
        text = next((p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"), "")
        return text.startswith("[D.L. CLI")
    return False


PROTECT_SHARE = 0.25            # at most this part of the trim target goes to keeping older user messages


def protected_user_messages(messages: list[dict], target: int) -> set[int]:
    """Indexes of the user's own messages that trimming keeps: always the first and the latest, then the others
    newest first while they fit in PROTECT_SHARE of the target (a pasted @file can be huge).  D.L. CLI's notes never
    count, so a note can no longer push the user's task out, as it did in the CONTRA run of 2026-10-19."""
    real = [i for i, m in enumerate(messages) if m.get("role") == "user" and not is_cli_note(m)]
    if not real:
        return set()
    keep = {real[0], real[-1]}
    budget = target * PROTECT_SHARE - sum(_msg_chars(messages[i]) for i in keep) / CHARS_PER_TOKEN
    for i in reversed(real[1:-1]):
        cost = _msg_chars(messages[i]) / CHARS_PER_TOKEN
        if cost > budget:
            break
        keep.add(i)
        budget -= cost
    return keep


def current_check_note(messages: list[dict]) -> set[int]:
    """The newest finish-check note (review findings, browser errors, evidence check) while it is still the agent's
    current job - after the user's last own message - so a trim cannot drop it half-way through: on 2026-10-21 a
    CONTRA trim came 6 minutes after a 6-finding review.  The done check's note is left out: the open plan steps
    are in the system prompt anyway."""
    prefixes = tuple(n.split("{", 1)[0][:40] for n in (REVIEW_NOTE, BROWSER_NOTE, BROWSER_LIVE_NOTE, EVIDENCE_NOTE))
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user" and not is_cli_note(m)), default=-1)
    for i in range(len(messages) - 1, last_user, -1):
        if messages[i].get("role") == "user" and str(messages[i].get("content") or "").startswith(prefixes):
            return {i}
    return set()


def compact_history(messages: list[dict], tools: list[dict] | None, limit: int, target: int,
                    measured: tuple[int, int] | None = None, force: bool = False) -> dict | None:
    """Shrink the conversation in place when its prompt would exceed `limit` tokens (or always with force), in
    stages, until it is under `target`: (1) messages older than the last 6 lose their reasoning, whole-file
    contents in tool calls and the middle of long tool results; (2) the same down to the last 2 messages with
    tighter sizes; (3) the oldest messages are removed in whole units, keeping the system prompt, the first and
    the user's own messages (protected_user_messages) and a note.  Returns what it did, or None when nothing was
    needed."""
    before = estimate_prompt_tokens(messages, tools, measured)
    if before <= limit and not force:
        return None
    stats = {"before": before, "reasoning": 0, "file_contents": 0, "tool_results": 0, "removed": 0}
    est = lambda: estimate_prompt_tokens(messages, tools)          # noqa: E731 - after a change, measure afresh
    for keep, arg_max, result_max in ((6, 800, 3000), (2, 300, 1200)):
        for m in messages[1:max(1, len(messages) - keep)]:
            _shrink(m, arg_max, result_max, stats)
        if est() <= target:
            break
    if est() > target:
        protected = protected_user_messages(messages, target) | current_check_note(messages)
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        first = min(protected) if protected else (users[0] if users else 0)
        start = first + 1
        if start < len(messages) and str(messages[start].get("content", "")).startswith("[D.L. CLI:"):
            start += 1                                              # keep one note, counting on from it
        stop = len(messages) - 2
        removable = [u for u in _units(messages, start, stop) if not any(u[0] <= i < u[1] for i in protected)]
        cut = []
        for u in removable:
            cut.append(u)
            gone = sum(_msg_chars(m) for a, b in cut for m in messages[a:b])
            if est() - int(gone / CHARS_PER_TOKEN) <= target:
                break
        if cut:
            gone_idx = {i for a, b in cut for i in range(a, b)}
            stats["removed"] = len(gone_idx)
            kept = [m for i, m in enumerate(messages) if i not in gone_idx]
            if start > first + 1:
                existing_content = str(messages[first + 1].get("content", ""))
                h_match = _HANDOFF_RE.match(existing_content)
                if h_match:
                    h_part = int(h_match.group(1))
                    h_removed = int(h_match.group(2))
                    h_diary = h_match.group(3)
                    tok_m = re.search(r"\(tokens: (\d+)\)", existing_content)
                    b_tok = int(tok_m.group(1)) if tok_m else 0
                    diary_m = re.search(r"archived to `([^`]+)`", existing_content)
                    d_rel = diary_m.group(1) if diary_m else "wiki/handoffs/latest.md"
                    arch_m = re.search(r"full stretch log: `([^`]+)`", existing_content)
                    a_rel = arch_m.group(1) if arch_m else ""
                    h_seq = max((m.get("dl_handoff_seq") or 0 for m in messages if isinstance(m, dict)), default=0)
                    note_msg = {"role": "user", "dl_handoff_seq": h_seq, "content": HANDOFF_NOTE.format(
                        part=h_part, removed=h_removed + len(gone_idx), diary_rel=d_rel,
                        archive_rel=a_rel, diary=h_diary, base_tokens=b_tok
                    )}
                else:
                    note = re.search(r"(\d+) earlier messages", existing_content)
                    prior = int(note.group(1)) if note else 0
                    note_msg = {"role": "user", "content": DROPPED.format(n=prior + len(gone_idx))}
                kept[first + 1] = note_msg
            else:
                note_msg = {"role": "user", "content": DROPPED.format(n=len(gone_idx))}
                kept.insert(first + 1, note_msg)
            messages[:] = kept
    if est() > target:                      # (4) last resort: the newest tool results (2026-10-20 22:12: one 106k
        for result_max in (4000, 1200):     # result was the last message, so (1)-(3) could not reach it)
            for m in messages[-2:]:
                if m.get("role") == "tool":
                    _shrink(m, 10 ** 9, result_max, stats)
            if est() <= target:
                break
    stats["after"] = est()
    return stats


TOOL_RESULT_MAX = int(os.environ.get("DL_TOOL_RESULT_MAX") or 30000)    # chars of one tool result the model gets


def cap_tool_result(text: str, limit: int | None = None, read: bool = False) -> str:
    """The start and the end of a result longer than limit, with a stand-in that says how to get the rest."""
    limit = limit or tuned("DL_TOOL_RESULT_MAX", TOOL_RESULT_MAX)
    if len(text) <= limit:
        return text
    if read:                                # a file read or command output: the start is what was asked for
        return (f"{text[:limit]}\n[cut at {limit:,} of {len(text):,} characters: read a narrower range "
                f"(StartLine/EndLine, sed -n) or grep for what you need]")
    head, tail = int(limit * 0.7), int(limit * 0.3)
    return (f"{text[:head]}\n[... {len(text) - head - tail:,} chars removed by D.L. CLI to fit the context: the "
            f"result had {len(text):,}. Ask for less - redirect long output to a file and read it in parts "
            f"(sed -n, grep, tail), or read a smaller range ...]\n{text[-tail:]}")


def fit_context(messages: list[dict], tools: list[dict] | None, url: str, api_key: str, emit=None,
                measured: tuple[int, int] | None = None, over: int | None = None,
                workspace: Path | None = None, plan_file: Path | str | None = None,
                cancel=None, in_session: bool | None = None, on_handoff=None) -> dict | None:
    """Keep the next request inside the context with room for the reply; `over` = the prompt size Strata
    reported when it refused one (forces a compaction).  When `workspace` is given and DL_HANDOFF is on (default),
    writes a condensed wiki handoff diary and reloads a clean session instead of mechanical pruning.  Returns stats,
    or None when nothing was needed."""
    ctx = _cli().context_window(url, api_key)
    limit = max(4096, ctx - tuned("DL_CONTEXT_RESERVE", _cli().CONTEXT_RESERVE))
    target = int(limit * 0.6)
    if over:                                # the estimate was low: aim lower by the same ratio
        measured = None
        est = estimate_prompt_tokens(messages, tools)
        if over > est > 0:
            target = int(target * est / over)
    if workspace is not None and _switch("DL_HANDOFF"):
        # Between 50k (limit) and 61k (ctx - HANDOFF_MIN_REPLY_ROOM), the 16k reserve (50k..64k) has plenty of room
        # for the ~1.5k warm in-session diary turn; above 61k (or after an overflow refusal) fall back to digest mode.
        before_est = over or estimate_prompt_tokens(messages, tools, measured)
        use_in_session = (in_session if in_session is not None
                          else (not over and before_est <= max(limit, ctx - tuned("DL_HANDOFF_MIN_REPLY_ROOM", HANDOFF_MIN_REPLY_ROOM))))
        stats = _cli().handoff_session(messages, tools, limit, target, workspace, url=url, api_key=api_key,
                                plan_file=plan_file, measured=measured, force=bool(over), cancel=cancel,
                                in_session=use_in_session, on_handoff=on_handoff)
    else:
        stats = compact_history(messages, tools, limit, target, measured=measured, force=bool(over))
    if not stats:
        return None
    if stats.get("handoff"):
        mode_tag = "warm in-session" if stats.get("in_session") else "digest fallback"
        note = (f"🗂️ Context {stats['before'] / 1000:.0f}k → {stats['after'] / 1000:.0f}k tokens "
                f"(limit {limit / 1000:.0f}k of {ctx / 1000:.0f}k): wiki handoff #{stats['handoff']} ({mode_tag}) "
                f"saved to {stats['diary']} ({stats['removed']} earlier messages archived into clean session)")
    else:
        did = [f"{stats[k]} {label}" for k, label in (("reasoning", "old reasoning blocks"),
                                                      ("file_contents", "old file contents"),
                                                      ("tool_results", "long tool results"),
                                                      ("removed", "oldest messages removed")) if stats[k]]
        note = (f"Context {stats['before'] / 1000:.0f}k → {stats['after'] / 1000:.0f}k tokens "
                f"(limit {limit / 1000:.0f}k of {ctx / 1000:.0f}k): {', '.join(did) or 'nothing left to shorten'}")
    if emit:
        emit({"type": "notice", "level": "info", "text": note})
    else:
        print(f"{C_MUTED}{note}{C_RESET}")
    return stats


HANDOFF_MIN_REPLY_ROOM = int(os.environ.get("DL_HANDOFF_MIN_REPLY_ROOM") or 4500)  # min KV room in 50k..64k for in-session diary turn


HANDOFF_NOTE = (
    "[D.L. CLI: Session handoff #{part} — {removed} earlier messages were archived to `{diary_rel}` "
    "(tokens: {base_tokens}) (full stretch log: `{archive_rel}`) and replaced with a clean session to keep reasoning sharp. "
    "Read the Active Handoff Brief below:\n\n"
    "{diary}\n\n"
    "Continue from **Next Immediate Action**. Context guard rules:\n"
    "1. Do NOT re-read files listed under **Completed & Verified** unless a test fails.\n"
    "2. Do NOT read entire files or dump full logs; use `view_file` with narrow `StartLine`/`EndLine` ranges around "
    "the `file:Lstart-Lend` anchors above, or `grep_search`.\n"
    "3. Only open `{archive_rel}` if you specifically need an older detail not in the brief above.\n"
    "4. **Key Facts (verified)** are already checked: use them as they are; never fetch or derive them again.]"
)


_HANDOFF_RE = re.compile(
    r"^\[D\.L\. CLI: Session handoff #(\d+) — (\d+) earlier messages were archived to `[^`]+`[^\n]*\n\n"
    r"(.*?)\n\nContinue from \*\*(?:Next Immediate Action|Next Immediate Step)\*\*",
    re.DOTALL,
)


DONE_NOTE = ("[D.L. CLI] {plan} still has {n} open step(s) in its Progress checklist: {items}. Continue with the next "
             "open step and tick each line (\"- [x]\") as soon as its own check passes - one line at a time, not when the whole section is done. If you cannot go on, add a \"Blocked: <reason>\" "
             "line to the Progress section and say why.")


EVIDENCE_NOTE = ("[D.L. CLI] Your answer says \"{word}\", but no test or check command ran after your last file edit. "
                 "Run one now and report its real output, or say plainly what is not verified.")


BROWSER_NOTE = ("[D.L. CLI] Browser check: D.L. CLI loaded {page} in headless Chromium after your edits and it "
                "reported {n} error(s):\n{errors}\nFix them and run your checks again, then finish.")


BROWSER_LIVE_NOTE = ("[D.L. CLI] Browser check during the run: D.L. CLI loaded {page} in headless Chromium and it "
                     "reported {n} error(s):\n{errors}\nThese happen in a real browser; a check that runs without "
                     "one may not see them. Fix them as part of your current work.")


REVIEW_NOTE = ("[D.L. CLI] A reviewer with a fresh context read your changes and your final answer and reported:\n"
               "{findings}\nFix the real problems and re-run the checks; for any finding you reject, say why. Then "
               "finish.")
