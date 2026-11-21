"""The handoff diary written when a session is cleared or compacted.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import subprocess
import sys
import time
try:
    from .dl_common import (
    _switch,
    cli as _cli,
    dl_memory,
    dl_profile,
    memory_store,
)
except ImportError:
    from dl_common import (
    _switch,
    cli as _cli,
    dl_memory,
    dl_profile,
    memory_store,
)
try:
    from .dl_context import (
    HANDOFF_NOTE,
    _HANDOFF_RE,
    _shrink,
    _units,
    compact_history,
    current_check_note,
    estimate_prompt_tokens,
    protected_user_messages,
)
except ImportError:
    from dl_context import (
    HANDOFF_NOTE,
    _HANDOFF_RE,
    _shrink,
    _units,
    compact_history,
    current_check_note,
    estimate_prompt_tokens,
    protected_user_messages,
)
try:
    from .dl_finish import _latest_task, request_actions
except ImportError:
    from dl_finish import _latest_task, request_actions
try:
    from .dl_prompt import plan_progress
except ImportError:
    from dl_prompt import plan_progress
try:
    from .dl_tools_schema import find_wiki_script
except ImportError:
    from dl_tools_schema import find_wiki_script


HANDOFF_MIN_GROWTH = int(os.environ.get("DL_HANDOFF_MIN_GROWTH") or 8000)  # min prompt tokens added between handoffs to prevent thrashing


HANDOFF_MAX_CHARS = 3200


HANDOFF_SYSTEM = (
    "You write a condensed session handoff brief for a coding agent that is resetting to a fresh context window. "
    "Write at most 450 words using ONLY these five Markdown sections:\n"
    "## Goal & Live State\n"
    "## Completed & Verified\n"
    "## Key Facts (verified)\n"
    "## Dead Ends / Ruled Out\n"
    "## Next Immediate Action\n"
    "Include exact file:Lstart-Lend anchors, function names, commands, and ports. Under 'Completed & Verified', list "
    "what is already done on disk so the fresh session does not re-read those files. Under 'Dead Ends / Ruled Out', "
    "list any approaches, edits, or commands that failed or were ruled out so the fresh session never repeats them. "
    "Under 'Key Facts (verified)', copy exact data the work depends on that was already looked up or checked (table "
    "values, constants, API names, URLs already read), so the fresh session never fetches or derives it again. "
    "Do not call any tools and do not include code blocks or prose outside these five sections."
)


IN_SESSION_HANDOFF_PROMPT = (
    "[D.L. CLI: Context is approaching the handoff threshold. Before D.L. CLI reloads a clean session, write the "
    "condensed Active Handoff Brief now (at most 450 words, no tool calls, no code blocks) using ONLY these five "
    "Markdown sections:\n"
    "## Goal & Live State\n"
    "(Exact task, workspace paths, active file:Lstart-Lend anchors, running services/ports)\n"
    "## Completed & Verified\n"
    "(One-line bullets of steps already verified on disk; include exact PLAN.md step text for any newly completed steps)\n"
    "## Key Facts (verified)\n"
    "(Exact data already looked up or checked that the work depends on: table values, constants, names, URLs already "
    "read. Copy the values themselves, not a pointer to them)\n"
    "## Dead Ends / Ruled Out\n"
    "(Failed commands, errors, or ruled-out hypotheses from this session and any prior handoff — never repeat these)\n"
    "## Next Immediate Action\n"
    "(The exact next tool call or edit to run first in the clean session, with target file and StartLine/EndLine)]"
)


def _prior_handoff(messages: list[dict]) -> tuple[int, int, str, int]:
    """(part, removed_count, diary_text, base_tokens) from an earlier handoff note in `messages`, or (0, 0, '', 0)."""
    drop_count = 0
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            match = _HANDOFF_RE.match(m["content"])
            if match:
                tok_m = re.search(r"\(tokens: (\d+)\)", m["content"])
                base_tok = int(tok_m.group(1)) if tok_m else 0
                return int(match.group(1)), int(match.group(2)), match.group(3).strip(), base_tok
            m_drop = re.search(r"\[D\.L\. CLI: (\d+) earlier messages", m["content"])
            if m_drop and not drop_count:
                drop_count = int(m_drop.group(1))
    return 0, drop_count, "", 0


def _extract_dead_ends(diary: str) -> list[str]:
    for heading in ("## Dead Ends / Ruled Out", "## Dead Ends & Do Not Repeat"):
        if heading in diary:
            sec = diary.split(heading, 1)[1].split("## ", 1)[0].strip()
            return [l.strip() for l in sec.splitlines() if l.strip().startswith("-") and "None recorded" not in l]
    return []


def _fallback_handoff_diary(messages: list[dict], ws: Path, plan_file: Path | str | None = None,
                            prior_diary: str = "") -> str:
    """Deterministic 4-section Active Handoff Brief used when the LLM summary call is skipped or fails."""
    task = " ".join(_latest_task(messages).split())[:550] or "(see user messages above)"
    plan_path = Path(plan_file) if plan_file else (ws / "PLAN.md" if (ws / "PLAN.md").is_file() else None)
    done_steps, open_steps = [], []
    if plan_path and plan_path.is_file():
        _, open_steps, done_steps, _ = plan_progress(plan_path)
    results = {m.get("tool_call_id"): str(m.get("content") or "") for m in messages if m.get("role") == "tool"}
    ok_calls, failed_calls, anchors = [], [], []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name", "?")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            target = (args.get("TargetFile") or args.get("AbsolutePath") or args.get("CommandLine")
                      or args.get("Query") or args.get("path") or "")
            target_str = " ".join(str(target).split())[:90]
            if args.get("StartLine") or args.get("EndLine"):
                loc = f"{target_str}:L{args.get('StartLine', 1)}-L{args.get('EndLine', '?')}"
                if loc not in anchors:
                    anchors.append(loc)
            elif name in ("write_to_file", "replace_file_content", "view_file") and target_str:
                if target_str not in anchors:
                    anchors.append(target_str)
            raw_res = results.get(tc.get("id"), "")
            res = " ".join(raw_res.split())
            entry = f"{name}({target_str})" if target_str else name
            is_failure = (
                bool(re.search(r"\bexit(?:ed)? with code [1-9]\b", res, re.I))
                or bool(re.search(r"(?:^|\n)\s*Traceback \(most recent call last\):", raw_res))
                or bool(re.search(r"(?:^|\n)\s*(?:[A-Za-z0-9_]*Error|Exception):\s+", raw_res))
                or bool(re.search(r"^Command exited with code [1-9]", res))
            )
            if is_failure:
                failed_calls.append(f"- `{entry}` -> {res[:140]}")
            else:
                ok_calls.append(f"- `{entry}` -> {res[:100]}" if res else f"- `{entry}`")
    last_asst = ""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            last_asst = " ".join(str(m.get("content") or m.get("reasoning_content") or "").split())[-280:]
            if last_asst:
                break
    completed = ([f"- [x] {s}" for s in done_steps[:6]] + ok_calls[-7:]) or ["- Initial exploration in progress."]
    prev_de = _extract_dead_ends(prior_diary)
    dead_ends = list(dict.fromkeys(prev_de[:4] + failed_calls[-5:])) or ["- None recorded in this stretch."]
    if open_steps:
        next_step = f"- Complete next open plan step in `{plan_path.name}`: {open_steps[0]}"
    elif last_asst:
        next_step = f"- Continue from last assistant step: {last_asst}"
    else:
        next_step = "- Continue executing the user's latest request from the current workspace state."
    anchor_line = f"\n- Active file anchors: {', '.join(f'`{a}`' for a in anchors[-5:])}" if anchors else ""
    diary = (
        f"## Goal & Live State\n"
        f"- Workspace: `{ws}`\n"
        f"- Task: {task}{anchor_line}\n\n"
        f"## Completed & Verified\n" + "\n".join(completed[-8:]) + "\n\n"
        f"## Dead Ends / Ruled Out\n" + "\n".join(dead_ends[-6:]) + "\n\n"
        f"## Next Immediate Action\n"
        f"{next_step}"
    )
    return diary[:HANDOFF_MAX_CHARS]


def _normalize_handoff_diary(text: str, prior_diary: str, fallback: str) -> str:
    """Ensure the model's diary is non-empty, strips any accidental tool/code blocks, and retains prior dead ends."""
    text = _cli().TEXT_TOOL_CALL.sub("", (text or "")).strip()
    if not text or "## " not in text:
        return fallback
    prev_de = _extract_dead_ends(prior_diary)
    cur_de = _extract_dead_ends(text)
    missing_de = [d for d in prev_de[:3] if d not in cur_de and d not in text]
    if missing_de and "## Dead Ends / Ruled Out" in text:
        head, tail = text.split("## Dead Ends / Ruled Out", 1)
        text = head + "## Dead Ends / Ruled Out\n" + "\n".join(missing_de) + "\n" + tail.lstrip("\n")
    return text[:HANDOFF_MAX_CHARS]


def in_session_handoff_diary(messages: list[dict], tools: list[dict] | None, ws: Path, url: str, api_key: str,
                             plan_file: Path | str | None = None, cancel=None) -> str:
    """Ask the live session itself (while its KV cache is warm in memory) to author the 4-section Active Handoff Brief.
    Passes `tools` unchanged so the cached prompt prefix hits 100%."""
    _, _, prior_diary, *_ = _prior_handoff(messages)
    fallback = _fallback_handoff_diary(messages, ws, plan_file=plan_file, prior_diary=prior_diary)
    if not url or not _switch("DL_HANDOFF_LLM"):
        return fallback
    messages.append({"role": "user", "content": IN_SESSION_HANDOFF_PROMPT})
    try:
        res = _cli().stream_chat_turn(
            messages, url, api_key, tools=tools or [], emit=lambda e: None, cancel=cancel,
            effort=dl_profile.env("DL_HANDOFF_EFFORT") or "low",
        )
        text = (res.get("content") or "").strip()
    except RuntimeError:
        text = ""
    finally:
        if messages and messages[-1].get("content") == IN_SESSION_HANDOFF_PROMPT:
            messages.pop()
    return _normalize_handoff_diary(text, prior_diary, fallback)


def generate_handoff_diary(messages: list[dict], ws: Path, url: str = "", api_key: str = "",
                           plan_file: Path | str | None = None, cancel=None,
                           in_session: bool = False, tools: list[dict] | None = None) -> str:
    """Author the 4-section Wiki Handoff Brief: in-session when `in_session=True` (warm KV cache), else via a small
    out-of-band digest call, with a deterministic fallback if the call fails or DL_HANDOFF_LLM=0."""
    if in_session and url and _switch("DL_HANDOFF_LLM"):
        return in_session_handoff_diary(messages, tools, ws, url, api_key, plan_file=plan_file, cancel=cancel)
    _, _, prior_diary, *_ = _prior_handoff(messages)
    fallback = _fallback_handoff_diary(messages, ws, plan_file=plan_file, prior_diary=prior_diary)
    if not url or not _switch("DL_HANDOFF_LLM"):
        return fallback
    plan_path = Path(plan_file) if plan_file else (ws / "PLAN.md" if (ws / "PLAN.md").is_file() else None)
    plan_sec = plan_progress(plan_path)[0][:2500] if plan_path and plan_path.is_file() else ""
    recent_notes = []
    for m in messages[-10:]:
        if m.get("role") == "assistant":
            txt = " ".join(str(m.get("content") or m.get("reasoning_content") or "").split())
            if txt:
                recent_notes.append(f"- {txt[-350:]}")
    digest = (
        f"WORKSPACE: {ws}\n\n"
        f"TASK:\n{_latest_task(messages)}\n\n"
        + (f"PREVIOUS HANDOFF DIARY:\n{prior_diary[:2000]}\n\n" if prior_diary else "")
        + (f"PLAN PROGRESS:\n{plan_sec}\n\n" if plan_sec else "")
        + f"TOOL ACTIONS & RESULTS:\n{request_actions(messages, limit=7000) or '(none)'}\n\n"
        + (f"RECENT ASSISTANT NOTES:\n" + "\n".join(recent_notes[-4:]) if recent_notes else "")
    )
    try:
        res = _cli().stream_chat_turn(
            [{"role": "system", "content": HANDOFF_SYSTEM}, {"role": "user", "content": digest}],
            url, api_key, tools=[], emit=lambda e: None, cancel=cancel,
            effort=dl_profile.env("DL_HANDOFF_EFFORT") or "low",
        )
        text = (res.get("content") or "").strip()
    except RuntimeError:
        text = ""
    return _normalize_handoff_diary(text, prior_diary, fallback)


WIKI_SECRETS_PATTERNS = [
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Stripe key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}")),
    ("connection string with password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]{3,}@[^\s/]+")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"']?(?![<{*])[A-Za-z0-9/+_\-.]{8,}")),
    ("Google OAuth Client Secret", re.compile(r"\b(GOCSPX-[A-Za-z0-9_-]{20,})")),
    ("Google OAuth Access Token", re.compile(r"\b(ya29\.[A-Za-z0-9_-]{20,})")),
    ("Google OAuth Refresh Token", re.compile(r"(?<![A-Za-z0-9])(1//0[A-Za-z0-9_-]{30,})")),
    ("Context7 API Key", re.compile(r"\b(ctx7sk-[a-zA-Z0-9-]{20,})\b")),
]


def redact_secrets(text: str) -> str:
    """Replace lines containing credentials/tokens with [redacted: <label>] so handoff archives pass wiki.py lint."""
    if not text:
        return ""
    out_lines = []
    for line in text.splitlines():
        matched_label = None
        for label, pat in WIKI_SECRETS_PATTERNS:
            if pat.search(line):
                matched_label = label
                break
        if matched_label:
            prefix_match = re.match(r"^(\s*(?:-\s*)?)", line)
            prefix = prefix_match.group(1) if prefix_match else ""
            out_lines.append(f"{prefix}[redacted: {matched_label}]")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def save_handoff_diary(ws: Path, diary: str, part: int, removed: int,
                       messages: list[dict] | None = None) -> tuple[Path, str, str]:
    """Write the Tier-1 Active Handoff Brief (`wiki/handoffs/latest.md`) and Tier-2 Stretch Archive
    (`wiki/handoffs/handoff-<date>-part-<N>.md`) with valid `wiki.py` frontmatter and `## Sources`, and register them
    in `wiki/index.md` via `wiki.py index` when `wiki/` exists.  Returns (latest_path, latest_rel, archive_rel).
    With the shared memory store on, both go to its handoffs/<project>/ (searchable, not versioned by jj) and the
    two "rel" values are absolute paths, which view_file opens from any workspace."""
    store = memory_store()
    if store:
        task_line = " ".join(_latest_task(messages or []).split())[:75] if messages else "coding session"
        stretch = request_actions(messages, limit=6000) if messages else ""
        latest, _, arch_rel = dl_memory.save_handoff(store, ws, redact_secrets(diary), part, removed,
                                                     stretch_log=redact_secrets(stretch), task_summary=task_line)
        return latest, str(latest), str(store / arch_rel)
    has_wiki = (ws / "wiki").is_dir()
    rel_dir = "wiki/handoffs" if has_wiki else ".dl-handoff"
    out_dir = ws / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    ts = time.strftime("%Y-%m-%d-%H%M%S")
    archive_name = f"handoff-{ts}-part-{part}.md"
    # Ensure a unique filename if two handoffs occur within the same second (e.g. in fast unit tests)
    if (out_dir / archive_name).exists():
        archive_name = f"handoff-{ts}-{int((time.time() % 1) * 1000):03d}-part-{part}.md"
    latest_rel = f"{rel_dir}/latest.md"
    archive_rel = f"{rel_dir}/{archive_name}"

    task_line = " ".join(_latest_task(messages or []).split())[:75] if messages else "coding session"
    task_clean = re.sub(r'["\\\n\r]', " ", task_line).strip() or "coding session"
    latest_desc = "Active session handoff brief"
    arch_desc = f"Session handoff diary part #{part} ({removed} messages archived): {task_clean}"[:140]

    latest_fm = (
        f'---\n'
        f'title: "Session Handoff Brief (Latest)"\n'
        f'type: artifact\n'
        f'description: "{latest_desc}"\n'
        f'status: active\n'
        f'tags: [handoff, session-diary]\n'
        f'created: {today}\n'
        f'updated: {today}\n'
        f'last_verified: {today}\n'
        f'---\n\n'
    )
    latest_body = (
        f"# Session Handoff Brief (Part #{part})\n\n"
        f"- **Task:** {task_clean}\n"
        f"- **Full stretch archive:** [Part #{part} ({archive_name})]({archive_name})\n"
        f"- **Archived messages:** {removed}\n\n"
        f"{diary.strip()}\n\n"
        f"## Sources\n\n"
        f"1. Generated automatically by D.L. CLI session handoff #{part} on {today}.\n"
    )

    stretch_log = request_actions(messages, limit=6000) if messages else ""
    arch_fm = (
        f'---\n'
        f'title: "Session Handoff Diary {ts} Part {part}"\n'
        f'type: artifact\n'
        f'description: "{arch_desc}"\n'
        f'status: active\n'
        f'tags: [handoff, session-diary, part-{part}]\n'
        f'created: {today}\n'
        f'updated: {today}\n'
        f'last_verified: {today}\n'
        f'---\n\n'
    )
    arch_body = (
        f"# Session Handoff Diary — Part #{part} ({ts})\n\n"
        f"- **Active handoff brief:** [Session Handoff Brief (Latest)](latest.md)\n"
        f"- **Cumulative archived messages:** {removed}\n\n"
        f"{diary.strip()}\n\n"
        + (f"## Stretch Tool Log\n\n{stretch_log}\n\n" if stretch_log else "")
        + f"## Sources\n\n"
        f"1. Generated automatically by D.L. CLI session handoff #{part} on {today}.\n"
    )

    clean_latest = redact_secrets(latest_fm + latest_body)
    clean_archive = redact_secrets(arch_fm + arch_body)
    latest_path = out_dir / "latest.md"
    archive_path = out_dir / archive_name
    latest_path.write_text(clean_latest, encoding="utf-8")
    archive_path.write_text(clean_archive, encoding="utf-8")

    if has_wiki and (ws / "wiki" / "index.md").is_file():
        wscript = find_wiki_script(ws)
        if wscript:
            try:
                subprocess.run([sys.executable, str(wscript), "index", "--root", str(ws / "wiki")],
                               capture_output=True, text=True, timeout=10, cwd=ws)
            except (OSError, subprocess.TimeoutExpired):
                pass
    return latest_path, latest_rel, archive_rel


def handoff_session(messages: list[dict], tools: list[dict] | None, limit: int, target: int, ws: Path,
                    url: str = "", api_key: str = "", plan_file: Path | str | None = None,
                    measured: tuple[int, int] | None = None, force: bool = False, cancel=None,
                    in_session: bool = False, on_handoff=None) -> dict | None:
    """When the conversation exceeds `limit` tokens (or `force`), write a condensed 4-section Wiki Handoff Diary and
    reload `messages` in place as a clean session: system prompt + protected user messages + the condensed handoff
    note + the last tool round.  Falls back to `compact_history` when there are no removable earlier rounds."""
    before = estimate_prompt_tokens(messages, tools, measured)
    if before <= limit and not force:
        return None
    protected = protected_user_messages(messages, target) | current_check_note(messages)
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    first = min(protected) if protected else (users[0] if users else 0)
    start = first + 1
    if start < len(messages) and str(messages[start].get("content", "")).startswith("[D.L. CLI:"):
        start += 1
    stop = len(messages) - 2
    removable = [u for u in _units(messages, start, stop) if not any(u[0] <= i < u[1] for i in protected)]
    if not removable:
        return compact_history(messages, tools, limit, target, measured=measured, force=force)

    prev_part, prev_removed, prior_diary, base_tokens = _prior_handoff(messages)
    # R3 Guard: avoid thrashing / back-to-back handoffs when a large protected message keeps session size high
    if not force and prev_part > 0:
        handoff_idx = next((i for i, m in enumerate(messages)
                            if m.get("role") == "user" and _HANDOFF_RE.match(str(m.get("content", "")))), None)
        growth = (before - base_tokens) if base_tokens > 0 else (
            estimate_prompt_tokens(messages[handoff_idx + 1:], tools) if handoff_idx is not None else before
        )
        if growth < dl_profile.tuned("DL_HANDOFF_MIN_GROWTH", HANDOFF_MIN_GROWTH):
            return compact_history(messages, tools, limit, target, measured=measured, force=force)

    part = prev_part + 1
    gone_idx = {i for a, b in removable for i in range(a, b)}
    total_removed = prev_removed + len(gone_idx)
    diary = _cli().generate_handoff_diary(messages, ws, url=url, api_key=api_key, plan_file=plan_file, cancel=cancel,
                                   in_session=in_session, tools=tools)
    plan_path = Path(plan_file) if plan_file else (ws / "PLAN.md" if (ws / "PLAN.md").is_file() else None)
    diary_path, diary_rel, archive_rel = save_handoff_diary(ws, diary, part, total_removed, messages=messages)

    if on_handoff is not None:
        try:
            on_handoff(messages, part)
        except Exception:
            pass

    stats = {"before": before, "reasoning": 0, "file_contents": 0, "tool_results": 0,
             "removed": len(gone_idx), "handoff": part, "diary": diary_rel, "archive": archive_rel,
             "diary_path": str(diary_path), "in_session": in_session}
    pre_msgs = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    handoff_seq = max((m.get("dl_turn") for m in pre_msgs if isinstance(m.get("dl_turn"), int)), default=0)
    kept = [m for i, m in enumerate(messages) if i not in gone_idx]
    note_msg = {"role": "user", "dl_handoff_seq": handoff_seq, "content": HANDOFF_NOTE.format(
        part=part, removed=total_removed, diary_rel=diary_rel, archive_rel=archive_rel, diary=diary,
        base_tokens=0
    )}
    if start > first + 1:
        kept[first + 1] = note_msg
    else:
        kept.insert(first + 1, note_msg)
    messages[:] = kept

    # Shrink oversized file contents or tool outputs in the kept tail round so the clean session starts lean
    for m in messages[-2:]:
        if m.get("role") in ("assistant", "tool"):
            _shrink(m, 800, 1500, stats)
    est = lambda: estimate_prompt_tokens(messages, tools)  # noqa: E731
    if est() > target:
        for result_max in (4000, 1200):
            for m in messages[-2:]:
                if m.get("role") == "tool":
                    _shrink(m, 10 ** 9, result_max, stats)
            if est() <= target:
                break
    after_tokens = est()
    stats["after"] = after_tokens
    note_msg["content"] = HANDOFF_NOTE.format(
        part=part, removed=total_removed, diary_rel=diary_rel, archive_rel=archive_rel, diary=diary,
        base_tokens=after_tokens
    )
    return stats
