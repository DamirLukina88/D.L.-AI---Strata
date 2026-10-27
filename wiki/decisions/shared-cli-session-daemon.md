---
title: "Shared CLI Session Daemon for Web and Terminal"
type: decision
description: "One D.L. CLI agent session in dl-ai-sessiond, used from the web Code tab and dl_cli.py --attach; replaced ttyd + tmux scraping"
status: active
tags: [cli, web-gui, mobile, architecture]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Shared CLI Session Daemon for Web and Terminal

## Summary

- 2026-10-13: The Code tab (ttyd iframe + a mobile wrapper scraping tmux with capture-pane/send-keys) was unusable on phones. Chosen (user): a shared agent session modelled on Claude Code Remote Control, over swapping ttyd for Zellij web or patching the wrapper.
- tools/dl_sessiond.py (user service dl-ai-sessiond) runs dl_cli's agent loop and owns named sessions (default dl-ai-code): history, workspace, mode, think level, approvals, interrupt. Unix socket $XDG_RUNTIME_DIR/dl-ai/sessiond.sock, JSON lines; sessions persist in ~/.local/state/dl-ai/sessions/.
- Clients: the web Code tab (serve/server.py bridges GET /api/code/session/events as SSE read with fetch, and POST /api/code/session) and the terminal: dl_cli.py --attach [session] (fish: dl-cli attach). Plain dl_cli.py still runs a private session.
- The agent loop takes emit/cancel hooks via session_context; terminal output is unchanged without them.
- claude-terminal.service (ttyd) is disabled and tools/run-code-session.sh removed.
- 2026-10-13 (night): The CLI follows the web app's Chat settings (user's request). `dl_cli.stream_chat_turn` no longer sends `reasoning_effort`, `temperature` or `max_tokens`, so the server fills in its shared Chat settings (`POST /settings`, kept in `strata-<model>.shared-settings.json`): effort, temperature, top_p, top_k, seed, max tokens and speed projection.
  - The web app always publishes them on Apply. The "Use for other apps too" switch is gone. On load (and when the drawer opens) the page adopts the server's copy, or publishes its own if the server has none.
  - `/think`, `--think` and the session's `think` state were removed; `/think` now prints where to change the settings. The banner, `/status` and the daemon's state show `dl_cli.chat_settings_summary()`.
  - The Code tab toolbar has the same Sampling button as Chat (`code-sampling-btn`).
  - Still per browser: "show thinking" (display only) and the web app's own MCP tools toggle.
  - Checked: with effort none a CLI-style request answered with 0 thinking words, with high 35, both within max_tokens 300.
  - Not changed: `tools/antigravity_local.py`, a separate copy of the CLI.
- 2026-10-17: Autonomous session management tools (`save_chat`, `get_system_health`, `get_engine_status`, `clear_conversation`) added to `DL_TOOLS` and `DL_PLAN_TOOLS`, allowing Qwen Coder to export sessions, inspect hardware/engine stats, and reset conversation memory autonomously. Conversational continuation phrases (`"continue"`, `"keep going"`, `"go on"`, `"proceed"`) in `dl_sessiond` and `dl_cli` automatically map to `/continue` after the tool-turn limit (`DL_MAX_TURNS`) is reached. In YOLO mode, reaching `DL_MAX_TURNS` automatically continues execution indefinitely without prompting the user. Tests in `tools/test_dl_session_tools.py` and `tools/test_dl_yolo_continue.py`.

- 2026-10-27: Saved sessions: /clear and /new keep the conversation; /sessions, /resume, /rename, /delete and a Sessions drawer in the Code tab. See [Saved CLI Sessions](saved-cli-sessions.md).

## Related

- [Scheduled Jobs in D.L. AI](dl-ai-scheduled-jobs.md)
- [Session Commands and Tools Implementation Plan](../artifacts/session-commands-and-tools-plan.md)
- [Home Assistant Server and Session Tools Walkthrough](../artifacts/homeassistant-and-session-tools-walkthrough.md)

## Sources

1. User, chat, 2026-10-13.
