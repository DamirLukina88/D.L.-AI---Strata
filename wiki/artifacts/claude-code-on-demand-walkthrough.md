---
title: Claude Code On-Demand Strata Walkthrough
type: artifact
description: Walkthrough of integrating Claude Code CLI with local Strata on-demand lifecycle and signal traps.
status: active
tags: [strata, claude-code, walkthrough, systemd, fish]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# Walkthrough: Claude Code CLI On-Demand Strata Integration

## Goal
The goal of this task was to configure the Claude Code CLI (`claude`) to run directly on top of the local Strata Qwen3.8-Flash-Next Coder engine, with an automatic on-demand lifecycle:
1. Automatically start the Strata engine when `claude` is launched.
2. Provide free, private, unlimited token inference via the local AMD RX 7600 XT GPU.
3. Automatically shut down the engine and release all 30 GB of system RAM and 6.6 GB of GPU VRAM when the session ends or the terminal window is closed.
4. Keep the official Claude Desktop application completely untouched and isolated.

## Implementation Details

### 1. Engine Configuration (`strata-coder-iq1_m.json`)
- **API Key Persistence:** Added `"api_key": "54adad..."` to ensure the Anthropic `/v1/messages` endpoint is always authenticated.
- **`fit_max_tokens` Resolution:** Claude Code CLI sends a ~28,224 token system prompt containing tools, instructions, and environment details, and requests `max_tokens: 64000`. On a 65,536 token context window, this sum (92,224 tokens) exceeded the window, resulting in an HTTP 400 error. Adding `"fit_max_tokens": true` instructs Strata to automatically clamp `max_tokens` to the remaining space in the context window.

### 2. User Service Daemon (`~/.config/systemd/user/strata-server.service`)
- Created a dedicated user systemd service to manage the model process cleanly outside transient terminal cgroups:
  - Working directory: `/mnt/data/Strata`
  - Command: `/mnt/data/Strata/run-coder-iq1_m.sh`
  - TimeoutStopSec: 15
  - KillMode: mixed

### 3. Shell Wrappers (`config.fish` & `.bashrc`)
- Added lifecycle management functions in Fish and Bash:
  - **Health check:** Pings `http://127.0.0.1:8080/health`. If not running, launches `systemctl --user start strata-server` and polls until `"loaded": true`.
  - **Environment routing:** Injects `ANTHROPIC_BASE_URL="http://127.0.0.1:8080"` and `ANTHROPIC_AUTH_TOKEN`.
  - **Signal traps:** Bound to `SIGHUP`, `SIGINT`, `SIGTERM`, and `fish_exit` so that even if the terminal emulator window is abruptly closed with the "X" button, the engine is cleanly stopped.
  - **Coexistence:** If Strata was already running before `claude` was launched, it leaves the engine running upon exit.
  - **Cloud fallback:** Retained `claude-cloud` alias for official Anthropic cloud usage.

## Validation Results
- **Cold-Start Verification:** Executed `claude -p "Respond with only the word: PONG"`. The wrapper started the systemd service, waited for weights to lock into memory, processed 28,224 prompt tokens at 267.4 tokens/second, printed `PONG`, and cleanly shut down the engine.
- **Memory Recovery Verification:** System memory dropped from 25 GB used during inference down to ~3.8 GB used after shutdown, returning over 21 GB of system RAM and 6.6 GB of VRAM back to the desktop environment.
- **Window Closure Verification:** Verified that terminating the shell triggers the `fish_exit` / `SIGHUP` trap, ensuring no zombie engine processes remain.

## Sources
- **Tool:** Antigravity AI Assistant
- **Session ID:** 44aeb44c-4179-41a4-b503-f0e55de2e0a8
- **Date:** 2026-10-10
