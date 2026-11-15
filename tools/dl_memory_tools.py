"""The memory tool and slash commands, chat saving, health and engine status, clearing.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import datetime
import re
import threading
import time
try:
    from .dl_common import (
    DEFAULT_API_KEY,
    DEFAULT_URL,
    dl_memory,
    format_health_card,
    get_system_health,
    memory_store,
)
except ImportError:
    from dl_common import (
    DEFAULT_API_KEY,
    DEFAULT_URL,
    dl_memory,
    format_health_card,
    get_system_health,
    memory_store,
)
try:
    from .dl_prompt import _read_text, build_dl_system_prompt
except ImportError:
    from dl_prompt import _read_text, build_dl_system_prompt
try:
    from .dl_status import check_status, format_messages_to_markdown, sync_current_chat_state
except ImportError:
    from dl_status import check_status, format_messages_to_markdown, sync_current_chat_state
try:
    from .dl_wiki_legacy import tool_local_wiki
except ImportError:
    from dl_wiki_legacy import tool_local_wiki


def tool_memory(args: dict, workspace: Path, mode: str = "act", session_context: dict | None = None,
                approved: bool = False) -> str:
    """Ray's `memory` tool (and the old `local_wiki` name): the shared store when it is on, else the project wiki.
    approved: the call passed the approval gate (a card, or YOLO) - only then may it change global/."""
    store = memory_store()
    if not store:
        legacy = dict(args)
        legacy["action"] = {"read": "read_page", "write": "new_page"}.get(args.get("action") or "", args.get("action"))
        legacy.setdefault("page_path", args.get("path"))
        legacy.setdefault("summary", args.get("content"))
        return tool_local_wiki(legacy, workspace, mode=mode, session_context=session_context)
    a = dict(args)
    action = (a.get("action") or "").strip().lower()
    if not a.get("content") and a.get("summary"):
        a["content"] = a["summary"]
    if action in ("write", "new_page", "remember", "log") and a.get("scope") not in ("global",):
        a["scope"] = "project"
    if action == "backup":
        if mode == "plan":
            return "Error: [PLAN MODE] Action 'backup' modifies memory and is disabled in Plan Mode."
        return memory_backup(workspace, (session_context or {}).get("messages"), note=a.get("content") or "")
    if action in ("remember", "log") and not (a.get("content") or a.get("query") or a.get("fact")):
        msgs = (session_context or {}).get("messages") or []
        last = next((m["content"] for m in reversed(msgs) if m.get("role") == "assistant"
                     and isinstance(m.get("content"), str) and len(m["content"]) > 10), "")
        a["content"] = last.splitlines()[0].strip() if last else ""
    if action == "init":
        return f"Memory is the shared store at {store}; no per-project setup is needed."
    try:
        return dl_memory.handle_memory_action(a, workspace=workspace, mode=mode, approved=approved)
    except Exception as e:                      # jj missing, store unreadable: a clear error, not a crashed turn
        return f"Error: memory {action} failed: {type(e).__name__}: {e}"


MEMORY_SLASH = ("/memory", "/wiki", "/remember", "/recall")


def memory_slash(text: str, workspace: Path, messages: list[dict] | None = None, mode: str = "act") -> str:
    """/memory, /wiki (alias), /remember, /recall typed by the user, against the shared store.  The user typed it,
    so a global change (/remember global ..., /memory undo) is the user's own and needs no further card."""
    t = text.strip()
    for old, new in (("/wiki-backup", "/memory backup"), ("/wiki-lint", "/memory lint"),
                     ("/recall", "/memory search"), ("/wiki", "/memory")):
        if t == old or t.startswith(old + " "):
            t = new + t[len(old):]
            break
    if t == "/remember" or t.startswith("/remember "):
        fact = t[len("/remember"):].strip()
        scope = "project"
        if fact.lower().startswith("global "):
            scope, fact = "global", fact[7:].strip()
        elif fact.lower().startswith("project "):
            fact = fact[8:].strip()
        return tool_memory({"action": "remember", "content": fact, "scope": scope}, workspace, mode=mode,
                           session_context={"messages": messages}, approved=True)
    sub, _, rest = t[len("/memory"):].strip().partition(" ")
    rest = rest.strip()
    if sub in ("", "digest", "status", "info"):
        return tool_memory({"action": "digest"}, workspace, mode=mode)
    if sub in ("search", "recall"):
        return tool_memory({"action": "search", "query": rest}, workspace, mode=mode) if rest else "Usage: /memory search <terms>"
    if sub in ("history", "log"):
        return tool_memory({"action": "history"}, workspace, mode=mode)
    if sub in ("diff", "undo"):
        return tool_memory({"action": sub, "rev": rest or "@-"}, workspace, mode=mode, approved=True)
    if sub in ("lint", "projects"):
        return tool_memory({"action": sub}, workspace, mode=mode)
    if sub == "env":
        return tool_memory({"action": "env_list"}, workspace, mode=mode)
    if sub == "backup":
        return tool_memory({"action": "backup", "content": rest}, workspace, mode=mode,
                           session_context={"messages": messages})
    if sub == "init":
        return tool_memory({"action": "init"}, workspace, mode=mode)
    return tool_memory({"action": "search", "query": (sub + " " + rest).strip()}, workspace, mode=mode)


def memory_backup(workspace: Path, messages: list[dict] | None = None, note: str = "") -> str:
    """/wiki-backup in the shared store: a session snapshot page under this project's artifacts."""
    recent = []
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            if m.get("role") == "user" and not c.startswith(("/", "[D.L. CLI")):
                recent.append(f"- **Request:** {c[:150].strip()}")
            elif m.get("role") == "assistant" and len(c) > 30 and not c.lstrip().startswith("<"):
                recent.append(f"- **Outcome:** {c.splitlines()[0][:150].strip()}")
    body = "\n".join(([f"- **Note:** {note}"] if note else []) + recent[-10:]) or "- General workspace session."
    plan = workspace / "PLAN.md"
    if plan.is_file():
        body += "\n\n### Plan (PLAN.md)\n\n```markdown\n" + _read_text(plan, 4000) + "\n```"
    stamp = time.strftime("%Y-%m-%d-%H-%M")
    return dl_memory.write_page(memory_store(), page_type="artifact", slug=f"session-backup-{stamp}",
                                title=f"Session Backup {stamp}", description=f"Session snapshot {stamp}",
                                content=f"## Summary\n\n{body}", tags="session, backup", scope="project",
                                workspace=workspace)


def tool_save_chat(args: dict, workspace: Path, session_context: dict | None = None) -> str:
    custom_name = (args.get("filename") or "").strip()
    messages = (session_context or {}).get("messages", [])
    user_or_asst = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not user_or_asst:
        return "No chat messages to save yet."

    now_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
    if custom_name:
        out_p = Path(custom_name).expanduser()
        if not out_p.is_absolute():
            out_p = (workspace / out_p).resolve()
        if not out_p.suffix:
            out_p = out_p.with_suffix(".md")
    else:
        out_p = workspace / f"dl-ai-code-chat-{now_str}.md"

    md_content = format_messages_to_markdown(messages, model_name="Qwen3.8-Flash-Next Coder", workspace=workspace)
    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md_content, encoding="utf-8")
        return f"Chat successfully saved as Markdown to {out_p} ({len(md_content):,} bytes, {len(user_or_asst)} messages)."
    except Exception as e:
        return f"Error saving chat to {out_p}: {e}"


def tool_get_system_health(args: dict, workspace: Path) -> str:
    stats = get_system_health(DEFAULT_URL, DEFAULT_API_KEY)
    card = format_health_card(stats)
    clean_card = re.sub(r'\033\[[0-9;]*m', '', card)
    return clean_card.strip()


def tool_get_engine_status(args: dict, workspace: Path) -> str:
    status_str = check_status(DEFAULT_URL, DEFAULT_API_KEY)
    clean_status = re.sub(r'\033\[[0-9;]*m', '', status_str)
    return clean_status.strip()


def tool_clear_conversation(args: dict, workspace: Path, session_context: dict | None = None) -> str:
    session = (session_context or {}).get("session")
    if session is not None and hasattr(session, "messages"):
        session.messages = [{"role": "system", "content": build_dl_system_prompt(session.workspace, session.mode)}]
        with getattr(session, "lock", threading.Lock()):
            session.events = []
        if hasattr(session, "emit"):
            session.emit({"type": "cleared"})
        if hasattr(session, "mcp") and hasattr(session.mcp, "close"):
            session.mcp.close()
        if hasattr(session, "notice"):
            session.notice(f"Memory reset ({session.mode} mode).")
        if hasattr(session, "emit_state"):
            session.emit_state()
        return "Conversation history and context memory have been reset."

    messages = (session_context or {}).get("messages")
    if messages is not None:
        messages.clear()
        mode = (session_context or {}).get("mode", "act")
        messages.append({"role": "system", "content": build_dl_system_prompt(workspace, mode=mode)})
        sync_current_chat_state(messages, workspace)
        return "Conversation history and context memory have been reset."

    return "Conversation reset requested."
