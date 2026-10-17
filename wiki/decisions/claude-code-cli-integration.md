---
title: "Claude Code CLI Integration on Strata"
type: decision
description: "How Claude Code CLI routes to local Strata with fit_max_tokens while isolating Claude Desktop."
status: active
tags: [claude-code, strata, cli, integration, gotchas]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# Claude Code CLI Integration on Strata

## Summary
The Claude Code CLI (`claude`) is configured to use the local Strata server (`http://127.0.0.1:8080`) as its Anthropic-compatible inference backend. This provides full terminal agent scaffolding on top of the local Qwen3.8-Flash-Next Coder model with zero API costs, while keeping the official Claude Desktop app completely untouched.

## Decisions & Configuration

### 1. Shell Wrapper vs Desktop Isolation
- **Terminal Routing:** Functions added to `~/.config/fish/config.fish` and aliases in `~/.bashrc` automatically set `ANTHROPIC_BASE_URL="http://127.0.0.1:8080"` and `ANTHROPIC_AUTH_TOKEN` when typing `claude`. A `claude-cloud` fallback is retained.
- **Desktop Isolation:** The official Claude Desktop application maintains its own private installation at `~/.config/Claude/claude-code/` and is unaffected by terminal shell functions.

### 2. Gotcha: `fit_max_tokens` Required for 65k Context
- **Problem:** Claude Code CLI sends ~28,224 tokens of system prompts/tools and requests `max_tokens: 64000`. On a 65,536 context window, this sum exceeds total context, causing HTTP 400 rejection.
- **Solution:** Add `"fit_max_tokens": true` to `strata-coder-iq1_m.json`. Strata will automatically clamp `max_tokens` to the remaining space in the context window.

### 3. On-Demand Lifecycle (Auto-Start & Auto-Stop)
- **Problem:** Keeping 30 GB of model weights and 6.6 GB of VRAM resident when not coding restricts system resources for browsers, gaming, or desktop tasks.
- **Solution:** A user systemd unit (`~/.config/systemd/user/strata-server.service`) is managed automatically by the `claude` shell function. When `claude` is executed:
  1. It checks if Strata is already running. If not, it starts `strata-server.service` and polls health until loaded.
  2. Runs the interactive Claude Code CLI session.
  3. When Claude Code exits, it automatically stops `strata-server.service`, cleanly freeing all 30 GB RAM and GPU VRAM. If Strata was already running beforehand, it leaves it alone.

### 4. Web Interface & Persistent Session (Code Tab)
- **Architecture:** A dedicated web terminal is exposed via the "Code" tab in the web UI at `https://ai.damir-lukina.com/`.
- **Backend:** `ttyd` (1.7.7) runs on `127.0.0.1:7681` managed by `claude-terminal.service`. It connects to a persistent tmux session named `dl-ai-code` via `tools/run-code-session.sh`.
- **Environment & Routing:** Launched with `ANTHROPIC_BASE_URL="http://127.0.0.1:8080"`, `ANTHROPIC_MODEL="qwen3.8-flash-next-coder-iq1_m"`, and pinned strictly to working directory `/mnt/data/DL-AI-workspace`.
- **Authentication & Security:** Reverse-proxied through Strata (`serve/server.py`) over HTTP route `code/`. Requires Strata API key (via header, URL token, or `strata_key` cookie). Bidirectional WebSocket upgrades (WebSocket route `code/ws`) are proxied via a raw TCP socket tunnel. Zero external ports are opened.
- **Session Persistence & Respawn Restart:** Navigating away or closing the mobile browser leaves the `tmux` session running. The "Restart" button in the web UI calls `POST /api/code/restart`, which invokes `tmux respawn-pane -k -t dl-ai-code:0.0`. This resets the CLI runner in-place without terminating the tmux session or ttyd daemon, preserving the live WebSocket connection without error 1006 drops.

### 5. Auto Mode Server Prompt Silencing
Claude Code v2.1.280+ introduces cloud-side classifier billing checks for Auto Mode. When routing requests through local gateway `http://127.0.0.1:8080`, Claude Code prompts that the session is ineligible. Setting `CLAUDE_CODE_AUTO_MODE_SERVER=0` in `~/.claude/settings.json` and `tools/run-code-session.sh` informs Claude Code to perform client-side classifications without displaying gateway notices or interrupting execution.

### 6. Dynamic Thinking Isolation (Code CLI vs Web Chat UI)
To maximize agentic velocity in Claude Code while allowing full reasoning control in Web Chat:
- **Claude Code CLI (Code Tab & Terminal):** Thinking is deactivated by default (`enable_thinking: false`). Tool calls (`Read`, `Edit`, `Bash`, `Grep`) trigger instantly without 5–12 second thinking pauses.
- **Web Chat UI (`/` Chat Tab):** Thinking is dynamically governed by the Sampling drawer's Thinking selector (`Off` -> answers right away, `Low` -> short, `Medium` -> medium, `High` -> thorough).
- **D.L. CLI & Cross-CLI Styling:** For local CLI default reasoning effort (`medium`) and unified terminal card aesthetics across all scaffolds, see [CLI Graphical Styling & Thinking Defaults](cli-graphical-styling-and-thinking-defaults.md).
- **Zero Model Reloads:** Both endpoints run concurrently against the single loaded model instance; thinking behavior is resolved per-request at prompt formatting time without dropping or swapping VRAM weights.

### 7. Model Preload Token Variances & Prompt Guardrails
When switching models in Claude Code CLI, preload token counts vary by model family:
- **Opus (~36,844 tokens):** Most compact prompt footprint. Anthropic omits verbose permission explanations and trust heuristics, assuming superior baseline reasoning.
- **Haiku (~37,688 tokens):** Adds 5 defensive behavioral paragraphs (+3,000 chars) instructing the model on turn completion, permission rules, and non-blocking errors, plus an explicit subagent restraint warning in the `Agent` tool schema (*"When in doubt, don't spawn"*).
- **Fable / Sonnet (~38,625 tokens):** Full autonomous agentic suite with complete tool specifications, planning protocols, and multi-file verification rules.
- **Captured Dumps:** Payloads are archived for inspection at `/mnt/data/Strata/dumps/claude_models/`.

### 8. Applied Performance Tuning Settings & Caching Optimizations
To maximize throughput and ensure 100% prompt cache prefix hits with Claude Code CLI on the AMD RX 7600 XT:
1. **Dynamic Token Budget Pinning (`pin_billing_stamp` in `serve/frontend.py`):**
   Claude Code appends a dynamic token countdown `<total_tokens>... tokens left</total_tokens>` to the end of its ~37,000-token system prompt. Normalizing this tag to `<total_tokens>15000000 tokens left</total_tokens>` guarantees byte-identical prefix hashing across all session turns, unlocking full prompt cache reuse.
2. **Extended Prefill Chunking (`--prefill auto:16384`):**
   Increased ubatch chunk borrowing limit from 8,192 to 16,384 tokens. Reduces kernel launch passes on 37k prompts from 5 down to 3 and cuts redundant PCIe weight streaming during prefill.
3. **Prompt Cache Checkpoint Capacity (`--prompt-cache 12`):**
   Raised retained checkpoints from default 6 to 12. With `--max-context 65536` and `--prompt-cache-every 8192`, all incremental checkpoints, the system prompt root, and tail remain cached without LRU eviction during long agent runs.
4. **Gateway Model Aliases & Stable Effort Positioning:**
   Added official model aliases (`claude-3-5-haiku-20241022`, `claude-haiku-5-5`, `claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`, etc.) and `"effort_position": "end"` in `strata-coder-iq1_m.json`. Requests requesting standard Claude model names map transparently without warnings or prompt cache prefix disruption.

### 9. Multi-Scaffold Terminal Architecture (Claude Code, D.L. CLI, DeepSeek)
The Code view in the Strata Web application is organized as a tri-scaffold coding terminal:
- **Claude Code CLI (`claude`):** Anthropic CLI running stripped Fable 5.1 system prompt and pure local tools (`Bash,Edit,Read,Write,Glob,Grep`), connected locally to Strata (`127.0.0.1:8080`).
- **D.L. CLI (`agy`):** Autonomous agent harness (`tools/dl_cli.py`) with Plan/Act modes, local wiki recall, and auditing guardrails suite.
- **DeepSeek CLI (`deepseek`):** Dedicated terminal coding engine with dual live streaming and real-time reasoning visualization.
- **Codex Pruned:** Codex was pruned from the UI, endpoints, and tmux session to keep the environment lean and focused.

### 10. Stripped-Down Fable 5.1 System Prompt & Lean Toolset
- **Problem:** Default Claude Code CLI sends 23 tools (many requiring cloud backends like `Cron*`, `PushNotification`, `ScheduleWakeup`, `DesignSync`, `WebFetch`) and ~38,000 tokens of system prompt every turn. On consumer GPU/RAM, prefilling 38k tokens takes 20–30s per interaction.
- **Solution:** Configured a lean Fable 5.1 system prompt at `~/.claude/profiles/fable_system_prompt.md` and restricted tools to `--tools "Bash,Edit,Read,Write,Glob,Grep"`.
- **Latency Gain:** Shrinks system prompt prefill from ~38,000 tokens down to <2,500 tokens, achieving a ~90% reduction in prefill latency while preserving core local engineering capabilities.
- **Launcher Integration:** Both `tools/run-code-session.sh` and the `claude()` bash wrapper in `~/.bashrc` automatically supply `--tools "Bash,Edit,Read,Write,Glob,Grep"` and `--system-prompt` from the Fable profile.

### 11. Mobile Responsive Layout Fix for Code Tab
- **Problem:** On mobile screens ($\le 600\text{px}$), the quad-scaffold button picker, session status text, and actions inside `.code-terminal-bar` exceeded the viewport width (~650px content width). In flexbox, flex children default to `min-width: auto`, which forced `.view--code`, `<main>`, and `<body>` to expand past $100\text{vw}$, breaking the top header and inducing horizontal scroll.
- **Solution:**
  1. Enforced `min-width: 0; max-width: 100vw; overflow-x: hidden;` on `main`, `.view`, `.view--code`, and `.code-terminal-wrap`.
  2. Implemented responsive wrapping on viewports $\le 900\text{px}$: `.code-terminal-bar` wraps into two rows. Row 1 holds terminal status on the left and actions (Restart + Fullscreen) on the right. Row 2 holds `.code-scaffold-picker` with `order: 3; width: 100%; overflow-x: auto; scrollbar-width: none;`.
  3. On viewports $\le 600\text{px}$: `.code-meta` is hidden, `.code-title` has ellipsis truncation, `.code-action-btn span` text is hidden (leaving compact icon buttons), and scaffold buttons adapt with compact padding (`26px` height, `11px` font). Header and menu boundaries remain strictly within $100\text{vw}$ with zero horizontal shift.

### 11. Complete Local Strata Routing for All Four Scaffolds
To achieve 100% offline, zero-cost, and private operation across the entire quad-scaffold suite, every CLI was routed directly to the local Strata engine (`127.0.0.1:8080`):
- **DeepSeek CLI (`deepseek-cli`):**
  - Upstream hardcoded `DEFAULT_BASE_URL = "https://api.deepseek.com/v1"`.
  - Patched `deepseek_cli/config/settings.py` in the pipx virtualenv to respect `os.getenv("DEEPSEEK_BASE_URL")`.
  - Exported `DEEPSEEK_BASE_URL="http://127.0.0.1:8080/v1"` and `DEEPSEEK_API_KEY="$STRATA_API_KEY"`.
  - Routes directly to Strata's OpenAI-compatible chat completions endpoint (`127.0.0.1:8080/v1/chat/completions`) running Qwen3.8-Flash-Next Coder.
- **OpenAI Codex CLI (`@openai/codex`):**
  - Codex v0.162.1 requires OpenAI's modern Responses API (`wire_api = "responses"`).
  - Configured `~/.codex/config.toml`:
    ```toml
    model_provider = "strata"
    model = "gpt-5.5"

    [model_providers.strata]
    name = "Strata"
    base_url = "http://127.0.0.1:8080/v1"
    env_key = "STRATA_API_KEY"
    wire_api = "responses"
    ```
  - Strata handles requests via `POST /v1/responses`, resolving model aliases (`gpt-5.5` / `gpt-6-sol`) directly to Qwen3.8 Coder.
- **D.L. CLI (Autonomous Engineering Agent):**
  - Custom local engineering agent (`tools/dl_cli.py`) built directly for Damir Lukina's workstation to provide an autonomous pair programmer without any third-party cloud branding or dependencies.
  - Implements full agentic capabilities: real-time SSE streaming from `http://127.0.0.1:8080/v1/chat/completions`, native reasoning/thought streaming (`<think>` blocks rendered in real time), `@file` context injection, and an autonomous tool execution loop with `view_file`, `write_to_file`, `replace_file_content`, and `run_command`.
  - Driven 100% locally by Strata's Qwen3.8-Flash-Next Coder model with ROCm GPU acceleration.
- **Claude Code CLI (`claude`):**
  - Defaults to `ANTHROPIC_BASE_URL="http://127.0.0.1:8080"`, `ANTHROPIC_AUTH_TOKEN="$STRATA_API_KEY"`, and `--model haiku`.

### 12. D.L. CLI Autonomous Tools (Exa Web Search & Context7 Documentation)
- **Position & UI Priority:** Rebranded from Antigravity to **D.L. CLI** and prioritized as item #1 in the web terminal scaffold segmented bar and default active session (`dl-ai-code:agy`).
- **Exa AI Web Search (`exa_web_search`):** Integrated semantic web search via Exa API with live search results, titles, URLs, and text summaries. Includes `/search <query>` terminal shortcut. Key stored securely in `wiki/private/.env` (`EXA_API_KEY`).
- **Context7 Documentation MCP (`resolve_library_id` & `get_library_docs`):** Integrated real-time library documentation lookup over JSON-RPC via `@upstash/context7-mcp` using `CONTEXT7_API_KEY`. Allows the local model to fetch verified code examples and API references. Includes `/docs <lib>` shortcut.

### 13. Workstation Memory Constraints & Reasoning Effort Gotcha
- **Constraint:** The workstation has 32 GB of physical RAM. The resident 125B MoE weights (`Qwen3.8-Flash-Next Coder IQ1_M`) take ~28–29 GB of RAM.
- **Gotcha:** Setting reasoning effort to `high` (maps to `xhigh` in Qwen) triggers deep multi-thousand-token thought chains. This rapidly exhausts the remaining ~2 GB RAM margin, forcing the Linux kernel into heavy swap thrashing (19.7 GB swap peak) and making the desktop GUI unresponsive until `systemd-oomd` terminates the unit.
### 14. Plan Mode Architecture in D.L. CLI
- **Inspiration & Parity:** Implemented Plan Mode inspired by Claude Code's Plan Mode (`Shift+Tab` / `/plan`), allowing developers to explore, analyze, and draft structured architectural plans before modifying files.
- **Tool Filtering & Sandboxing:**
  - **Act Mode (`[ACT MODE]`):** Exposes full tool suite (`DL_ACT_TOOLS`: `run_command`, `view_file`, `write_to_file`, `replace_file_content`, `exa_web_search`, `resolve_library_id`, `get_library_docs`).
  - **Plan Mode (`[PLAN MODE]`):** Excludes mutating write tools (`write_to_file`, `replace_file_content`). Exposes strictly read-only inspection tools (`DL_PLAN_TOOLS`: `view_file`, `exa_web_search`, `resolve_library_id`, `get_library_docs`, and inspection-scoped `run_command`).
  - `dispatch_dl_tool` enforces a hard guardrail: any attempted file write in Plan Mode immediately returns `"Error: [PLAN MODE] File modifications are disabled. Research the codebase and present your implementation plan for approval before executing."`
- **Dynamic System Prompt & Persona:**
  - System prompt switches between `act` and `plan` modes dynamically, instructing the model in Plan Mode to produce structured plans (Context & Architecture, Proposed Changes, Phased Steps, Verification Strategy) and ask for user approval before execution.
- **Commands & UX:**
  - `/plan`: Toggles between Plan and Act modes. Supports `/plan on`, `/plan off`, and `/plan <task>` to immediately run a planning turn.
  - `/act`, `/execute`: Switches back to Act Mode (or `/act <task>` to immediately run an execution turn).
  - CLI Prompt Indicator: `dl > ` in Act Mode vs `dl (plan) > ` in Plan Mode.
### 15. Local Wiki Knowledge Base Integration in D.L. CLI
- **Tool (`local_wiki`):** Integrated full Local Wiki tool support into D.L. CLI powered by `wiki.py` (resolved dynamically from workspace, `~/Desktop/local-wiki/scripts/wiki.py`, or the local-wiki plugin).
  - Actions supported: `search`, `read_page`, `new_page`, `lint`, `digest`, `init`, `env_list`, `log`.
  - In **Plan Mode**: Read-only exploration actions (`search`, `read_page`, `digest`, `lint`, `env_list`) are active. Write actions (`new_page`, `init`, `log`) are guardrailed.
  - In **Act Mode**: Full read and write knowledge persistence is enabled.
- **Dynamic System Prompt Integration:** When a workspace wiki is resolved (e.g. `/mnt/data/Strata/wiki`), D.L. AI's system prompt is automatically populated with the connected knowledge base rules, directing the model to search existing decisions, constraints, and preferences before writing code.
- **Terminal Slash Command (`/wiki`):** Added native terminal commands:
  - `/wiki` or `/wiki status`: Displays connection status, active wiki root, and session digest.
  - `/wiki search <query>`: Executes instant ranked search against the wiki.
  - `/wiki lint`: Audits the wiki for broken links, missing frontmatter, or orphaned pages.
  - `/wiki digest`: Prints compact session summary.
  - `/wiki init`: Initializes a `wiki/` directory in the current workspace.
  - `/wiki env`: Lists credential keys in `wiki/private/.env`.
- **Banner Status:** Displays `Wiki: Active (<name>)` and lists `local_wiki` among active tools on CLI launch.

## Related
- [Shared Workspace on Dedicated Storage](shared-workspace-d-disk.md)
- [Strata](../entities/strata.md)
- [RX 7600 XT CachyOS Deployment](rx-7600-xt-cachyos-deployment.md)
- [Claude Code On-Demand Strata Walkthrough](../artifacts/claude-code-on-demand-walkthrough.md)
- [Claude Code Web Terminal Integration Plan](../artifacts/claude-code-web-terminal-integration-plan.md)
- [Codebase Audit Report](../artifacts/codebase-audit-report.md)
- [Codebase Audit Walkthrough](../artifacts/codebase-audit-walkthrough.md)
- [Tetris Single-File Plan](../artifacts/tetris-single-file-plan.md)

## Sources
- **Agent:** Antigravity (Gemini)
- **Session ID:** 44aeb44c-4179-41a4-b503-f0e55de2e0a8
- **Date:** 2026-10-10




