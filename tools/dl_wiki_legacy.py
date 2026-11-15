"""The per-project wiki/ tools, used only when the shared memory store is off.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import datetime
import re
import subprocess
import time
try:
    from .dl_prompt import build_dl_system_prompt
except ImportError:
    from dl_prompt import build_dl_system_prompt
try:
    from .dl_status import sync_current_chat_state
except ImportError:
    from dl_status import sync_current_chat_state
try:
    from .dl_tools_schema import find_wiki_script, resolve_wiki_root
except ImportError:
    from dl_tools_schema import find_wiki_script, resolve_wiki_root


def perform_wiki_lint(workspace: Path, auto_fix: bool = True) -> str:
    wscript = find_wiki_script(workspace)
    if not wscript:
        return "Error: local-wiki script (wiki.py) not found on system."
    wroot = resolve_wiki_root(workspace)
    if not wroot:
        return f"Local Wiki is inactive in this workspace ({workspace}). Call /wiki init to initialize."
    cmd = ["python3", str(wscript), "lint"]
    if auto_fix:
        cmd.append("--write-index")
    cmd.extend(["--root", str(wroot)])
    try:
        res = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=30)
        out = (res.stdout or "").strip()
        if res.stderr:
            out += ("\n" + res.stderr.strip())
        return out or "0 error(s), 0 warning(s) checked."
    except Exception as e:
        return f"Error executing wiki lint: {e}"


def perform_wiki_backup(workspace: Path, messages: list[dict] | None = None, note: str = "") -> str:
    wscript = find_wiki_script(workspace)
    if not wscript:
        return "Error: local-wiki script (wiki.py) not found on system."
    wroot = resolve_wiki_root(workspace)
    if not wroot:
        target_wiki = (workspace / "wiki").resolve()
        try:
            subprocess.run(["python3", str(wscript), "init", "--root", str(target_wiki)], cwd=workspace, check=True, capture_output=True)
            wroot = target_wiki
        except Exception as e:
            return f"Error initializing wiki for backup: {e}"

    artifacts_dir = wroot / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d-%H-%M")
    date_str = now_dt.strftime("%Y-%m-%d")

    recent_work = []
    if messages:
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                if role == "user" and not content.startswith("/"):
                    recent_work.append(f"- **Request:** {content[:150].strip()}")
                elif role == "assistant" and len(content) > 30:
                    summary = content.splitlines()[0][:150].strip()
                    if summary and not summary.startswith("<"):
                        recent_work.append(f"- **Outcome:** {summary}")

    plan_path = workspace / "PLAN.md"
    plan_text = ""
    if plan_path.is_file():
        try:
            p_content = plan_path.read_text(encoding="utf-8", errors="replace")[:4000]
            plan_text = f"\n\n### Implementation Plan (PLAN.md)\n\n```markdown\n{p_content}\n```"
        except Exception:
            pass

    work_summary = "\n".join(recent_work[-10:]) if recent_work else "- General workspace development and verification session."
    if note:
        work_summary = f"- **Note:** {note}\n" + work_summary

    artifact_slug = f"session-backup-{now_str}"
    artifact_file = artifacts_dir / f"{artifact_slug}.md"

    content = f"""---
title: "Session Backup {now_str}"
type: artifact
description: "Snapshot of session goals, modified files, and verified outcomes on {date_str}."
status: active
tags: [session, backup, artifacts, dl-cli]
created: {date_str}
updated: {date_str}
last_verified: {date_str}
---

# Session Backup {now_str}

## Summary

Snapshot of session progress, goals achieved, and verified state recorded by `/wiki-backup`.

---

## 1. Accomplishments & History

{work_summary}{plan_text}

---

## 2. Related Pages

- [About This Wiki](../README.md)
- [Wiki Index](../index.md)

---

## Sources

1. D.L. CLI session backup, {date_str}.
"""
    try:
        artifact_file.write_text(content, encoding="utf-8")
        subprocess.run(["python3", str(wscript), "lint", "--write-index", "--root", str(wroot)], cwd=workspace, capture_output=True)
        subprocess.run(["python3", str(wscript), "log", f"Artifact Backup. Backed up session snapshot {artifact_slug}", "--root", str(wroot)], cwd=workspace, capture_output=True)
        return f"Saved → [{artifact_file.name}](wiki/artifacts/{artifact_file.name})"
    except Exception as e:
        return f"Error creating session backup: {e}"


def perform_wiki_remember(workspace: Path, fact: str, messages: list[dict] | None = None) -> str:
    wscript = find_wiki_script(workspace)
    if not wscript:
        return "Error: local-wiki script (wiki.py) not found on system."
    wroot = resolve_wiki_root(workspace)
    if not wroot:
        target_wiki = (workspace / "wiki").resolve()
        try:
            subprocess.run(["python3", str(wscript), "init", "--root", str(target_wiki)], cwd=workspace, check=True, capture_output=True)
            wroot = target_wiki
        except Exception as e:
            return f"Error initializing wiki: {e}"

    fact_clean = (fact or "").strip()
    if not fact_clean and messages:
        for m in reversed(messages):
            if m.get("role") == "assistant" and isinstance(m.get("content"), str) and len(m.get("content")) > 10:
                fact_clean = m["content"].splitlines()[0].strip()
                break

    if not fact_clean:
        return "Error: Please specify the fact, decision, or preference to remember. Usage: /remember <fact>"

    words = [re.sub(r'[^a-zA-Z0-9]', '', w.lower()) for w in fact_clean.split()[:5]]
    slug = "-".join(w for w in words if w) or f"note-{int(time.time())}"
    title = fact_clean[:60].strip()
    desc = fact_clean[:140].strip()

    cmd = [
        "python3", str(wscript), "new", "preference", slug,
        "--title", title,
        "--description", desc,
        "--summary", fact_clean,
        "--force",
        "--root", str(wroot)
    ]
    try:
        subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, check=True)
        subprocess.run(["python3", str(wscript), "lint", "--write-index", "--root", str(wroot)], cwd=workspace, capture_output=True)
        subprocess.run(["python3", str(wscript), "log", f"Ingestion. Remembered {slug}", "--root", str(wroot)], cwd=workspace, capture_output=True)
        return f"Saved → [{slug}.md](wiki/preferences/{slug}.md)"
    except Exception as e:
        return f"Error saving to wiki: {e}"


def tool_local_wiki(args: dict, workspace: Path, mode: str = "act", session_context: dict | None = None) -> str:
    action = (args.get("action") or "").strip()
    if not action:
        return "Error: action required (search, read_page, new_page, lint, digest, init, env_list, log, backup, remember)"

    if mode == "plan" and action in ("new_page", "init", "log", "backup", "remember"):
        return f"Error: [PLAN MODE] Action '{action}' modifies the wiki and is disabled in Plan Mode. Use 'search' or 'read_page' to explore existing knowledge first."

    if action == "backup":
        msgs = (session_context or {}).get("messages")
        return perform_wiki_backup(workspace, messages=msgs, note=args.get("summary") or args.get("note") or "")

    if action == "remember":
        msgs = (session_context or {}).get("messages")
        fact_text = args.get("summary") or args.get("query") or args.get("fact") or ""
        return perform_wiki_remember(workspace, fact=fact_text, messages=msgs)

    if action == "lint":
        return perform_wiki_lint(workspace, auto_fix=True)

    wiki_script = find_wiki_script(workspace)
    if not wiki_script:
        return "Error: local-wiki script (wiki.py) not found on system."

    wiki_root = resolve_wiki_root(workspace)

    # If wiki is not active in this project folder:
    # 1. new_page automatically initializes the wiki first
    # 2. search/read_page/digest/lint/env_list report that the wiki is inactive and can be initialized with action='init'
    if not wiki_root and action == "new_page":
        target_root = (workspace / "wiki").resolve()
        init_cmd = ["python3", str(wiki_script), "init", "--root", str(target_root)]
        try:
            subprocess.run(init_cmd, cwd=workspace, capture_output=True, text=True, check=True)
            wiki_root = target_root
            if session_context is not None:
                messages = session_context.get("messages")
                if messages and len(messages) > 0 and messages[0].get("role") == "system":
                    messages[0]["content"] = build_dl_system_prompt(workspace, mode=mode)
                sync_current_chat_state(messages, workspace)
        except subprocess.CalledProcessError as e:
            return f"Error initializing Local Wiki in {target_root}: {e.stderr or e.stdout}"

    if not wiki_root and action in ("search", "read_page", "digest", "env_list"):
        return (f"Local Wiki is inactive in this workspace ({workspace}) because no wiki/ folder exists. "
                "Call local_wiki(action='init') to initialize one, or local_wiki(action='new_page', ...) to create the first page.")

    if action == "read_page":
        ppath_str = args.get("page_path") or args.get("query")
        if not ppath_str:
            return "Error: page_path required for read_page"
        p = Path(ppath_str).expanduser()
        if not p.is_absolute():
            if wiki_root and not str(p).startswith("wiki/"):
                p = wiki_root / p
            else:
                p = (workspace / p).resolve()
        if not p.is_file():
            if wiki_root and (wiki_root / ppath_str).is_file():
                p = wiki_root / ppath_str
            else:
                return f"Error: Wiki page not found: {ppath_str}"
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return f"Wiki Page: {p}\n\n{content}"
        except Exception as e:
            return f"Error reading wiki page {p}: {e}"

    cmd = ["python3", str(wiki_script)]
    cwd = workspace

    if action == "search":
        terms = (args.get("query") or args.get("terms") or "").strip()
        if not terms:
            return "Error: query required for search"
        cmd.extend(["search", terms])
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    elif action == "digest":
        cmd.append("digest")
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    elif action == "lint":
        cmd.append("lint")
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    elif action == "init":
        target = args.get("root") or args.get("project_folder") or (workspace / "wiki")
        cmd.extend(["init", "--root", str(Path(target).resolve())])

    elif action == "env_list":
        cmd.extend(["env", "list"])
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    elif action == "log":
        msg = (args.get("log_message") or args.get("query") or "").strip()
        if not msg:
            return "Error: log_message required for log"
        cmd.extend(["log", msg])
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    elif action == "new_page":
        ptype = args.get("page_type")
        slug = args.get("slug")
        title = args.get("title")
        desc = args.get("description")
        if not all([ptype, slug, title, desc]):
            return "Error: page_type, slug, title, and description are all required for new_page"
        cmd.extend(["new", ptype, slug, "--title", title, "--description", desc])
        if args.get("tags"):
            cmd.extend(["--tags", args["tags"]])
        if args.get("summary"):
            cmd.extend(["--summary", args["summary"]])
        cmd.append("--force")
        if wiki_root:
            cmd.extend(["--root", str(wiki_root)])

    else:
        return f"Error: Unknown wiki action '{action}'"

    try:
        res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=30)
        out = (res.stdout or "") + (f"\nStderr: {res.stderr}" if res.stderr else "")
        if action == "init" and res.returncode == 0:
            target_wiki = Path(target if 'target' in locals() else (workspace / "wiki")).resolve()
            if target_wiki.is_dir() and session_context is not None:
                messages = session_context.get("messages")
                if messages and len(messages) > 0 and messages[0].get("role") == "system":
                    messages[0]["content"] = build_dl_system_prompt(workspace, mode=mode)
                sync_current_chat_state(messages, workspace)
        return out.strip() or f"Action '{action}' completed."
    except Exception as e:
        return f"Error executing wiki command: {e}"
