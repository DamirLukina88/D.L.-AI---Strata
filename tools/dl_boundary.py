"""What the model may not do unasked: approvals, git/jj/memory/desktop/picture rules, left-over servers.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import re
try:
    from .dl_common import (
    C_ACCENT_BOLD,
    C_BOLD,
    C_MUTED,
    C_RESET,
    C_YELLOW,
    classify_command,
    classify_write,
    memory_store,
)
except ImportError:
    from dl_common import (
    C_ACCENT_BOLD,
    C_BOLD,
    C_MUTED,
    C_RESET,
    C_YELLOW,
    classify_command,
    classify_write,
    memory_store,
)


def terminal_approve(kind: str, summary: str, reason: str) -> bool:
    """Ask on this terminal before a gated action runs (the session daemon swaps in its own approver)."""
    print(f"\n{C_YELLOW}⚠ Approval needed{C_RESET} {C_MUTED}({reason}){C_RESET}\n  {C_BOLD}{summary}{C_RESET}")
    try:
        return input(f"  {C_ACCENT_BOLD}Allow?{C_RESET} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def approval_reason(name: str, args: dict, workspace: Path) -> tuple[str, str] | None:
    """(what will run, why it needs approval) for a destructive or out-of-workspace action, else None."""
    if name == "run_command":
        cmd = str(args.get("CommandLine") or args.get("command") or "")    # a list as CommandLine raised here
        cwd = command_cwd(args, workspace)
        reason = classify_command(cmd, workspace) or (classify_write(cwd, workspace) and f"runs outside the workspace ({cwd})")
        return (cmd, reason) if reason else None
    if name in ("write_to_file", "replace_file_content"):
        path_str = args.get("TargetFile") or args.get("path") or ""
        p = Path(path_str).expanduser()
        p = p if p.is_absolute() else (workspace / p)
        reason = classify_write(p, workspace)
        return (f"{name} {p}", reason) if reason else None
    if name == "save_chat" and str(args.get("filename") or "").strip():
        p = save_chat_path(args, workspace)                 # any path, written without a card before
        reason = classify_write(p, workspace)
        return (f"{name} {p}", reason) if reason else None
    if name in ("memory", "local_wiki") and memory_store():
        what = memory_global_change(args)
        return (what, "changes global memory, which every agent sees in every project") if what else None
    return None


def command_cwd(args: dict, workspace: Path) -> Path:
    """run_command's Cwd: a relative one is the workspace's (it ran in the process's folder, which a
    switch_workspace in another daemon session changes), ~ is the home folder in the gate and in the run alike."""
    if not args.get("Cwd"):
        return workspace
    return (workspace / Path(str(args["Cwd"])).expanduser()).resolve()


def save_chat_path(args: dict, workspace: Path) -> Path:
    """Where save_chat writes (the same rule as tool_save_chat)."""
    p = Path(str(args.get("filename") or "").strip()).expanduser()
    p = p if p.is_absolute() else (workspace / p).resolve()
    return p if p.suffix else p.with_suffix(".md")


def memory_global_change(args: dict) -> str | None:
    """A one-line summary when a memory call would change global/ (it then needs the user's yes), else None."""
    action = (args.get("action") or "").strip().lower()
    text = str(args.get("content") or args.get("summary") or args.get("fact") or args.get("query") or "")
    if action in ("write", "new_page") and args.get("scope") == "global":
        return f"memory write global/{args.get('page_type') or 'decision'}/{args.get('slug') or '?'}: {args.get('title') or ''}"
    if action in ("remember", "log") and (args.get("scope") == "global" or text.lower().startswith(("global ", "global:"))):
        return f"memory remember (global): {text[:120]}"
    if action == "undo":
        return f"memory undo {args.get('rev') or '@-'} (may revert a global/ change)"
    return None


# Ray keeps memory with jj through the `memory` tool and leaves git alone unless the user asks for git in the request
# (the user's rule, 2026-11-14: "git is for you and antigravity"). A command word in command position: at the start, or
# after ; & | ( ` $( or a quote, past sudo/env/time/... prefixes and VAR=value assignments.
_CMD_WORD = (r"(?:^|[;&|(`{\n]|\$\(|[\"'])\s*(?:(?:sudo|env|command|exec|nohup|nice|time|xargs|stdbuf|timeout\s+\S+|"
             r"[A-Za-z_]\w*=\S*)\s+)*(?:\S*/)?{word}(?:-[\w-]+)?(?=$|[\s;&|)`\"'])")


GIT_COMMAND = re.compile(_CMD_WORD.replace("{word}", "git"))


JJ_COMMAND = re.compile(_CMD_WORD.replace("{word}", "jj"))


ASKS_FOR_GIT = re.compile(r"\bgit\b", re.I)


# Global memory (every agent, every project) changes only when the words ask for it, in YOLO too (the user's choice,
# 2026-11-15: Ray wrote a global page about a photo on his own).  Outside YOLO the approval card still follows.
ASKS_FOR_GLOBAL = re.compile(r"\bglobal(?:ly)?\b|\bevery (?:project|agent)\b|\ball (?:projects|agents)\b|"
                             r"\beverywhere\b|\bsvugdje\b|\bglobaln\w*|\bza sve projekte\b", re.I)


def asked_text(ctx: dict | None) -> str:
    """The words a words-rule reads: this turn's request plus the task it carries on (dl_sessiond's task_text)."""
    ctx = ctx or {}
    return f"{ctx.get('user_text') or ''}\n{ctx.get('task_text') or ''}"


# A desktop viewer or opener puts a window on the user's screen: only when the words ask for it (2026-11-15: Ray ran
# xdg-open on an attached photo the model could already see).
DESKTOP_OPENER = re.compile(_CMD_WORD.replace(
    "{word}", r"(?:xdg-open|gio\s+open|kde-open\d*|kioclient\d*\s+exec|eog|gwenview|feh)"))


ASKS_TO_OPEN = re.compile(r"\b(?:open|show|display|otvori|prika[zž]i)\w*\b[^\n]*\b(?:screen|desktop|pc|computer|monitor|"
                          r"viewer|window|ekran\w*|zaslon\w*|ra[cč]unal\w*)\b|\b(?:xdg-open|gwenview|eog|feh)\b", re.I)


# The request's own words about the attached picture: changing it, or reading its metadata
ASKS_TO_EDIT = re.compile(r"\b(?:edit|convert|crop|resiz|rotat|compress|scal|shrink|chang|modif|metadata|exif|"
                          r"optimi[sz]|annotat|uredi|izre[zž]|smanj|pretvor|promijen|okren)\w*", re.I)


ATTACHED_PICTURE = re.compile(r"(?:^|(?<=\s))@([\w./-]+\.(?:jpe?g|png|webp|gif|bmp|heic|heif|tiff?|avif))\b", re.I)


REF_WORD = re.compile(r"(?:^|(?<=\s))@[\w./-]+")


# a command that leaves something running after it returns: `cmd &`, nohup, setsid, disown (not && or 2>&1)
DETACHES = re.compile(r"(?<![&>|])&(?![&>\d])|\bnohup\b|\bsetsid\b|\bdisown\b")


KEEP_RUNNING = re.compile(r"\b(?:serve|server|host|keep (?:it |them )?running|leave (?:it |them )?running|"
                          r"in the background|background|pokreni|poslu[zž]itelj|neka radi|ostavi)\w*", re.I)


def words_of(ctx: dict | None) -> str:
    """asked_text without the @file references, so a path such as uploads/crop.jpg is not read as a word."""
    return REF_WORD.sub(" ", asked_text(ctx))


def attached_pictures(ctx: dict | None) -> list[str]:
    """The pictures attached to this turn's request (@path in its own words), as written."""
    return ATTACHED_PICTURE.findall(str((ctx or {}).get("user_text") or ""))


def picture_refusal(cmd: str, ctx: dict) -> str | None:
    """A refusal for a command that opens a desktop window, or that works on the attached picture, unasked."""
    words = words_of(ctx)
    if DESKTOP_OPENER.search(cmd) and not ASKS_TO_OPEN.search(words):
        return ("Refused: this opens a window on the user's screen, which the user did not ask for. Answer in the chat;"
                " an attached picture is already shown to you.")
    if not ASKS_TO_EDIT.search(words):
        for ref in attached_pictures(ctx):
            if Path(ref).name in cmd:
                return ("Refused: the picture is already shown to you. Answer from what you see; do not open, convert,"
                        " crop, serve or re-read the file unless the user asks you to change it.")
    return None


def _listeners() -> dict[tuple[int, int], float]:
    """{(pid, port): process start time} of this user's listening TCP sockets."""
    import psutil
    out = {}
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return out
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.pid or not c.laddr:
            continue
        try:
            out[(c.pid, c.laddr.port)] = psutil.Process(c.pid).create_time()
        except psutil.Error:
            pass
    return out


def stop_left_listeners(ctx: dict | None, emit=None) -> list[str]:
    """At the end of a request: stop what Ray's detached commands left listening on a port, unless the words asked to
    keep something running.  Returns the notices."""
    left = (ctx or {}).get("bg_listeners") or []
    if not left:
        return []
    ctx["bg_listeners"] = []
    if KEEP_RUNNING.search(words_of(ctx)):
        return []
    import psutil
    notes = []
    now = _listeners()
    for pid, port, started, name in left:
        if now.get((pid, port)) != started:            # already gone, or the pid now belongs to another process
            continue
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(3)
            except psutil.TimeoutExpired:
                proc.kill()
        except psutil.Error:
            continue
        notes.append(f"Stopped the {name} server Ray left running on port {port} (pid {pid}).")
    for n in notes:
        if emit:
            emit({"type": "notice", "level": "warn", "text": n})
        else:
            print(f"{C_YELLOW}{n}{C_RESET}")
    return notes


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def agent_boundary(name: str, args: dict, workspace: Path, session_context: dict | None) -> str | None:
    """A refusal when the model (not the user) reaches for git without being asked, or for jj or the memory store's
    files instead of the `memory` tool; None otherwise.  Only agent turns carry user_text: `!cmd` typed by the user and
    scheduled jobs pass untouched."""
    ctx = session_context or {}
    if "user_text" not in ctx:
        return None
    # git_ok: this turn carries on a task whose request asked for git (dl_sessiond.Session._git_for)
    asked_git = bool(ASKS_FOR_GIT.search(str(ctx.get("user_text") or ""))) or ctx.get("git_ok") is True
    store = memory_store()
    use_memory = ("Use the memory tool instead: memory(action=\"search\"|\"read\"|\"write\"|\"remember\"|\"history\"|"
                  "\"diff\"|\"undo\"); it commits to jj for you.")
    if name == "run_command":
        cmd = str(args.get("CommandLine") or args.get("command") or "")
        cwd = command_cwd(args, workspace)
        if store is not None and (_inside(cwd, store) or str(store) in cmd or str(store.resolve()) in cmd):
            return (f"Refused: the memory store ({store}) is not reached with run_command, not even to look. "
                    + use_memory)
        if JJ_COMMAND.search(cmd):
            return "Refused: jj is used only through the memory tool, never typed by hand. " + use_memory
        if GIT_COMMAND.search(cmd) and not asked_git:
            return ("Refused: git is not yours to use unless the user asks for git in this request (git is for Claude "
                    "Code and Antigravity). Keep history with the memory tool, or ask the user whether they want git.")
        refused = picture_refusal(cmd, ctx)
        if refused:
            return refused
    if name in ("write_to_file", "replace_file_content", "view_file", "save_chat") and store is not None:
        path_str = args.get("TargetFile") or args.get("AbsolutePath") or args.get("path") or ""
        p = Path(str(path_str)).expanduser()
        p = p if p.is_absolute() else (workspace / p)
        if name == "save_chat":
            p = save_chat_path(args, workspace) if str(args.get("filename") or "").strip() else workspace
        if _inside(p, store) and (name != "view_file" or _inside(p, store / "private") or _inside(p, store / ".memory")):
            return (f"Refused: {name} does not touch the memory store's files ({p}). " + use_memory
                    + (" Credentials: memory(action=\"env_list\")." if name == "view_file" else ""))
    if name == "git_diff_audit" and not asked_git:
        return "Refused: git is not yours to use unless the user asks for git in this request."
    if (name in ("memory", "local_wiki") and str(args.get("action") or "").strip().lower() in ("write", "new_page", "remember", "log")
            and memory_global_change(args) and not ASKS_FOR_GLOBAL.search(asked_text(ctx))):
        return ("Refused: global memory (every agent, every project) changes only when the user asks for a global "
                "rule in this request. Save it to this project instead (scope=\"project\").")
    return None
