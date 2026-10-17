---
title: "DeepSeek CLI Live Thinking Stream"
type: decision
description: "Real-time streaming display of reasoning/thinking tokens in DeepSeek CLI with dual Live panels and history preservation."
status: active
tags: [cli, deepseek, streaming, thinking, rich, reasoning]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# DeepSeek CLI Live Thinking Stream

## Summary
Updated the DeepSeek CLI to stream reasoning/thinking tokens in real time as the model generates them, anchoring the completed reasoning panel to terminal scrollback before streaming the answer below.

## Problem & Context
Previously, DeepSeek CLI buffered the reasoning process and only dumped a static panel at the conclusion of the request, or wiped out the reasoning panel when content tokens began arriving. When run without explicit flags (`-s --think`), streaming and thinking defaulted to disabled.

## Decisions & Architecture

### 1. Dual Sequential Rich Live Display
- **Live Reasoning Stream (`handlers/chat_handler.py`):**
  - Uses Rich `Live` (`live_think`) with `Text(reasoning_content)` refreshed at 10 Hz under title `[bold yellow]🧠 Thinking...[/bold yellow]`.
  - Avoids re-parsing incomplete markdown on every token chunk to eliminate terminal flashing and latency.
- **Freeze & Anchor:**
  - When regular answer tokens (`delta.content`) start arriving, `live_think` updates to complete markdown with `[bold yellow]🧠 Chain of Thought (Completed)[/bold yellow]` and executes `live_think.stop()`.
  - Rich's `stop()` with `transient=False` permanently writes the rendered panel into the terminal scrollback.
- **Live Answer Stream:**
  - Instantiates `live_answer = Live(...)` below the frozen thinking panel under title `[bold green]AI[/bold green]`.
  - Streams response markdown continuously until the SSE stream terminates.

### 2. Multi-turn History Preservation
- When reasoning mode is enabled, `reasoning_content` is stored alongside `content` in `self.messages` assistant history turns:
  ```python
  assistant_msg = {"role": "assistant", "content": full_response}
  if reasoning_content:
      assistant_msg["reasoning_content"] = reasoning_content
  self.messages.append(assistant_msg)
  ```
- Prevents API 400 errors on subsequent conversation turns and preserves full multi-turn context.

### 3. CLI Defaults & Runner Config
- Defaults `stream=True` and `think=True` in `ChatHandler` and `DeepSeekCLI`.
- Added `--no-stream` and `--no-think` CLI flags for explicit override.
- Persisted `"thinking": true` in `~/.config/deepseek-cli/settings.json`.
- Updated `tools/run-code-session.sh` and a temporary runner script (since removed) to execute `"$DEEPSEEK_BIN" -s --think`.

## Sources
- `~/.local/share/pipx/venvs/deepseek-cli/lib/python3.14/site-packages/deepseek_cli/handlers/chat_handler.py`
- `~/.local/share/pipx/venvs/deepseek-cli/lib/python3.14/site-packages/deepseek_cli/cli/deepseek_cli.py`
- `tools/run-code-session.sh`
- `~/.config/deepseek-cli/settings.json`
