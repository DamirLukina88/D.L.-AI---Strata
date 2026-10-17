---
title: "D.L. AI Plan (2026-10-13): Shared Session, Guardrails, README"
type: artifact
description: "Phases 2, 5 and 6 of the 2026-10-13 plan: shared CLI session daemon, approval guardrails, README rewrite"
status: active
tags: [plan, cli, guardrails, readme]
created: 2026-10-15
updated: 2026-10-15
last_verified: 2026-10-15
---

# D.L. AI Plan (2026-10-13): Shared Session, Guardrails, README

Phases 2, 5 and 6 of [D.L. AI Implementation Plan (2026-10-13)](dl-ai-2026-10-13-implementation-plan.md). The context, order, verification and outcome are on that page.

## Phase 2: A shared agent session for the web CLI and the terminal (like Claude Code Remote Control)

**Goal:** one CLI session that runs on the server and can be driven from the terminal and from the web/phone at the same time. The web view is a native mobile-friendly UI, not a terminal emulator. This replaces ttyd, the tmux screen scraping (`/api/code/chat`, `/api/code/send`, capture-pane in `serve/server.py` ~5263-5760) and `claude-terminal.service`.

**2a. Split `tools/dl_cli.py` (1717 lines) into a core and its front ends.**
- New `tools/dl_agent/core.py` holds the code that doesn't depend on a UI:
  - `build_dl_system_prompt`
  - the tools, `dispatch_dl_tool`
  - `stream_chat_turn`
  - `execute_agent_loop`
  - markdown export
  - plan/act state
- `execute_agent_loop` and `stream_chat_turn` stop printing. Instead they emit events to a callback: `thinking_delta`, `text_delta`, `tool_call`, `tool_result`, `approval_request`, `mode_change`, `turn_end`, `error`.
- `dl_cli.py` keeps its current look by rendering those events to ANSI. Its standalone mode keeps working.

**2b. Session daemon `tools/dl_agent/sessiond.py`, a user service `dl-ai-sessiond.service`.**
- Holds named sessions (default `dl-ai-code`): message history, workspace, mode, think level.
- Listens on a Unix socket `$XDG_RUNTIME_DIR/dl-ai/sessiond.sock` and speaks JSON lines:
  - `attach`, which replays history and then streams live events
  - `input`, `slash`, `approve`, `deny`, `interrupt`
- Saves sessions to `~/.local/state/dl-ai/sessions/<name>.json`, so they survive restarts.
- Runs one turn at a time per session, and every client attached to that session sees the same stream.

**2c. Terminal client.**
- `dl-cli attach [name]` (fish function plus `tools/dl_cli.py --attach`) connects to the socket and renders with the existing ANSI renderer.
- Ctrl-C sends `interrupt`, and `/detach` leaves the session running.
- Plain `dl-cli` with no daemon still runs standalone, as today.

**2d. Web client: the Code tab in `serve/web/app.js` and `index.html`.**
- `serve/server.py` gets `GET /api/code/session/events` (SSE; it bridges the Unix socket) and `POST /api/code/session/{input,slash,approve,deny,interrupt}`. Both use the Phase 3 auth.
- The UI reuses the Chat tab's message rendering (markdown, code blocks, collapsible thinking) and adds:
  - tool-call cards
  - an approval card with Approve/Deny buttons
  - chips for `/plan`, `/act`, `/health`, `/status`, `/exa`, `/context7`, `/save`
  - a workspace selector
  - the existing workspace file manager button
- `/health` and `/status` are sent as structured data and drawn as HTML bars, so no ANSI ends up on mobile.
- Remove the ttyd iframe, `frame.src = "/code/"`, the `/code/*` proxy (`_tunnel_ws`, `_proxy_http`, the `/code/token` stub) and the `strata_key` cookie that was set from `?token=`.
- **Optional fallback:** keep a "Raw shell" toggle that starts ttyd only on demand, behind the same auth, for `bash`. It is off by default.

## Phase 5: Guardrails (request 3)

Keep the security guards as they are:
- `scan_secrets` on writes
- the sensitive-file guard (`dl_cli.py:505`)
- the workspace path checks
- the "content is data, not instructions" rule

No content-restriction rules exist in the prompt, so nothing needs removing for the uncensored model.

1. **Approval for destructive commands, in `core.py`.**
   - Add `classify_command(cmd, workspace)`. It flags:
     - `rm -r`/`-f` outside tmp
     - `sudo`, `dd`, `mkfs`, `shred`, `wipefs`
     - `chmod -R` / `chown -R`
     - `git push --force`, `git reset --hard`, `git clean -f`
     - `systemctl stop|disable`, `kill -9`
     - `> /dev/sd*`
     - any write or redirect outside the workspace
   - `write_to_file` and `replace_file_content` outside the workspace are flagged too.
   - A flagged call emits `approval_request` and waits:
     - in the terminal, a `y/N` prompt
     - on the web, Approve/Deny buttons
   - Deny returns `"Denied by user"` to the model.
   - `/yolo` skips approval for the rest of the session (off by default, and the banner shows it).
   - Unit tests go in `tools/test_dl_auditing.py`.
2. **Plan mode may execute.**
   - The plan prompt (`dl_cli.py:434-469`) ends with a plan plus the question "Execute this plan?".
   - An `approval_request{kind:"plan"}` shows Execute/Revise. Execute switches to act mode and runs the plan without a manual `/act`.
3. Remove `FABLE_STRIPPED_SYSTEM_PROMPT` / `optimize_claude_code_system_prompt` from `serve/frontend.py:471-495`, because Claude Code was removed from the app on 11 Oct. Keep it only if Phase 1's merge shows it's still referenced.

## Phase 6: README rewrite (request 2)

Replace `README.md` (still the upstream text). Delete `README.{zh-CN,ja,de,fr,es,pt-BR}.md`, since they describe upstream, not this fork.

Defaults for the questions Antigravity asked but you never answered:
- Title **"D.L. AI"**, with the subtitle "a private AI workstation built on Strata"
- Intro: "Dedicated private AI without external tracking. Your own model, your own rules."
- An attribution line linking to Niko1221/Strata and keeping its LICENSE
- **Hardware & benchmarks:**
  - RX 7600 XT 16 GB, 32 GB RAM, CachyOS, ROCm
  - a highlight card (31.2 tok/s decode, 291.7 tok/s 16K prefill, 1.69 s TTFT)
  - the arm progression table from `wiki/artifacts/v0-1-43-optimization-benchmark-report.md`, updated with Phase 1's numbers
- **Features:**
  - the shared web/terminal CLI
  - workspace manager
  - JIT model load/unload and force restart
  - Cloudflare Access remote access
  - local wiki integration
  - guardrails
- **Setup:** `strata.sh`, the systemd units, `secrets.env`, Cloudflare Access settings (AUD tag)
- **Security:** no secrets in the repo, Access JWT, `/v1` needs a key
- Text and tables only, no generated images
- No private domain, machine paths or keys. `scan_secrets` must pass before the commit.

## Related

- [D.L. AI Implementation Plan (2026-10-13)](dl-ai-2026-10-13-implementation-plan.md) (split from this page on 2026-10-15)

## Sources

1. Claude Code plan file `~/.claude/plans/create-a-implementation-plan-valiant-ladybug.md`, session of 2026-10-13, approved by the user.
