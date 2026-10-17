---
title: "CLI Chat Markdown Export Feature"
type: decision
description: "Parity export feature for saving CLI conversations as structured Markdown via /save slash command and Web Code toolbar button."
status: active
tags: [dl-cli, export, markdown, web, api]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# CLI Chat Markdown Export Feature

## Summary

Implemented conversation export to Markdown for CLI sessions, providing feature parity with the Strata Web Chat export button. Available via `/save` (or `/export` / `/markdown`) inside D.L. CLI and through a one-click `#code-export-btn` download button on the Web Code toolbar.

## Context & Requirements

The Strata Web Chat had a "Save this chat as Markdown" button (`#export-btn`) that exports user prompts, assistant replies, collapsible thinking blocks, and tool executions. The user requested this capability for CLI sessions across both the terminal interface and the Web Code environment.

## Implementation Details

### 1. Terminal CLI Integration (`tools/dl_cli.py`)
- **Slash Commands:** Added `/save [file]`, `/export [file]`, and `/markdown [file]`. Defaults to `strata-chat-YYYY-MM-DD-HH-MM.md` in workspace, or writes to a custom path.
- **Formatter (`format_messages_to_markdown`):** Maps structured messages into Markdown with:
  - Header with date, model name, and workspace.
  - User Prompts (`## You`).
  - Assistant Responses (`## Qwen3.8-Flash-Next Coder`).
  - Collapsible Thinking blocks (`<details><summary>Thinking</summary>`).
  - Collapsible Tool Calls (`<details><summary>Tool {name}</summary>`) with args JSON and tool outputs.
- **Live State Persistence (`sync_current_chat_state`):** Writes temporary session state file `dl-cli-current-chat.json` after every turn, on start, and on memory reset.

### 2. Backend Endpoint (`serve/server.py`)
- **Route:** `GET /api/code/export?scaffold={active}`.
- If scaffold is `agy` and temporary chat state file `dl-cli-current-chat.json` exists in the system temporary directory, renders the rich structured Markdown.
- If other scaffolds (`claude`, `deepseek`, `codex`) or fallback, captures the active tmux pane (`tmux capture-pane -p -S - -t dl-ai-code:{scaffold}`), strips ANSI color codes, and formats into Markdown with session metadata.
- Returns JSON payload with `{status: "ok", markdown: "...", filename: "strata-{scaffold}-chat-...", scaffold: "..."}`.

### 3. Web Code Interface (`serve/web/index.html` & `serve/web/app.js`)
- Added `#code-export-btn` icon button with `web/sprite.svg#i-download` inside `.code-terminal-actions`.
- Clicking the button calls `GET /api/code/export?scaffold=${currentScaffold}`, generates a Markdown blob, and triggers browser file download.

## Related
- [Unified CLI Architecture & Mobile Companion Feed Walkthrough](../artifacts/unified-cli-and-mobile-companion-walkthrough.md)

## Sources

1. User, chat, 2026-10-11.
2. `tools/dl_cli.py`
3. `serve/server.py`
4. `serve/web/index.html`
5. `serve/web/app.js`
6. `tools/test_dl_auditing.py`
