"""The finish checks: change tracking, browser errors, reviewer, review notes.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
try:
    from .dl_boundary import terminal_approve
except ImportError:
    from dl_boundary import terminal_approve
try:
    from .dl_checkpoints import SCAN_SKIP
except ImportError:
    from dl_checkpoints import SCAN_SKIP
try:
    from .dl_common import (
    C_MUTED,
    C_RESET,
    _note,
    _switch,
    cli as _cli,
    dl_advisor,
    dl_effort,
)
except ImportError:
    from dl_common import (
    C_MUTED,
    C_RESET,
    _note,
    _switch,
    cli as _cli,
    dl_advisor,
    dl_effort,
)
try:
    from .dl_context import (
    BROWSER_LIVE_NOTE,
    BROWSER_NOTE,
    DONE_NOTE,
    EVIDENCE_NOTE,
    REVIEW_NOTE,
    is_cli_note,
)
except ImportError:
    from dl_context import (
    BROWSER_LIVE_NOTE,
    BROWSER_NOTE,
    DONE_NOTE,
    EVIDENCE_NOTE,
    REVIEW_NOTE,
    is_cli_note,
)
try:
    from .dl_prompt import NOW_PREFIX, plan_progress
except ImportError:
    from dl_prompt import NOW_PREFIX, plan_progress


DONE_STALL_LIMIT = 3


# 2026-10-31, honest bench run r2: the reviewer called "the test is wrong, I changed it and said so" a missed
# requirement ("the task says fix money.py"), and the agent then special-cased split(100, 3) in money.py to satisfy it.
REVIEWER_SYSTEM = (
    "You review a coding agent's finished work. You see the task, the agent's plan progress (if any), the diff of the "
    "files it changed, and its final answer. Report only real problems: bugs, requirements of the task that the diff "
    "does not meet, and claims in the final answer that the diff or the task does not support. Do not report style. "
    "Write each problem on its own line as \"- <file>:<line or area> - <problem>\". If there are none, answer exactly "
    "NO PROBLEMS. Judge the work against the LATEST message; an earlier message is context, done in an earlier "
    "request. The diff shows file contents only: a new folder, a workspace switch, and files the workspace's "
    ".gitignore hides (a wiki/ folder is private and always hidden) never appear in it, so check those against "
    "TOOL ACTIONS, what this request's tools did and answered, and do not report them missing from the diff. "
    "Judge what the user needs, not the literal wording: when a test or the task itself is wrong or impossible, an "
    "agent that says so plainly (and changes the test only if it says it did) has done the right thing; do not report "
    "that as a missed requirement. Do report a test changed without saying so, a test skipped or removed, and code "
    "special-cased to the inputs a test uses (a branch for those exact values) - those fake a pass.")


CLAIM_WORDS = re.compile(r"\b(verified|tested|all (?:\d+ )?(?:tests|checks) pass(?:ed)?|tests? pass(?:ed|es)?|passes|"
                         r"passed|confirmed|works correctly|is correct|cross-checked)\b", re.I)


CHECK_CMD = re.compile(r"\b(test|tests|pytest|unittest|node|python3?|bash|make|npm|npx|harness|check|audit|curl|go|"
                       r"cargo|ctest)\b")


WEB_SUFFIXES = (".html", ".htm", ".js", ".mjs", ".css")


PLAYWRIGHT_CORE = os.environ.get("DL_PLAYWRIGHT_CORE",
                                 str(Path.home() / ".local/share/dl-ai/mcp-npm/node_modules/playwright-core"))


REVIEW_DIFF_MAX = 16000


REVIEW_EFFORT = "low"           # the review at the session's level took 9.5 min on crc32c (2026-10-20), mostly thinking


# `node -e` puts the first argument at process.argv[1], not [2]; reading [2]/[3] made every check fail with "list
# index out of range" and get skipped (found 2026-10-20 22:45: the check had never run).
BROWSER_JS = r"""
const [PW, PAGE] = process.argv.slice(-2);
const { chromium } = require(PW);
(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await b.newPage(); const errs = [];
  p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  p.on('pageerror', e => errs.push('uncaught: ' + String(e)));
  p.on('requestfailed', r => errs.push('request failed: ' + r.url()));
  await p.goto(PAGE, { waitUntil: 'load', timeout: 20000 });
  await p.waitForTimeout(2000);
  console.log(JSON.stringify({ errors: errs.slice(0, 20) }));
  await b.close();
})().catch(e => { console.log(JSON.stringify({ launch_error: String(e).slice(0, 400) })); });
"""


class RequestChanges:
    """What this request changed through the file tools: each file's content before its first edit (for the
    reviewer's diff), and the order of edits and check commands (for the evidence check)."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.before: dict[Path, str | None] = {}
        self.last_edit = -1
        self.last_check = -1
        self.step = 0

    def _path(self, args: dict) -> Path | None:
        raw = args.get("TargetFile") or args.get("AbsolutePath") or args.get("path")
        if not raw:
            return None
        p = Path(str(raw)).expanduser()
        return (p if p.is_absolute() else (self.workspace / p)).resolve()

    def before_tool(self, name: str, args: dict) -> None:
        self.step += 1
        if name in ("write_to_file", "replace_file_content"):
            p = self._path(args)
            if p is not None and p not in self.before:
                try:
                    self.before[p] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
                except OSError:
                    self.before[p] = None
            self.last_edit = self.step
        elif name == "run_command" and CHECK_CMD.search(str(args.get("CommandLine") or "")):
            self.last_check = self.step

    def changed(self) -> list[Path]:
        out = []
        for p, old in self.before.items():
            try:
                new = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
            except OSError:
                new = None
            if new != old:
                out.append(p)
        return out

    def diff(self) -> str:
        chunks = []
        for p in self.changed():
            old = self.before.get(p) or ""
            try:
                new = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            except OSError:
                new = ""
            rel = p.relative_to(self.workspace) if p.is_relative_to(self.workspace) else p
            chunks.append("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                       f"a/{rel}", f"b/{rel}", n=2)))
        text = "\n".join(chunks)
        return text if len(text) <= REVIEW_DIFF_MAX else (
            text[:REVIEW_DIFF_MAX] + f"\n[... diff cut at {REVIEW_DIFF_MAX:,} of {len(text):,} chars]")


def workspace_snapshot(ws: Path, cap: int = 20000) -> str:
    """A cheap fingerprint of the folder (names, sizes, mtimes) for the done check's "nothing changed" guard."""
    h, n = hashlib.sha256(), 0
    for root, dirs, files in os.walk(ws):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv"))
        for f in sorted(files):
            try:
                st = os.stat(os.path.join(root, f))
            except OSError:
                continue
            h.update(f"{root}/{f}:{st.st_size}:{st.st_mtime_ns}\n".encode())
            n += 1
            if n >= cap:
                return h.hexdigest()
    return h.hexdigest()


def browser_errors(page: Path, timeout: int = 60) -> tuple[list[str] | None, str]:
    """Load a page in headless Chromium (playwright-core from the MCP install); (errors, "") or (None, why not)."""
    if not Path(PLAYWRIGHT_CORE).is_dir() or not shutil.which("node"):
        return None, "playwright-core or node not found"
    try:
        r = subprocess.run(["node", "-e", BROWSER_JS, PLAYWRIGHT_CORE, page.resolve().as_uri()],
                           capture_output=True, text=True, timeout=timeout)
        data = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError) as e:
        return None, f"browser check failed: {e}"
    if "launch_error" in data:
        return None, data["launch_error"]
    return [str(e)[:300] for e in data.get("errors") or []], ""


def web_pages(ws: Path) -> dict[Path, int]:
    """{page: mtime_ns} of the HTML pages at the workspace's top level and one folder down."""
    out: dict[Path, int] = {}
    for pattern in ("*.html", "*.htm", "*/*.html", "*/*.htm"):
        for p in ws.glob(pattern):
            if any(part in SCAN_SKIP or part in ("tmp", "temp") for part in p.relative_to(ws).parts[:-1]):
                continue
            try:
                out[p] = p.stat().st_mtime_ns
            except OSError:
                pass
    return out


def changed_pages(state: dict, ws: Path) -> list[Path]:
    """Pages new or changed since state["pages"] was taken, index.html first.  This sees pages a build script
    writes, which the file tools never touch: CONTRA edits src/*.part and builds index.html with tools/build.sh, so
    until 2026-10-20 the browser check never chose its page."""
    old = state.get("pages") or {}
    return sorted((p for p, m in web_pages(ws).items() if old.get(p) != m),
                  key=lambda p: (p.name != "index.html", str(p)))


def browser_nudge(state: dict, ws: Path, emit=None) -> str | None:
    """At each YOLO auto-continue: load a page that changed since the last look and hand the agent its console
    errors.  The finish check alone runs only when a request ends, and a YOLO request can run for hours.  The same
    errors are not sent twice in a row."""
    if not _switch("DL_BROWSER_CHECK"):
        return None
    pages = changed_pages(state, ws)
    if not pages:
        return None
    state["pages"] = web_pages(ws)
    errs, why = _cli().browser_errors(pages[0])
    if errs is None or errs == state.get("browser_errs"):
        return None
    state["browser_errs"] = errs
    if not errs:
        return None
    rel = pages[0].relative_to(ws) if pages[0].is_relative_to(ws) else pages[0]
    _note(emit, f"Browser check during the run: {rel} reported {len(errs)} error(s); told the agent.", "warn")
    return BROWSER_LIVE_NOTE.format(page=rel, n=len(errs), errors="\n".join(f"- {e}" for e in errs))


def _user_message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


def _latest_task(messages: list[dict]) -> str:
    real = [m for m in messages if m.get("role") == "user" and not is_cli_note(m)
            and (isinstance(m.get("content"), str) or isinstance(m.get("content"), list))]
    texts = [NOW_PREFIX.sub("", _user_message_text(m.get("content"))).strip()[:3000] for m in real[-2:]]
    if len(texts) < 2:
        return "\n\n".join(texts)
    # 2026-10-30: unlabelled, "Create a folder TEST2" then "Init the wiki" read as one task, and the review of the
    # wiki request reported the folder missing from its diff
    return f"EARLIER MESSAGE (context):\n{texts[0]}\n\nLATEST MESSAGE:\n{texts[1]}"


def request_actions(messages: list[dict], limit: int = 3000) -> str:
    """The tool calls since the user's latest message, one line each with the start of the result: what a diff
    cannot show.  2026-10-30: local_wiki init wrote a wiki the workspace's .gitignore hides, the reviewer saw only
    AGENTS.md and CLAUDE.md, reported the wiki and the folder missing, and the agent spent 4 minutes disproving it.
    External actions (sending mail, translating, scheduling) are listed first and in full so the limit never drops them."""
    start = max((i for i, m in enumerate(messages) if m.get("role") == "user" and not is_cli_note(m)), default=-1)
    results = {m.get("tool_call_id"): str(m.get("content") or "") for m in messages[start + 1:] if m.get("role") == "tool"}
    external_lines = []
    other_lines = []

    def is_external(tool_name: str) -> bool:
        low = tool_name.lower()
        return any(k in low for k in ("send_mail", "send_gmail", "deepl", "schedule", "draft_mail"))

    for m in messages[start + 1:]:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name", "?")
            args_str = str(fn.get("arguments") or "")
            res = " ".join(results.get(tc.get("id"), "").split())
            if is_external(name):
                external_lines.append(f"- {name} {args_str} -> {res[:200]}")
            elif name in ("write_to_file", "replace_file_content", "run_command"):
                args_summary = args_str[:80] + ("..." if len(args_str) > 80 else "")
                res_summary = res[:80] + ("..." if len(res) > 80 else "")
                other_lines.append(f"- {name} {args_summary} -> {res_summary}")
            else:
                other_lines.append(f"- {name} {args_str[:200]} -> {res[:200]}")

    lines = external_lines + other_lines
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n[...]"


def review_changes(messages: list[dict], changes: RequestChanges, final: str, plan_section: str, url: str,
                   api_key: str, cancel=None, effort: str | None = None, diff: str | None = None) -> str:
    """One call to the same model with a clean context; the findings, or "" when it found nothing.  `diff` (from
    the checkpoints) replaces the file tools' own diff when given."""
    body = (f"TASK (the user's latest messages):\n{_latest_task(messages)}\n\n"
            + (f"PLAN PROGRESS:\n{plan_section[:3000]}\n\n" if plan_section else "")
            + f"DIFF:\n{diff if diff is not None else changes.diff()}\n\n"
            + f"TOOL ACTIONS:\n{request_actions(messages) or '(none)'}\n\nFINAL ANSWER:\n{final[:3000]}")
    level = os.environ.get("DL_REVIEW_EFFORT") or REVIEW_EFFORT
    # the level needs its token budget too: without one the engine let the "low" review think for 10,000+ tokens
    # (7 minutes and counting, 2026-11-15 10:07)
    budget = dl_effort.budget_for(level) if dl_effort is not None and level in ("low", "medium", "high") else 0
    try:
        res = _cli().stream_chat_turn([{"role": "system", "content": REVIEWER_SYSTEM}, {"role": "user", "content": body}],
                               url, api_key, tools=[], emit=lambda e: None, cancel=cancel, effort=level, budget=budget)
    except RuntimeError:
        return ""
    text = (res.get("content") or "").strip()
    if not text or text.upper().startswith("NO PROBLEMS"):
        return ""
    return text[:2500]


def finish_checks(state: dict, messages: list[dict], final: str, mode: str, ws: Path, session_context: dict | None,
                  url: str, api_key: str, emit=None, cancel=None, effort: str | None = None) -> str | None:
    """Run when the model ended with no tool call.  Returns a note to send the agent back with, or None when the
    reply really is the end.  `state` lives for one request (which checks already ran, the stall counter)."""
    if mode != "act" or (cancel is not None and cancel.is_set()):
        return None
    ctx = session_context if session_context is not None else {}
    yolo = bool(ctx.get("yolo"))
    plan = Path(ctx["plan_file"]) if ctx.get("plan_file") else None
    section = ""
    if plan is not None and plan.is_file() and _switch("DL_DONE_CHECK"):
        section, open_items, done_items, blocked = plan_progress(plan)
        if not section or not (open_items or done_items):   # nothing to tick yet: writing the checklist is the open step
            open_items = ['add a "## Progress" checklist to the plan, one "- [ ] <step>" line per step, ticking '
                          'the steps that are already done']
        if section and not open_items:
            _note(emit, f"Plan complete: all {len(done_items)} steps in {plan.name} are ticked.")
            ctx["plan_file"] = None
        elif open_items and blocked:
            _note(emit, f"{plan.name} is blocked: see its Blocked line. {len(open_items)} step(s) still open.", "warn")
            return None
        elif open_items and not yolo:
            _note(emit, f"{len(open_items)} step(s) in {plan.name} are still open; /continue to go on.", "warn")
            return None
        elif open_items:
            snap = workspace_snapshot(ws)
            state["stalls"] = state.get("stalls", 0) + 1 if snap == state.get("snap") else 0
            state["snap"] = snap
            if state["stalls"] >= DONE_STALL_LIMIT:
                _note(emit, f"Stopped: {plan.name} has {len(open_items)} open step(s), but the last "
                            f"{DONE_STALL_LIMIT} times it was sent back nothing in the folder changed.", "warn")
                return None
            items = "; ".join(i[:120] for i in open_items[:3]) + (" ..." if len(open_items) > 3 else "")
            _note(emit, f"Done check: {len(open_items)} plan step(s) still open; sent the agent back to them.")
            return DONE_NOTE.format(plan=plan.name, n=len(open_items), items=items)
    changes: RequestChanges | None = state.get("changes")
    changed = changes.changed() if changes else []
    built = changed_pages(state, ws) if "pages" in state else []
    if (changed or built) and _switch("DL_BROWSER_CHECK") and not state.get("browser"):
        web = [p for p in changed if p.suffix.lower() in WEB_SUFFIXES]
        if web or built:
            state["browser"] = True
            pages = [p for p in web if p.suffix.lower() in (".html", ".htm")] or built or \
                    [p for p in (ws / "index.html",) if p.is_file()]
            if pages:
                errs, why = _cli().browser_errors(pages[0])
                rel = pages[0].relative_to(ws) if pages[0].is_relative_to(ws) else pages[0]
                if errs is None:
                    _note(emit, f"Browser check skipped: {why}", "warn")
                elif errs:
                    _note(emit, f"Browser check: {rel} reported {len(errs)} error(s); sent the agent back.", "warn")
                    return BROWSER_NOTE.format(page=rel, n=len(errs), errors="\n".join(f"- {e}" for e in errs))
                else:
                    _note(emit, f"Browser check: {rel} loads with no console errors.")
    if changed and _switch("DL_EVIDENCE") and not state.get("evidence"):
        m = CLAIM_WORDS.search(final or "")
        if m and changes.last_check < changes.last_edit:
            state["evidence"] = True
            _note(emit, f"Evidence check: the answer says \"{m.group(0)}\" with no check after the last edit; "
                        f"sent the agent back.", "warn")
            return EVIDENCE_NOTE.format(word=m.group(0))
    # 2026-10-21: the CONTRA review saw 1 of the request's changed files; the rest came from shell commands and
    # builds, which only the checkpoints record.
    cps, start = state.get("cps"), state.get("cp_start")
    via_cps = cps.changed_since(start) if cps is not None else []
    if (changed or via_cps) and _switch("DL_REVIEW") and not state.get("review"):
        state["review"] = True
        n_files = len(set(via_cps) | {str(p.relative_to(ws)) if p.is_relative_to(ws) else str(p) for p in changed})
        _note(emit, f"Reviewing the changes to {n_files} file(s) with a fresh context...")
        findings = review_changes(messages, changes, final, section, url, api_key, cancel=cancel, effort=effort,
                                  diff=cps.diff_since(start, REVIEW_DIFF_MAX) if via_cps else None)
        if findings:
            n = sum(1 for l in findings.splitlines() if l.strip().startswith("-")) or 1
            _note(emit, f"Review: {n} finding(s); sent the agent back to check them.", "warn")
            if emit:                        # the findings themselves, for the Code tab and the transcript
                emit({"type": "output", "title": "Review findings", "text": findings, "ansi": findings})
            else:
                print(f"{C_MUTED}{findings}{C_RESET}")
            return REVIEW_NOTE.format(findings=findings)
        _note(emit, "Review: no problems found.")
    # the DeepSeek helper (DL_ADVISOR=1): a run that started from an approved plan gets a final review by Pro, and
    # goes back for fixes until it passes (at most DL_ADVISOR_FINAL_MAX rounds; the user's choice, 2026-11-14)
    if (dl_advisor is not None and dl_advisor.enabled() and state.get("from_plan") and (changed or via_cps)
            and os.environ.get("DL_ADVISOR_FINAL", "1") != "0"):
        return _final_review(state, final, ws, ctx, changed, via_cps, emit)
    return None


def final_review_files(ws: Path, changed: list, via_cps: list, plan: str | None = None) -> list[str]:
    """The files the final review reads, most important first, as paths relative to the workspace.
    First the project files the agent edited with its file tools, then other project files the checkpoints saw
    change (shell edits, or the user's own files), then test and scratch files.  Left out: files outside the
    workspace (scratch copies in /tmp) and the plan, which the review gets on its own.  On 2026-11-15 two stale
    scripts in /tmp, the plan and a file of the user's filled the brief before the game itself."""
    root = Path(ws).resolve()
    plan_rel = None
    if plan:
        try:
            plan_rel = str(Path(plan).resolve().relative_to(root))
        except (ValueError, OSError):
            pass
    edited = []
    for p in changed:
        try:
            rel = str(Path(p).resolve().relative_to(root))
        except (ValueError, OSError):
            continue                                # outside the workspace: not part of the result
        if rel not in edited:
            edited.append(rel)
    others = [n for n in sorted(set(via_cps)) if n not in edited and not Path(n).is_absolute()]
    ordered = ([n for n in edited if not _cli().SCRATCH_FILE.search(n)] + [n for n in others if not _cli().SCRATCH_FILE.search(n)]
               + [n for n in edited + others if _cli().SCRATCH_FILE.search(n)])
    return [n for n in ordered if n != plan_rel]


def _final_review(state: dict, final: str, ws: Path, ctx: dict, changed: list, via_cps: list, emit) -> str | None:
    """One round of the Pro final review: a note sending the agent back, or None when it passed or must stop."""
    rounds_max = int(os.environ.get("DL_ADVISOR_FINAL_MAX") or 5)
    done = state.get("final_rounds", 0)
    snap = workspace_snapshot(ws)
    if done and snap == state.get("final_snap"):
        _note(emit, "Final review: nothing changed since the last review round, so it was not repeated; the "
                    "findings above are still open.", "warn")
        return None
    if done >= rounds_max:
        _note(emit, f"Final review: stopped after {rounds_max} rounds; the fixes after the last round were not "
                    "reviewed again.", "warn")
        return None
    names = final_review_files(ws, changed, via_cps, state.get("from_plan"))
    files = {}
    for n in names:
        p = (ws / n) if not Path(n).is_absolute() else Path(n)
        try:
            if p.is_file() and p.stat().st_size <= 200_000:
                files[n] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    try:
        plan = Path(state["from_plan"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        plan = ""
    adv = state.setdefault("final_advisor", dl_advisor.Advisor(ctx))
    _note(emit, f"Final review by DeepSeek Pro, round {done + 1} of at most {rounds_max} ({len(files)} file(s))...")
    verdict, note = adv.final_review(ctx.get("mcp"), plan, final or "", files, done + 1,
                                     approve=ctx.get("approve") or terminal_approve, emit=emit)
    if verdict == "skip":
        return None
    state["final_rounds"], state["final_snap"] = done + 1, snap
    if verdict == "pass":
        _note(emit, f"Final review: passed in round {done + 1}.")
        return None
    _note(emit, f"Final review: problems found in round {done + 1}; sent the agent back to fix them.", "warn")
    if emit:
        emit({"type": "output", "title": "Final review findings (DeepSeek Pro)", "text": note, "ansi": note})
    return note
