#!/usr/bin/env python3
"""dl_cli.py - D.L. CLI Autonomous Engineering Agent powered by Strata Qwen3.8-Flash-Next Coder.

Equipped with D.L. AI identity, tool schemas:
- run_command
- view_file
- write_to_file
- replace_file_content
- exa_web_search (Exa AI Web Search API)
- resolve_library_id (Context7 Documentation MCP)
- get_library_docs (Context7 Documentation MCP)

Runs 100% locally on the Strata engine with live SSE streaming.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import difflib
import hashlib
import http.client
import json
import os
import re
import readline
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

if __name__ == "__main__":
    # run as a script: load the one real module, so the moved code and this file share their names
    import importlib
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(importlib.import_module("dl_cli").main() or 0)

# The code below was split into dl_*.py modules; every name is re-exported here, because the importers
# (dl_sessiond, dl_attach, serve/server.py, the benches, the tests) use `dl_cli.<name>`.
try:
    from .dl_common import (  # noqa: F401
        C_ACCENT,
        C_ACCENT_BOLD,
        C_ACCENT_SOFT,
        C_BLUE,
        C_BOLD,
        C_CYAN,
        C_DIM,
        C_GREEN,
        C_INK,
        C_INK_SOFT,
        C_LINE,
        C_MUTED,
        C_RED,
        C_RESET,
        C_YELLOW,
        DEFAULT_API_KEY,
        DEFAULT_CLIENT_IP_KEY,
        DEFAULT_CONTEXT7_KEY,
        DEFAULT_EXA_KEY,
        DEFAULT_URL,
        _note,
        _switch,
        classify_command,
        classify_write,
        dl_advisor,
        dl_effort,
        dl_mcp,
        dl_memory,
        format_health_card,
        get_system_health,
        load_env_file,
        memory_store,
        scan_secrets_in_text,
        tool_git_diff_audit,
        tool_scan_secrets,
        tool_smart_test_runner,
        tool_syntax_guard,
        validate_syntax,
    )
except ImportError:
    from dl_common import (  # noqa: F401
        C_ACCENT,
        C_ACCENT_BOLD,
        C_ACCENT_SOFT,
        C_BLUE,
        C_BOLD,
        C_CYAN,
        C_DIM,
        C_GREEN,
        C_INK,
        C_INK_SOFT,
        C_LINE,
        C_MUTED,
        C_RED,
        C_RESET,
        C_YELLOW,
        DEFAULT_API_KEY,
        DEFAULT_CLIENT_IP_KEY,
        DEFAULT_CONTEXT7_KEY,
        DEFAULT_EXA_KEY,
        DEFAULT_URL,
        _note,
        _switch,
        classify_command,
        classify_write,
        dl_advisor,
        dl_effort,
        dl_mcp,
        dl_memory,
        format_health_card,
        get_system_health,
        load_env_file,
        memory_store,
        scan_secrets_in_text,
        tool_git_diff_audit,
        tool_scan_secrets,
        tool_smart_test_runner,
        tool_syntax_guard,
        validate_syntax,
    )
try:
    from .dl_tools_schema import (  # noqa: F401
        DL_ACT_TOOLS,
        DL_PLAN_TOOLS,
        DL_TOOLS,
        find_wiki_script,
        get_active_tools,
        resolve_wiki_root,
        web_docs_tools_hint,
    )
except ImportError:
    from dl_tools_schema import (  # noqa: F401
        DL_ACT_TOOLS,
        DL_PLAN_TOOLS,
        DL_TOOLS,
        find_wiki_script,
        get_active_tools,
        resolve_wiki_root,
        web_docs_tools_hint,
    )
try:
    from .dl_media import (  # noqa: F401
        ATTACHED_IMAGE_LABEL,
        AUDIO_EXTENSIONS,
        BINARY_EXTENSIONS,
        IMAGE_EXTENSIONS,
        IMAGE_MARKER,
        IMAGE_RESULT_TOOLS,
        MEDIA_CACHE_DIR,
        PDF_EXTENSIONS,
        SENSITIVE_DIRS,
        SENSITIVE_EXTENSIONS,
        SENSITIVE_FILE_NAMES,
        VIDEO_EXTENSIONS,
        _render_pdf_pages,
        _sample_video_frames,
        _transcribe_audio_file,
        build_user_message_content,
        is_sensitive_file,
        resolve_file_references,
        resolve_prompt_and_images,
        tool_result_images,
    )
except ImportError:
    from dl_media import (  # noqa: F401
        ATTACHED_IMAGE_LABEL,
        AUDIO_EXTENSIONS,
        BINARY_EXTENSIONS,
        IMAGE_EXTENSIONS,
        IMAGE_MARKER,
        IMAGE_RESULT_TOOLS,
        MEDIA_CACHE_DIR,
        PDF_EXTENSIONS,
        SENSITIVE_DIRS,
        SENSITIVE_EXTENSIONS,
        SENSITIVE_FILE_NAMES,
        VIDEO_EXTENSIONS,
        _render_pdf_pages,
        _sample_video_frames,
        _transcribe_audio_file,
        build_user_message_content,
        is_sensitive_file,
        resolve_file_references,
        resolve_prompt_and_images,
        tool_result_images,
    )
try:
    from .dl_checkpoints import (  # noqa: F401
        CHECKPOINT_DIR,
        CHECKPOINT_MAX_FILE,
        CHECKPOINT_MAX_FILES,
        Checkpoints,
        SCAN_SKIP,
        SHRINK_MIN,
        SHRINK_NOTE,
        WRITE_TOOLS,
        scan_workspace,
        shrink_note,
        shrunk_files,
    )
except ImportError:
    from dl_checkpoints import (  # noqa: F401
        CHECKPOINT_DIR,
        CHECKPOINT_MAX_FILE,
        CHECKPOINT_MAX_FILES,
        Checkpoints,
        SCAN_SKIP,
        SHRINK_MIN,
        SHRINK_NOTE,
        WRITE_TOOLS,
        scan_workspace,
        shrink_note,
        shrunk_files,
    )
try:
    from .dl_tools_impl import (  # noqa: F401
        _exa,
        _note_new_listeners,
        call_context7_mcp_raw,
        dl_proton,
        dl_schedule,
        dl_translate,
        stand_in_error,
        tool_context7_docs,
        tool_context7_resolve,
        tool_exa_web_search,
        tool_replace_file_content,
        tool_run_command,
        tool_switch_workspace,
        tool_view_file,
        tool_write_to_file,
    )
except ImportError:
    from dl_tools_impl import (  # noqa: F401
        _exa,
        _note_new_listeners,
        call_context7_mcp_raw,
        dl_proton,
        dl_schedule,
        dl_translate,
        stand_in_error,
        tool_context7_docs,
        tool_context7_resolve,
        tool_exa_web_search,
        tool_replace_file_content,
        tool_run_command,
        tool_switch_workspace,
        tool_view_file,
        tool_write_to_file,
    )
try:
    from .dl_wiki_legacy import (  # noqa: F401
        perform_wiki_backup,
        perform_wiki_lint,
        perform_wiki_remember,
        tool_local_wiki,
    )
except ImportError:
    from dl_wiki_legacy import (  # noqa: F401
        perform_wiki_backup,
        perform_wiki_lint,
        perform_wiki_remember,
        tool_local_wiki,
    )
try:
    from .dl_memory_tools import (  # noqa: F401
        MEMORY_SLASH,
        memory_backup,
        memory_slash,
        tool_clear_conversation,
        tool_get_engine_status,
        tool_get_system_health,
        tool_memory,
        tool_save_chat,
    )
except ImportError:
    from dl_memory_tools import (  # noqa: F401
        MEMORY_SLASH,
        memory_backup,
        memory_slash,
        tool_clear_conversation,
        tool_get_engine_status,
        tool_get_system_health,
        tool_memory,
        tool_save_chat,
    )
try:
    from .dl_boundary import (  # noqa: F401
        ASKS_FOR_GIT,
        ASKS_FOR_GLOBAL,
        ASKS_TO_EDIT,
        ASKS_TO_OPEN,
        ATTACHED_PICTURE,
        DESKTOP_OPENER,
        DETACHES,
        GIT_COMMAND,
        JJ_COMMAND,
        KEEP_RUNNING,
        REF_WORD,
        _CMD_WORD,
        _inside,
        _listeners,
        agent_boundary,
        approval_reason,
        asked_text,
        attached_pictures,
        memory_global_change,
        picture_refusal,
        stop_left_listeners,
        terminal_approve,
        words_of,
    )
except ImportError:
    from dl_boundary import (  # noqa: F401
        ASKS_FOR_GIT,
        ASKS_FOR_GLOBAL,
        ASKS_TO_EDIT,
        ASKS_TO_OPEN,
        ATTACHED_PICTURE,
        DESKTOP_OPENER,
        DETACHES,
        GIT_COMMAND,
        JJ_COMMAND,
        KEEP_RUNNING,
        REF_WORD,
        _CMD_WORD,
        _inside,
        _listeners,
        agent_boundary,
        approval_reason,
        asked_text,
        attached_pictures,
        memory_global_change,
        picture_refusal,
        stop_left_listeners,
        terminal_approve,
        words_of,
    )
try:
    from .dl_status import (  # noqa: F401
        STALL_LOG,
        chat_settings_summary,
        check_status,
        format_messages_to_markdown,
        stall_summary,
        sync_current_chat_state,
    )
except ImportError:
    from dl_status import (  # noqa: F401
        STALL_LOG,
        chat_settings_summary,
        check_status,
        format_messages_to_markdown,
        stall_summary,
        sync_current_chat_state,
    )
try:
    from .dl_engine import (  # noqa: F401
        LOOP_CHECK_EVERY,
        LOOP_RULES,
        READING_SHOW_S,
        READING_SLOW_S,
        _ConnHTTPHandler,
        _ConnHTTPSHandler,
        _SENTENCE,
        _cut_on_cancel,
        _keep_socket,
        format_args_preview,
        stream_chat_turn,
        thinking_loops,
    )
except ImportError:
    from dl_engine import (  # noqa: F401
        LOOP_CHECK_EVERY,
        LOOP_RULES,
        READING_SHOW_S,
        READING_SLOW_S,
        _ConnHTTPHandler,
        _ConnHTTPSHandler,
        _SENTENCE,
        _cut_on_cancel,
        _keep_socket,
        format_args_preview,
        stream_chat_turn,
        thinking_loops,
    )
try:
    from .dl_context import (  # noqa: F401
        BIG_ARGS,
        BROWSER_LIVE_NOTE,
        BROWSER_NOTE,
        CHARS_PER_TOKEN,
        CONTEXT_RESERVE,
        DONE_NOTE,
        DROPPED,
        ELIDED,
        EVIDENCE_NOTE,
        HANDOFF_MIN_REPLY_ROOM,
        HANDOFF_NOTE,
        PROTECT_SHARE,
        REVIEW_NOTE,
        STAND_IN,
        TOOL_RESULT_MAX,
        _HANDOFF_RE,
        _ctx_cache,
        _degraded_told,
        _msg_chars,
        _shrink,
        _units,
        cap_tool_result,
        compact_history,
        context_window,
        current_check_note,
        degraded_notice,
        estimate_prompt_tokens,
        fit_context,
        is_cli_note,
        protected_user_messages,
    )
except ImportError:
    from dl_context import (  # noqa: F401
        BIG_ARGS,
        BROWSER_LIVE_NOTE,
        BROWSER_NOTE,
        CHARS_PER_TOKEN,
        CONTEXT_RESERVE,
        DONE_NOTE,
        DROPPED,
        ELIDED,
        EVIDENCE_NOTE,
        HANDOFF_MIN_REPLY_ROOM,
        HANDOFF_NOTE,
        PROTECT_SHARE,
        REVIEW_NOTE,
        STAND_IN,
        TOOL_RESULT_MAX,
        _HANDOFF_RE,
        _ctx_cache,
        _degraded_told,
        _msg_chars,
        _shrink,
        _units,
        cap_tool_result,
        compact_history,
        context_window,
        current_check_note,
        degraded_notice,
        estimate_prompt_tokens,
        fit_context,
        is_cli_note,
        protected_user_messages,
    )
try:
    from .dl_handoff import (  # noqa: F401
        HANDOFF_MAX_CHARS,
        HANDOFF_MIN_GROWTH,
        HANDOFF_SYSTEM,
        IN_SESSION_HANDOFF_PROMPT,
        WIKI_SECRETS_PATTERNS,
        _extract_dead_ends,
        _fallback_handoff_diary,
        _normalize_handoff_diary,
        _prior_handoff,
        generate_handoff_diary,
        handoff_session,
        in_session_handoff_diary,
        redact_secrets,
        save_handoff_diary,
    )
except ImportError:
    from dl_handoff import (  # noqa: F401
        HANDOFF_MAX_CHARS,
        HANDOFF_MIN_GROWTH,
        HANDOFF_SYSTEM,
        IN_SESSION_HANDOFF_PROMPT,
        WIKI_SECRETS_PATTERNS,
        _extract_dead_ends,
        _fallback_handoff_diary,
        _normalize_handoff_diary,
        _prior_handoff,
        generate_handoff_diary,
        handoff_session,
        in_session_handoff_diary,
        redact_secrets,
        save_handoff_diary,
    )
try:
    from .dl_finish import (  # noqa: F401
        BROWSER_JS,
        CHECK_CMD,
        CLAIM_WORDS,
        DONE_STALL_LIMIT,
        PLAYWRIGHT_CORE,
        REVIEWER_SYSTEM,
        REVIEW_DIFF_MAX,
        REVIEW_EFFORT,
        RequestChanges,
        WEB_SUFFIXES,
        _final_review,
        _latest_task,
        _user_message_text,
        browser_errors,
        browser_nudge,
        changed_pages,
        final_review_files,
        finish_checks,
        request_actions,
        review_changes,
        web_pages,
        workspace_snapshot,
    )
except ImportError:
    from dl_finish import (  # noqa: F401
        BROWSER_JS,
        CHECK_CMD,
        CLAIM_WORDS,
        DONE_STALL_LIMIT,
        PLAYWRIGHT_CORE,
        REVIEWER_SYSTEM,
        REVIEW_DIFF_MAX,
        REVIEW_EFFORT,
        RequestChanges,
        WEB_SUFFIXES,
        _final_review,
        _latest_task,
        _user_message_text,
        browser_errors,
        browser_nudge,
        changed_pages,
        final_review_files,
        finish_checks,
        request_actions,
        review_changes,
        web_pages,
        workspace_snapshot,
    )
try:
    from .dl_prompt import (  # noqa: F401
        BLOCKED_LINE,
        DONE_ITEM,
        HR_DAYS,
        MEMORY_CAPS,
        NOW_PREFIX,
        OPEN_ITEM,
        PLAN_FILE,
        PROFILE_PATH,
        PROGRESS_HEAD,
        RAY_ABOUT,
        VOICE_NOTE,
        VOICE_PREAMBLE,
        _imports_only,
        _read_text,
        _wiki_titles,
        build_dl_system_prompt,
        device_of,
        mcp_prompt_section,
        now_line,
        persona_text,
        plan_progress,
        profile_prompt_section,
        project_memory,
        save_approved_plan,
        user_profile,
        voice_note,
        with_now,
    )
except ImportError:
    from dl_prompt import (  # noqa: F401
        BLOCKED_LINE,
        DONE_ITEM,
        HR_DAYS,
        MEMORY_CAPS,
        NOW_PREFIX,
        OPEN_ITEM,
        PLAN_FILE,
        PROFILE_PATH,
        PROGRESS_HEAD,
        RAY_ABOUT,
        VOICE_NOTE,
        VOICE_PREAMBLE,
        _imports_only,
        _read_text,
        _wiki_titles,
        build_dl_system_prompt,
        device_of,
        mcp_prompt_section,
        now_line,
        persona_text,
        plan_progress,
        profile_prompt_section,
        project_memory,
        save_approved_plan,
        user_profile,
        voice_note,
        with_now,
    )
try:
    from .dl_repl import (  # noqa: F401
        interactive_loop,
        print_banner,
    )
except ImportError:
    from dl_repl import (  # noqa: F401
        interactive_loop,
        print_banner,
    )


def dispatch_dl_tool(name: str, args: dict, workspace: Path, mode: str = "act", session_context: dict | None = None) -> str:
    if mode == "plan" and name in ("write_to_file", "replace_file_content"):
        return "Error: [PLAN MODE] File modifications are disabled. Research the codebase and present your implementation plan for approval before executing."
    refused = agent_boundary(name, args, workspace, session_context)
    if refused:
        return refused
    gated = approval_reason(name, args, workspace)
    if gated and not (session_context or {}).get("yolo"):
        approve = (session_context or {}).get("approve") or terminal_approve
        if not approve("tool", gated[0], gated[1]):
            return f"Denied by user: {gated[1]}. Do not retry it; ask the user or choose a non-destructive approach."
    registry = (session_context or {}).get("mcp")
    if registry is not None and registry.active:
        if name == "mcp":
            return registry.handle_meta(args)
        if not registry.owns(name):
            registry.revive(name)                    # its server went idle: start it again rather than "unknown"
        if registry.owns(name):
            blocked = registry.leak(args)            # a credential in an email/file/URL: refused before any card
            if blocked:
                return blocked
            if "user_text" in (session_context or {}):  # an agent turn (not a scheduled job or the user's own call)
                refused = registry.words_refusal(name, args, asked_text(session_context))
                if refused:
                    return refused
            ask = registry.approval(name, args)
            # YOLO is fully autonomous (the user's choice, 2026-10-15): nothing asks, sending email included
            if ask and not (session_context or {}).get("yolo"):
                approve = (session_context or {}).get("approve") or terminal_approve
                if not approve("mcp-always" if ask[2] else "tool", ask[0], ask[1]):
                    return f"Denied by user: {name}. Do not retry it; ask the user what to do instead."
            return registry.call(name, args, mode=mode, cancel=(session_context or {}).get("cancel"))
    if name == "switch_workspace":
        return tool_switch_workspace(args, workspace, session_context=session_context)
    elif name == "view_file":
        return tool_view_file(args, workspace)
    elif name == "write_to_file":
        return tool_write_to_file(args, workspace)
    elif name == "replace_file_content":
        return tool_replace_file_content(args, workspace)
    elif name == "run_command":
        # an agent turn's detached command: what it leaves listening on a port is stopped at the end of the request
        bg = (session_context or {}).get("bg_listeners") if "user_text" in (session_context or {}) else None
        if bg is None or not DETACHES.search(str(args.get("CommandLine") or args.get("command") or "")):
            return tool_run_command(args, workspace)
        before, t0 = _listeners(), time.time()
        try:
            return tool_run_command(args, workspace)
        finally:
            _note_new_listeners(bg, before, t0)
    elif name == "exa_web_search":
        return tool_exa_web_search(args)
    elif name == "resolve_library_id":
        return tool_context7_resolve(args)
    elif name == "get_library_docs":
        return tool_context7_docs(args)
    elif name in ("memory", "local_wiki"):
        out = tool_memory(args, workspace, mode=mode, session_context=session_context, approved=bool(gated))
        if gated and (session_context or {}).get("yolo") and not str(out).startswith(("Error", "Refused")):
            out += ("\n(No approval card was shown: YOLO is on. Do not tell the user they approved this; say it was "
                    "saved without asking because YOLO is on.)")
        return out
    elif name == "syntax_guard":
        return tool_syntax_guard(args, workspace)
    elif name == "scan_secrets":
        return tool_scan_secrets(args, workspace)
    elif name in ("get_system_health", "system_health"):
        return tool_get_system_health(args, workspace)
    elif name in ("get_engine_status", "engine_status"):
        return tool_get_engine_status(args, workspace)
    elif name in ("save_chat", "export_chat"):
        return tool_save_chat(args, workspace, session_context=session_context)
    elif name in ("clear_conversation", "reset_conversation"):
        return tool_clear_conversation(args, workspace, session_context=session_context)
    elif name == "git_diff_audit":
        return tool_git_diff_audit(args, workspace)
    elif name == "smart_test_runner":
        return tool_smart_test_runner(args, workspace)
    else:
        return unknown_tool(name, args, workspace, mode, session_context)


# names models use for the built-in tools: write_file was called instead of write_to_file in the 2026-10-29 roman run
TOOL_ALIASES = {"write_file": "write_to_file", "create_file": "write_to_file", "read_file": "view_file",
                "open_file": "view_file", "edit_file": "replace_file_content", "bash": "run_command",
                "shell": "run_command", "execute_command": "run_command", "run_shell_command": "run_command"}


def unknown_tool(name: str, args: dict, workspace: Path, mode: str, session_context: dict | None) -> str:
    """A tool name the agent made up.  A plain typo of one real tool (replace_file_ontent) or a known alias
    (write_file) runs that tool and says so; anything else gets the closest names and the full list, so the next try
    is right."""
    import difflib
    tools = get_active_tools(workspace, mode=mode, registry=(session_context or {}).get("mcp"))
    names = [t["function"]["name"] for t in tools]
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.6)
    typo = [TOOL_ALIASES[name]] if TOOL_ALIASES.get(name) in names else difflib.get_close_matches(name, names, n=2, cutoff=0.88)
    if len(typo) == 1 and not (set(args or {}) - set(
            next(t for t in tools if t["function"]["name"] == typo[0])["function"]["parameters"].get("properties", {}))):
        out = dispatch_dl_tool(typo[0], args, workspace, mode=mode, session_context=session_context)
        return f"[{name!r} is not a tool; ran {typo[0]!r}]\n{out}"
    hint = f" Did you mean {' or '.join(repr(c) for c in close)}?" if close else ""
    return f"Error: Unknown tool {name}.{hint} Tools you have: {', '.join(names)}"


TRANSIENT_ENGINE_ERR = re.compile(
    r"the next request restarts it|engine stopped unexpectedly|said nothing for|"
    r"Connection refused|RemoteDisconnected|Remote end closed connection|Connection reset|EOF occurred|"
    r"Strata API HTTP 50[234]",
    re.IGNORECASE,
)


ENGINE_RETRIES = 2


ENGINE_RETRY_WAIT_S = float(os.environ.get("DL_ENGINE_RETRY_WAIT_S") or 2.0)


def chat_turn_in_context(messages: list[dict], url: str, api_key: str, tools: list[dict], emit=None, cancel=None,
                         measured: tuple[int, int] | None = None, effort: str | None = None,
                         budget: int = 0, on_compact=None, workspace: Path | None = None,
                         plan_file: Path | str | None = None, on_handoff=None) -> dict:
    """stream_chat_turn after fit_context; if Strata still refuses the prompt as too long, compact/handoff to what it
    reported and try once more.  If the engine stops mid-stream or is restarting, wait briefly and retry so the agent
    does not silently stop mid-work or leave the model unloaded."""
    if fit_context(messages, tools, url, api_key, emit=emit, measured=measured,
                   workspace=workspace, plan_file=plan_file, cancel=cancel, on_handoff=on_handoff) and on_compact:
        on_compact(messages)
    tries = 0
    while True:
        try:
            return stream_chat_turn(messages=messages, url=url, api_key=api_key, tools=tools, emit=emit, cancel=cancel,
                                    effort=effort, budget=budget)
        except RuntimeError as e:
            m = re.search(r"exceeds the context window: prompt \((\d+) tokens\)", str(e))
            if m:
                if fit_context(messages, tools, url, api_key, emit=emit, over=int(m.group(1)),
                               workspace=workspace, plan_file=plan_file, cancel=cancel,
                               on_handoff=on_handoff) and on_compact:
                    on_compact(messages)
                return stream_chat_turn(messages=messages, url=url, api_key=api_key, tools=tools, emit=emit,
                                        cancel=cancel, effort=effort, budget=budget)
            if (tries < ENGINE_RETRIES and (cancel is None or not cancel.is_set())
                    and TRANSIENT_ENGINE_ERR.search(str(e))):
                tries += 1
                note = (f"Engine interrupted mid-turn ({e}); waiting for reload and retrying "
                        f"({tries}/{ENGINE_RETRIES})...")
                if emit:
                    emit({"type": "notice", "level": "warn", "text": note})
                else:
                    print(f"\n{C_YELLOW}{note}{C_RESET}")
                wait_s = float(os.environ.get("DL_ENGINE_RETRY_WAIT_S") or ENGINE_RETRY_WAIT_S)
                if wait_s > 0:
                    time.sleep(wait_s)
                continue
            raise


LOOP_RETRIES = 3                    # per request


LOOP_NOTE = ("[D.L. CLI] Your thinking went round in circles (it kept repeating: \"{sentence}\"), so D.L. CLI stopped "
             "it. Decide now with what you already know: make the next tool call, or answer. Keep your thinking short.")


TEXT_TOOL_CALL = re.compile(r"<tool_call>|<function=[\w-]*|<parameter=[\w-]*>")


TEXT_CALL_RETRIES = 2                       # per request: a model that keeps doing it is not looped forever


TEXT_CALL_NOTE = ("[D.L. CLI] Your last reply contains a tool call written as text (<tool_call>, <function=...>), "
                  "which cannot be run, so nothing was executed. Send it again as a real tool call with all its "
                  "parameters, one call at a time.")


TEXT_CALL_NAME = re.compile(r"<function=([\w-]+)|<invoke name=\"([\w-]+)\"")


TEXT_CALL_REVIVED = (" That tool's server ({server}) had been turned off while it was idle, so the tool was missing "
                     "from your list; it is on again now, so the real call will work.")


# Edit-first watchdog (2026-11-14: a 25-line fix took 2 h, most of it reading and building test tools in /tmp):
# coding work in Act mode that goes DL_NUDGE_AT rounds without changing a workspace file gets a note; DL_PATCH_AT
# rounds gets DeepSeek's patch (the helper on) or a sterner note.  0 turns it off.
NUDGE_AT = int(os.environ.get("DL_NUDGE_AT") or 12)


PATCH_AT = int(os.environ.get("DL_PATCH_AT") or 18)


PATCH_RECENT = 6                            # the patch needs a failure among this many latest tool results


CODING_REASONS = ("coding task", "code or error", "follow-up on a failed answer")


NUDGE_NOTE = ("[D.L. CLI] {n} rounds without changing a project file. Stop reading and building test tools: make the "
              "edit now with replace_file_content (or write_to_file), then test it.")


NUDGE_NOTE_2 = ("[D.L. CLI] {n} rounds and still no project file changed. Make the change you already know is needed "
                "in your next call; do not read, fetch or write helper scripts first.")


# Test, probe and scratch files do not count as a changed project file (the user's choice, 2026-11-15): the first
# Tetris run spent 30 minutes repairing tetris.test.js while tetris.html stayed untouched.  The plan does count: a
# ticked line is progress (leaving it out, the 09:35 live run was nudged and patched while it verified and ticked).
SCRATCH_FILE = re.compile(r"(^|/)([^/]*\.(test|spec)\.[^/]+|test_[^/]*|[^/]*_test\.[^/]+|"
                          r"(probe|scratch|tmp|temp)(?![a-z])[^/]*|(tests?|__tests__|scratch|tmp|uploads|phone-photos|phone-files)/.*)$",
                          re.I)       # uploads/, phone-*: chat attachments and the phone's pictures, not project work


def project_change(names, ws: Path | None = None) -> bool:
    """Whether any of the changed files is a project file: inside the workspace, and not a test, probe or scratch
    file.  Paths are relative to the workspace, or absolute (from a tool call's arguments)."""
    root = Path(ws).resolve() if ws is not None else None
    for n in names:
        p = Path(str(n))
        if p.is_absolute() and root is not None:
            try:
                p = p.resolve().relative_to(root)
            except (ValueError, OSError):
                continue                            # written outside the workspace (/tmp): not a project file
        if not SCRATCH_FILE.search(str(p).replace(os.sep, "/")):
            return True
    return False


def _written_files(tool_calls) -> list[str]:
    """The files this round's write_to_file / replace_file_content calls name."""
    out = []
    for tc in tool_calls or []:
        fn = tc.get("function") or {}
        if fn.get("name") not in ("write_to_file", "replace_file_content"):
            continue
        a = fn.get("arguments")
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except ValueError:
                a = {}
        a = a if isinstance(a, dict) else {}
        out.append(str(a.get("TargetFile") or a.get("path") or a.get("AbsolutePath") or "?"))
    return out


# Lean thinking (the user's choice, 2026-11-14): auto effort on coding work thinks on high in the first round and
# for LEAN_HIGH_ROUNDS rounds after a failure, and on medium in the rounds that only act on what it already knows.
LEAN_HIGH_ROUNDS = int(os.environ.get("DL_LEAN_HIGH_ROUNDS") or 2)


READ_RESULT_MAX = int(os.environ.get("DL_READ_RESULT_MAX") or 8000)     # one view_file / run_command result


READ_TOOLS = ("view_file", "run_command")


MAX_TURNS = int(os.environ.get("DL_MAX_TURNS") or 40)   # model calls per request before the agent must stop


CONTINUE_PROMPT = "Continue the task from where you stopped."


SMALL_TALK_NOTE = "Small talk: no tool is needed here, and none was run. Answer directly, as yourself."


TURN_CAP_NOTE = ("[D.L. CLI] You have used all {n} tool rounds for this request, so tools are off now. Do not call "
                 "a tool. In one short paragraph tell the user what is done, what is not done yet, and what you "
                 "would do next. The user can type /continue to let you go on.")


def turn_cap_wrap_up(messages: list[dict], url: str, api_key: str, tools: list[dict], limit: int,
                     emit=None, cancel=None, effort: str | None = None, budget: int = 0) -> str:
    """The loop hit its cap: one last call, asked for a status instead of a tool call, so the turn never ends
    silently on a tool result.  The tools stay in the request (same prompt prefix, so the cache still hits); a tool
    call in the reply is not run."""
    messages.append({"role": "user", "content": TURN_CAP_NOTE.format(n=limit)})
    try:
        res = chat_turn_in_context(messages, url, api_key, tools, emit=emit, cancel=cancel, effort=effort, budget=budget)
        text = (res.get("content") or "").strip()
    except RuntimeError:
        res, text = {}, ""
    if not text:
        text = f"I stopped after {limit} tool rounds before finishing. Type /continue to let me go on."
        if emit:
            emit({"type": "text", "text": text})
        else:
            print(text)
    msg = {"role": "assistant", "content": text}
    if res.get("reasoning"):
        msg["reasoning_content"] = res["reasoning"]
    messages.append(msg)
    note = f"Stopped after {limit} tool rounds (DL_MAX_TURNS). Type /continue to go on."
    if emit:
        emit({"type": "notice", "level": "warn", "text": note})
    else:
        print(f"\n{C_YELLOW}{note}{C_RESET}\n")
    return text


def execute_agent_loop(messages: list[dict], url: str, api_key: str,
                       workspace: Path, max_turns: int | None = None,
                       mode: str = "act", session_context: dict | None = None) -> Path:
    max_turns = max_turns or MAX_TURNS
    turn = 0
    total_tokens = 0
    t_start = time.time()
    current_ws = workspace
    emit = (session_context or {}).get("emit")
    cancel = (session_context or {}).get("cancel")
    effort = (session_context or {}).get("effort")
    effort_auto = bool((session_context or {}).get("effort_auto"))
    budget = int((session_context or {}).get("reasoning_budget_tokens") or 0)
    seen: set[tuple[str, str]] = set()

    advisor = dl_advisor.Advisor(session_context) if dl_advisor is not None and dl_advisor.enabled() else None

    sc = session_context or {}
    kind = sc.get("effort_reason")
    if (kind is None or str(kind).startswith("model2vec ")) and dl_effort is not None and sc.get("user_text"):
        try:
            kind = dl_effort.pick(str(sc["user_text"]), mode=mode, semantic=False)[1]
        except Exception:  # noqa: BLE001 - the watchdog is a helper; a classifier error must not stop the request
            pass
    coding = mode == "act" and (kind in CODING_REASONS or bool(sc.get("plan_file")))
    lean = (effort_auto and coding and effort == "high" and dl_effort is not None
            and os.environ.get("DL_LEAN_THINKING", "1") != "0")
    high_left = 1                           # lean: rounds left on high (the first one plans)
    quiet = 0                               # watchdog: rounds in a row without a changed workspace file
    nudged = 0
    recent_fail: list[bool] = []            # the last PATCH_RECENT tool results: did each one fail?
    fail_seen: set[tuple[str, str]] = set()

    def _auto_raise(reason: str | None, noted: bool = False) -> None:
        nonlocal effort, budget, high_left
        if advisor is not None and not noted:
            advisor.note_raise(reason)
        if reason and session_context is not None:
            session_context["raised"] = True          # the helper waits for this rung first
        if lean and reason:
            if high_left <= 0:
                _note(emit, f"Thinking on high for the next {LEAN_HIGH_ROUNDS} rounds, because "
                            f"{dl_effort.RAISE_WHY.get(reason, reason)}.")
            high_left = max(high_left, LEAN_HIGH_ROUNDS)
            return
        if effort_auto and reason and effort != "high":
            effort = "high"
            budget = dl_effort.budget_for("high") if dl_effort is not None else 4096
            if session_context is not None:
                session_context["effort"] = "high"
                session_context["reasoning_budget_tokens"] = budget
            _note(emit, dl_effort.describe_raise(reason) if dl_effort is not None else f"Thinking raised to high ({reason}).")

    degraded_notice(url, api_key, emit)
    if session_context is not None and "user_text" in session_context:
        session_context["bg_listeners"] = []      # what detached commands leave listening; stopped at the end
    registry = (session_context or {}).get("mcp")
    if registry is not None and registry.active:
        registry.route((session_context or {}).get("user_text") or "")
    active_tools = get_active_tools(current_ws, mode=mode, registry=registry)
    # small talk ("hello Ray", "introduce yourself"): a tool call is answered, not run.  Introductions turned on
    # ray_identity or called get_engine_status, get_system_health or local_wiki in 6-7 of 10 bench runs whatever the
    # persona said, and a server turned on changes the tool list, so the whole prompt is read again (2026-10-29).
    # The tools stay in the request (tool_choice "none" would drop them and break the cached prefix the same way).
    small_talk = (dl_effort is not None and os.environ.get("DL_SMALLTALK_GUARD", "1") != "0"
                  and dl_effort.is_small_talk((session_context or {}).get("user_text") or "",
                                              voice=bool((session_context or {}).get("voice")),
                                              last_reply=next((m.get("content") or "" for m in reversed(messages)
                                                               if m.get("role") == "assistant"
                                                               and isinstance(m.get("content"), str)), "")))

    def refresh_memory(msgs: list[dict]) -> None:
        # the start of a request and right after a trim: the only moments the prompt prefix may change
        if msgs and msgs[0].get("role") == "system":
            msgs[0] = {"role": "system", "content": build_dl_system_prompt(
                current_ws, mode=mode, plan_file=(session_context or {}).get("plan_file"))}

    refresh_memory(messages)
    finish = {"changes": RequestChanges(current_ws), "pages": web_pages(current_ws),   # one request's check state
              "from_plan": (session_context or {}).get("plan_file")}
    # on in the daemon and the CLI (their main() sets DL_CHECKPOINTS=1 unless it is set), not in tests that import this
    cps = Checkpoints(current_ws, emit) if os.environ.get("DL_CHECKPOINTS") == "1" else None
    if cps is not None:
        cps.take("request start")
        finish["cps"], finish["cp_start"] = cps, cps.head     # the reviewer's diff: everything since this point
    alarm = os.environ.get("DL_SHRINK_ALARM", "1") != "0"
    measured = None                         # (messages in the last request, its prompt tokens)
    text_call_retries = 0
    loop_retries = 0
    total_rounds = 0                        # model calls in this request, across YOLO's auto-continues

    def yolo_rollover() -> None:
        # YOLO: a stretch that reached the cap starts a new one instead of ending the request.  Every path that goes
        # on to the next round calls this; on 2026-10-20 a text tool call on round 40 skipped it and ended a CONTRA
        # run.  A new stretch also gets fresh text-call and loop-guard retries.
        nonlocal turn, text_call_retries, loop_retries
        if turn < max_turns or not (session_context or {}).get("yolo") or (cancel is not None and cancel.is_set()):
            return
        turn = text_call_retries = loop_retries = 0
        note = (f"⚡ [YOLO] {total_rounds} tool rounds so far in this request ({max_turns} per stretch, "
                f"DL_MAX_TURNS). Auto-continuing...")
        if emit:
            emit({"type": "notice", "level": "info", "text": note})
        else:
            print(f"\n{C_ACCENT}{note}{C_RESET}\n")
        nudge = browser_nudge(finish, current_ws, emit)     # a long run gets the real browser's errors too
        if nudge:
            if messages and messages[-1].get("role") == "user":
                c = messages[-1].get("content")
                if isinstance(c, list):
                    for part in c:
                        if isinstance(part, dict) and part.get("type") == "text":
                            part["text"] = f"{part.get('text', '')}\n\n{nudge}"
                            break
                    else:
                        c.append({"type": "text", "text": nudge})
                else:
                    messages[-1]["content"] = f"{messages[-1].get('content', '')}\n\n{nudge}"
            else:
                messages.append({"role": "user", "content": nudge})

    def poll_queued() -> bool:
        # User input sent while the session was busy: pick it up right after a tool round finishes (or before finish
        # checks) so the next model call sees it without losing the cached prompt prefix.
        nonlocal effort, effort_auto, budget, active_tools, small_talk, turn, text_call_retries, loop_retries, high_left
        take = (session_context or {}).get("take_queued")
        if not take or (cancel is not None and cancel.is_set()):
            return False
        picked = take(current_ws, effort)
        if not picked:
            return False
        effort = (session_context or {}).get("effort", effort)
        effort_auto = bool((session_context or {}).get("effort_auto", effort_auto))
        budget = int((session_context or {}).get("reasoning_budget_tokens") or 0)
        active_tools = get_active_tools(current_ws, mode=mode, registry=registry)
        if picked.get("prompts"):
            small_talk = False
            turn = text_call_retries = loop_retries = 0
            if lean:
                high_left = max(high_left, 1)
            for k in ("browser", "evidence", "review", "stalls"):
                finish.pop(k, None)
            return True
        return False

    while turn < max_turns:
        turn += 1
        total_rounds += 1
        if lean:                                # high to plan (and after a failure), medium to act
            effort = "high" if high_left > 0 else "medium"
            high_left = max(0, high_left - 1)
            budget = dl_effort.budget_for(effort)
            if session_context is not None:
                session_context["effort"], session_context["reasoning_budget_tokens"] = effort, budget
        res = chat_turn_in_context(messages, url, api_key, active_tools, emit=emit, cancel=cancel,
                                   measured=measured, effort=effort, budget=budget, on_compact=refresh_memory,
                                   workspace=current_ws, plan_file=(session_context or {}).get("plan_file"),
                                   on_handoff=(session_context or {}).get("on_handoff"))
        if res.get("prompt_tokens"):           # messages is now exactly what was sent (after any compaction)
            measured = (len(messages), res["prompt_tokens"])
        total_tokens += res["tokens"]

        # Append assistant turn
        asst_msg = {"role": "assistant"}
        if res["content"] is not None:
            asst_msg["content"] = res["content"]
        if res["reasoning"]:
            asst_msg["reasoning_content"] = res["reasoning"]
        if res["tool_calls"]:
            asst_msg["tool_calls"] = res["tool_calls"]
        messages.append(asst_msg)

        # The thinking went round in circles: drop it (it is only noise) and ask for the next action instead.
        if res["finish_reason"] == "loop" and loop_retries < LOOP_RETRIES:
            loop_retries += 1
            messages.pop()
            messages.append({"role": "user", "content": LOOP_NOTE.format(sentence=(res.get("loop_sentence") or "")[:200])})
            _note(emit, f"Loop guard: the thinking kept repeating itself; stopped it and asked for the next action "
                        f"({loop_retries}/{LOOP_RETRIES}).", "warn")
            _auto_raise("thinking loop")
            yolo_rollover()
            continue

        if res["finish_reason"] == "cancelled":
            if emit:
                emit({"type": "notice", "level": "warn", "text": "Interrupted."})
            else:
                print(f"{C_YELLOW}Interrupted.{C_RESET}\n")
            break

        # A tool call the model wrote out as text (<tool_call><function=...>) that the server could not parse:
        # without this the reply looks final and the turn ends with nothing run.  Say so and let it resend.
        if (not res["tool_calls"] and text_call_retries < TEXT_CALL_RETRIES
                and TEXT_TOOL_CALL.search(res["content"] or "")):
            text_call_retries += 1
            # often the tool's server was turned off (idle) and its tools left the list, so the model had no real
            # call to make (Playwright, 2026-11-14 16:03): turn it back on before asking for the call again
            revived = ""
            for named in (a or b for a, b in TEXT_CALL_NAME.findall(res["content"] or "")):
                if registry is not None and registry.active and not registry.owns(named) and registry.revive(named):
                    revived = named.split("__", 1)[0]
                    active_tools = get_active_tools(current_ws, mode=mode, registry=registry)
                    break
            messages.append({"role": "user", "content": TEXT_CALL_NOTE + (TEXT_CALL_REVIVED.format(server=revived)
                                                                          if revived else "")})
            note = "The model wrote a tool call as text, so nothing ran; asked it to send a real tool call."
            if revived:
                note += f" Its server ({revived}) was off and is on again."
            if emit:
                emit({"type": "notice", "level": "warn", "text": note})
            else:
                print(f"{C_YELLOW}{note}{C_RESET}")
            _auto_raise("tool call sent as text")
            yolo_rollover()
            continue

        # No tool calls: the model thinks it is done.  The finish checks may send it back once more.
        if not res["tool_calls"]:
            if poll_queued():
                continue
            back = finish_checks(finish, messages, res["content"] or "", mode, current_ws, session_context, url,
                                 api_key, emit=emit, cancel=cancel, effort=effort)
            if back:
                messages.append({"role": "user", "content": back})
                _auto_raise("sent back by the finish checks")
                yolo_rollover()                 # a send-back must not run into the cap and end a YOLO run
                continue
            if poll_queued():
                continue

        # If no tool calls, turn is complete
        if not res["tool_calls"] and emit:
            wall = time.time() - t_start
            emit({"type": "stats", "tokens": total_tokens, "seconds": round(wall, 1),
                  "rate": round(total_tokens / wall, 1) if wall > 0 else 0})
            break
        if not res["tool_calls"]:
            wall = time.time() - t_start
            rate = total_tokens / wall if wall > 0 else 0
            print(f"{C_MUTED}[{total_tokens} tokens in {wall:.1f}s · {rate:.1f} t/s]{C_RESET}")
            if mode == "plan":
                print(f"{C_MUTED}💡 Plan ready. Type {C_BOLD}/act{C_RESET}{C_MUTED} or {C_BOLD}/execute{C_RESET}{C_MUTED} to apply changes, or ask adjustments.{C_RESET}\n")
            else:
                print()
            break

        # Process and execute each tool call
        for tc in res["tool_calls"]:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            bad_args = None
            try:
                args = json.loads(raw_args or "{}")
                if not isinstance(args, dict):
                    raise ValueError(f"expected a JSON object, got {type(args).__name__}")
            except Exception as e:
                args = {}
                bad_args = (f"Error: the arguments of this {fn_name} call are not valid JSON ({e}); nothing was run. "
                            f"They are {len(raw_args or ''):,} characters"
                            + (" and end mid-way, so the reply was probably cut off by the length limit. Send the "
                               "call again; write a big file in smaller parts (write_to_file, then "
                               "replace_file_content) or with fewer comments."
                               if res.get("finish_reason") == "length" or len(raw_args or "") > 4000 else "."))

            if emit:
                emit({"type": "tool_call", "id": tc.get("id"), "name": fn_name, "args": args,
                      **({"skipped": "small talk"} if small_talk else {})})
            else:
                print(f"{C_ACCENT}◆{C_RESET} {C_INK_SOFT}[Tool]{C_RESET} {C_BOLD}{fn_name}{C_RESET}({C_MUTED}{format_args_preview(args)}{C_RESET})")

            if not bad_args and not small_talk:
                finish["changes"].before_tool(fn_name, args)
            before = (scan_workspace(current_ws) if alarm and not bad_args and not small_talk and fn_name in WRITE_TOOLS
                      else None)
            if small_talk:
                if not finish.get("small_talk_noted"):
                    finish["small_talk_noted"] = True
                    _note(emit, "Small talk: a tool call was answered, not run (DL_SMALLTALK_GUARD=0 turns this off).")
                result_str = SMALL_TALK_NOTE
            else:
                try:
                    result_str = bad_args or dispatch_dl_tool(fn_name, args, current_ws, mode=mode,
                                                              session_context=session_context)
                except Exception as e:              # a tool's bug or an argument of the wrong type: the model hears
                    # it and goes on; it ended the whole request, the call left in messages with no result
                    result_str = f"Error: {fn_name} failed: {type(e).__name__}: {e}"
            result_str = cap_tool_result(result_str)    # 2026-10-20 22:12: a 106k debug print ended a CONTRA run
            if fn_name in READ_TOOLS and READ_RESULT_MAX > 0 and not bad_args:     # keep reads small (2026-11-14)
                # a file read keeps its start; a command keeps its start and its end, where the failures, the
                # summary and the "[Command exited with code N]" line are (cut off, a failed run looked like a pass)
                result_str = cap_tool_result(result_str, READ_RESULT_MAX, read=fn_name == "view_file")
            if before is not None:                  # did it empty, delete or halve a file?
                after = scan_workspace(current_ws)
                hits = shrunk_files(before, after) if after is not None else []
                if hits:
                    result_str = f"{result_str}\n\n{shrink_note(hits, cps)}"
                    _note(emit, f"Shrink alarm: {fn_name} " + "; ".join(h[1] for h in hits[:3])
                                + (f"; and {len(hits) - 3} more" if len(hits) > 3 else ""), "warn")

            # Check if directory was switched
            if session_context and session_context.get("workspace"):
                if session_context["workspace"] != current_ws:
                    current_ws = session_context["workspace"]
                    active_tools = get_active_tools(current_ws, mode=mode, registry=registry)
                    if dl_mcp is not None and dl_mcp.call_context():    # built-ins resolve files in the new one
                        dl_mcp.CALL.ctx = {**dl_mcp.call_context(), "workspace": current_ws}
            if registry is not None and registry.active:      # an MCP server may have been turned on or off
                active_tools = get_active_tools(current_ws, mode=mode, registry=registry)

            res_preview = result_str.strip()
            if emit:
                emit({"type": "tool_result", "id": tc.get("id"), "name": fn_name, "text": res_preview[:4000],
                      "truncated": len(res_preview) > 4000})
            else:
                if len(res_preview) > 160:
                    res_preview = res_preview[:160] + "..."
                print(f"{C_MUTED}  ↳ {res_preview}{C_RESET}\n")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id") or "call_1",
                "name": fn_name,
                "content": result_str
            })
            if advisor is not None and not small_talk:
                advisor.note_result(fn_name, args, result_str)
                if dl_effort is not None and not effort_auto:     # the helper also sees raises when effort is fixed
                    advisor.note_raise(dl_effort.raise_reason(fn_name, args, result_str, seen), fn_name)
            if dl_effort is not None:
                recent_fail = (recent_fail + [dl_effort.raise_reason(fn_name, args, result_str, fail_seen) is not None]
                               )[-PATCH_RECENT:]
            if effort_auto and dl_effort is not None and not small_talk:
                reason = dl_effort.raise_reason(fn_name, args, result_str, seen)
                if advisor is not None:
                    advisor.note_raise(reason, fn_name)
                _auto_raise(reason, noted=True)

        # pictures a tool handed back this round (the phone's photo): the model sees them in the next call, as a user
        # message after all of the round's tool results (the order the chat template expects)
        round_imgs = []
        for m in reversed(messages):
            if m.get("role") != "tool":
                break
            round_imgs = tool_result_images(m.get("name", ""), str(m.get("content", "")), current_ws) + round_imgs
        if round_imgs:
            messages.append({"role": "user", "dl_tool_images": True, "content":
                             [{"type": "text", "text": "[D.L. CLI: the image the tool returned above.]"}] +
                             [{"type": "image_url", "image_url": {"url": u}} for u in round_imgs]})
            if emit:
                emit({"type": "notice", "level": "info", "text": f"Image from the tool shown to the model ({len(round_imgs)})"})

        changed_now = False
        if cps is not None:                         # this round's changes, so the next one can be undone
            if cps.ws != Path(current_ws).resolve():
                cps = Checkpoints(current_ws, emit)
            prev_head = cps.head
            if cps.take(f"round {total_rounds}: " + ", ".join(
                    (tc.get("function") or {}).get("name", "?") for tc in res["tool_calls"])) is not None:
                names = cps.changed_since(prev_head) if prev_head else []
                changed_now = project_change(names) if names else True
        if cps is None or cps.off:                  # no checkpoints (off, no jj, too big a folder): go by the edit tools
            changed_now = project_change(_written_files(res["tool_calls"]), current_ws)
        on_round = (session_context or {}).get("on_round")
        if callable(on_round):
            try:
                on_round()
            except Exception:  # noqa: BLE001
                pass

        start = finish.get("cp_start")
        approve_fn = (session_context or {}).get("approve") or terminal_approve
        consulted = False
        if coding and not small_talk and NUDGE_AT > 0:          # edit-first watchdog
            quiet = 0 if changed_now else quiet + 1
            if changed_now:
                nudged = 0
            elif quiet >= NUDGE_AT and nudged == 0:
                nudged = 1
                messages.append({"role": "user", "content": NUDGE_NOTE.format(n=quiet)})
                _note(emit, f"Watchdog: {quiet} rounds without changing a project file; told Ray to make the edit.",
                      "warn")
            elif PATCH_AT > 0 and quiet >= PATCH_AT and nudged == 1:
                nudged = 2
                note = None
                # DeepSeek is asked only when something failed lately; quiet rounds of reading alone get the note
                # (2026-11-15: the patch fired 18 rounds in with nothing broken).  DL_PATCH_NEEDS_FAILURE=0: always.
                failing = any(recent_fail) or os.environ.get("DL_PATCH_NEEDS_FAILURE", "1") == "0"
                if advisor is not None and dl_advisor.enabled() and failing:
                    changed = cps.changed_since(start) if cps is not None and start else []
                    note = advisor.patch(registry, f"{quiet} rounds without changing a project file",
                                         f"nochange#{total_rounds}", files=advisor.target_files(changed),
                                         diff=cps.diff_since(start, 9000) if cps is not None and start else "",
                                         approve=approve_fn, emit=emit)
                    consulted = note is not None
                messages.append({"role": "user", "content": note or NUDGE_NOTE_2.format(n=quiet)})
                if not note:
                    _note(emit, f"Watchdog: {quiet} rounds without changing a project file; told Ray again.", "warn")

        if advisor is not None and not small_talk:    # stuck after thinking on high: ask DeepSeek, hand Ray the fix
            advisor.end_round()
            stuck = None if consulted else advisor.stuck()
            if stuck:
                diff = cps.diff_since(start, 9000) if cps is not None and start else ""
                files = advisor.target_files(cps.changed_since(start) if cps is not None and start else [])
                note = advisor.patch(registry, stuck[0], stuck[1], stuck[2], files=files, diff=diff,
                                     approve=approve_fn, emit=emit)
                if note:
                    messages.append({"role": "user", "content": note})

        poll_queued()
        if turn >= max_turns and (session_context or {}).get("yolo") and cancel is not None and cancel.is_set():
            break
        yolo_rollover()
    else:                                   # the cap ended the loop, not the model: ask it for a status
        if not (cancel is not None and cancel.is_set()):
            turn_cap_wrap_up(messages, url, api_key, active_tools, max_turns, emit=emit, cancel=cancel, effort=effort, budget=budget)

    if registry is not None and registry.active:
        registry.tick()
    if advisor is not None:
        advisor.finish()
    stop_left_listeners(session_context, emit)
    return current_ws


def main():
    os.environ.setdefault("DL_CHECKPOINTS", "1")             # workspace checkpoints (see Checkpoints)
    parser = argparse.ArgumentParser(description="D.L. CLI Autonomous Agent on Strata Engine")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace directory")
    parser.add_argument("--url", default=DEFAULT_URL, help="Strata URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Strata API Key")
    parser.add_argument("--plan", action="store_true", help="Start directly in Plan Mode")
    parser.add_argument("-p", "--prompt", help="Run single prompt non-interactively and exit")
    parser.add_argument("--attach", nargs="?", const="dl-ai-code", metavar="SESSION",
                        help="Join a shared session of the session daemon (the web app's Code tab shows the same one)")

    args = parser.parse_args()
    if args.attach:
        from dl_attach import attach
        sys.exit(attach(args.attach))
    ws = Path(args.workspace).resolve()
    mode = "plan" if args.plan else "act"

    if args.prompt:
        messages = [
            {"role": "system", "content": build_dl_system_prompt(ws, mode=mode)},
            {"role": "user", "content": build_user_message_content(args.prompt, ws)}
        ]
        try:
            execute_agent_loop(messages, args.url, args.api_key, ws, mode=mode)
            sys.exit(0)
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

    interactive_loop(ws, args.url, args.api_key, initial_mode=mode)

