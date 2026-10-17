---
title: "GitHub Fork Sanitization and Push Plan"
type: artifact
description: "Security plan and execution details for sanitizing credentials and publishing the custom Strata fork to GitHub."
status: active
tags: [github, git, security, sanitization, public-fork]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# GitHub Fork Sanitization and Push Plan

This plan details the process for sanitizing and publishing the customized version of Strata with all custom features to your GitHub fork: **[https://github.com/DamirLukina88/D.L.-AI---Strata](https://github.com/DamirLukina88/D.L.-AI---Strata)**.

---

## Goal Description

Publishing a feature-rich fork of Strata featuring:
1. **Authenticated Claude Code CLI Web Terminal** (`#tab-btn-code`, WebSocket tunneling, persistent tmux session, session restart API).
2. **Dedicated Server Workspace Management** (`/mnt/data/DL-AI-workspace` with recursive N-ary collapsible folder tree and file drag-and-drop).
3. **Responsive Mobile Web GUI** (touch-friendly targets, collapsible sidebars, dynamic dark theme).
4. **Agentic Coding MCP Tools** (`strata_coder_generate` and `strata_coder_review` in `tools/strata_mcp.py`).
5. **System Management Scripts** (`strata.sh` CLI wrapper, `strata-watchdog.sh` auto-healer).
6. **Upstream v0.1.42 Enhancements** (AMD Linux PCIe link telemetry, sparkline noise filtering, spaceless reasoning loop detection).

**Core Security Mandate:** Ensure **zero private credentials, zero API keys, and zero private access realms** are exposed in the repository.

---

## Security Audit & Actions

| File | Sensitive Data Identified | Sanitization Action |
| --- | --- | --- |
| `serve/web/app.js` | Hardcoded default API key | Changed to `""`. Read from `localStorage` or URL only. |
| `serve/web/app.js` | Hardcoded Cloudflare Access team name | Switched to relative endpoint `"/cdn-cgi/access/logout"`. |
| `serve/web/index.html` | Hardcoded `localStorage.setItem` script | Removed script. Default to clean prompt. |
| `serve/web/monitor.js` | Hardcoded default API key | Changed default to `""`. |
| `tools/run-code-session.sh` | Hardcoded API key and local directory | Read from `$STRATA_API_KEY` and `$STRATA_WORKSPACE_DIR` env vars. |
| `.gitignore` | Missing ignores for local runtime files | Added `.directory`, `strata-server.out`, `strata-server.pid`, `*.orig`. |
| `wiki/` | Local notes & `wiki/private/.env` | Ignored by `.gitignore`. Verified: **not committed**. |
| `strata-*.json` | Local config files with API key | Ignored by `.gitignore`. Verified: **not committed**. |

---

## Verification & Execution

- Executed pre-commit security scans (`grep -r` for keys and private strings).
- Committed changes cleanly on `main` branch.
- Successfully pushed to `https://github.com/DamirLukina88/D.L.-AI---Strata.git`.

---

## Sources

- Tool: Antigravity pair programming session
- Session ID: `44aeb44c-4179-41a4-b503-f0e55de2e0a8`
- Date: 2026-10-10
