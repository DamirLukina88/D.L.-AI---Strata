---
title: "Google Workspace MCP Live Setup for D.L. CLI"
type: artifact
description: "How Gmail, Drive and Docs run in D.L. CLI: workspace-mcp, the gmail/drive/docs split, approvals, token, credential filter"
status: active
tags: [mcp, google, gmail, drive, docs, cli, security]
created: 2026-10-15
updated: 2026-10-15
last_verified: 2026-10-15
---

# Google Workspace MCP Live Setup for D.L. CLI

The live Google setup of [D.L. CLI On-Demand MCP Loading Plan](dl-cli-on-demand-mcp-plan.md), as built on 2026-10-15.

## Google: live setup (2026-10-15)

- **Server:** `workspace-mcp` 1.30.1 in its own venv `~/.local/share/dl-ai/mcp-google-venv`. It runs as `workspace-mcp --single-user --permissions gmail:send drive:full docs:full`.
  - The user chose the full levels: Gmail up to send, and Drive and Docs read and write.
  - The server offers 49 tools; the allowlist passes on 18.
- **Tools:**
  - 9 read-only, offered in plan mode too: Gmail search, message and thread; Drive search, file content and list; Docs search and as-Markdown; `start_google_auth`.
  - `ask` (asks first; `/yolo` skips it): Gmail draft and labels; Drive create and update; Docs create, modify text, and find and replace.
  - `ask_always` (asks even in `/yolo`): `send_gmail_message` and `manage_drive_access` (sharing).
  - `ask_always_args`: `update_drive_file` always asks when `trashed` is set.
- **Hidden fixed argument:** every tool needs `user_google_email`. `fixed_args` in `mcp.json` removes it from the schema the model sees and adds it to every call, so the model can't pick another account.
- **Surfaces:** `["code"]`. Google runs only in the shared daemon (the web Code tab and `dl_cli.py --attach`); the stand-alone REPL refuses it.
- **Credentials and token:**
  - The client ID and secret are in `secrets.env` (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`).
  - The token is in `~/.config/dl-ai/google/<account>.json`, and the server's PKCE state in `oauth_states.json` there.
  - `WORKSPACE_MCP_CREDENTIALS_DIR` and `WORKSPACE_MCP_PORT=8000` are set in the `mcp.json` env.
- **Live checks:**
  - The sign-in succeeded. Gmail, Drive and Docs reads work.
  - Through the daemon, "inbox" in the message turned on `+google`, and the model ran `search_gmail_messages`.
  - Slow point: the model kept paging through more than 100 unread mails to count them. That turn ran while another session was sending a 44k-token prompt, so it was very slow and was stopped.
  - A real send was not tested live. The always-ask rule is covered by the tests.

**Split into three entries (2026-10-15).** Every Google word used to load all 18 tools, about 40,000 characters of schema. Now there are three catalogue entries, `gmail`, `drive` and `docs`. They run the same `workspace-mcp` command and permissions and share one token, and each has its own allowlist and triggers. The process only opens port 8000 for a sign-in, so several can run at once. Backup of the old config: `~/.config/dl-ai/mcp.json.bak-20261015`.

| Entry | Tools (plan mode) | Prompt tokens added | Always asks |
|---|---|---|---|
| gmail | 12 (7) | 5,304 | `send_gmail_message` |
| drive | 15 (8) | 6,222 | `manage_drive_access`, `set_drive_file_permissions`, `update_drive_file` with `trashed` |
| docs | 14 (6) | 4,701 | none (writes ask, `/yolo` skips) |

Measured on qwen3.8-flash-next-coder-iq1_m (RX 7600 XT) as `prompt_tokens` for "hello" with only that entry's tools; the same request with no tools is 53 tokens. Shortening the descriptions would save only about 26% and would drop guidance the model needs (for example "sends immediately"), so they are kept.

Left out, from the server's 49 tools: `batch_update_doc` (26,000 characters of schema), `update_paragraph_style`, the `debug_*` tools, Slides import, the thread batch read and doc tabs and headers.

Local files: a mail attachment `path`, a Drive `file_path` or a `file://` URL is refused when the file is in `~/.config/dl-ai`, `~/.ssh` (and similar) or `wiki/private`, when it is an env or key file, or when its content holds a stored credential (`dl_mcp.file_leak`).

**Gotchas:**
- The OAuth client is a **Web application**, not a Desktop app. It needs the redirect URI `http://localhost:8000/oauth2callback`. Google took several minutes to apply a new URI (`redirect_uri_mismatch` until then).
- A personal Gmail account can't use an "Internal" audience. The app has to be **External** and set to **In production**: unverified is fine (you get a warning screen, and the cap is 100 users). In "Testing", sign-in fails with 403 unless the account is a test user, and tokens expire after 7 days.
- When waiting for the token file, skip `oauth_states.json`, which is written first.
- **Open risk:** the `@file` guard (`is_sensitive_file`) does not cover `~/.config/dl-ai/`. A `run_command` like `cat ~/.config/dl-ai/google/*.json` would show the refresh token to the model. The approval gate only asks about destructive commands, not reads. The user chose not to block it (2026-10-15): the model runs locally on their own PC, so the token doesn't leave the machine.
- **Credential filter (2026-10-15)**, so a token can't leave or land in a file:
  - `dl_auditing.find_known_secrets` compares text against the real stored values: every value in `secrets.env`, environment variables whose name has KEY, TOKEN, SECRET or PASSWORD, and the token fields in `~/.config/dl-ai/google/*.json`. It also checks the URL-decoded text. The files are read fresh on each check.
  - It also has new patterns for Google (`GOCSPX-`, `ya29.`, `1//0…`) and DeepL Free keys (`…:fx`).
  - `McpRegistry.leak` checks every string argument of every MCP call: email, Drive and Docs text, fetch URLs, typed browser text. A hit is refused **before** the approval card. `write_to_file` and `replace_file_content` use the same check through `scan_secrets_in_text`; `*.env` files are exempt from the value check.
  - Measured: all 12 stored credentials are caught, as-is and URL-encoded. None of the repo's 1,895 tracked text files is flagged.
  - Not covered: files written by `run_command` (`echo > file`, `curl`), and a value that is base64-encoded or split into pieces.

## Related

- [D.L. CLI On-Demand MCP Loading Plan](dl-cli-on-demand-mcp-plan.md) (split from this page on 2026-10-15)

## Sources

1. User, chat, 2026-10-13.
2. Code read: tools/dl_cli.py (DL_TOOLS, get_active_tools, call_context7_mcp_raw, run_agent_turn), 2026-10-13.
3. DeepL Pro service specification, https://www.deepl.com/en/pro-service-specifications
4. workspace-mcp, https://mcpservers.org/th/servers/taylorwilsdon/google_workspace_mcp; Google Workspace agent tools, https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html; Gmail MCP has no send, https://vorplabs.com/agent-tools/gmail-mcp
5. LibreTranslate, https://github.com/LibreTranslate/LibreTranslate; forum report https://discuss.techlore.tech/t/a-new-forum-feature-demo-beta/12347?page=2
6. Implementation plan: ~/.claude/plans/create-a-detailed-implementation-quirky-meadow.md (Claude Code, 2026-10-13); implemented 2026-10-13 to 2026-10-15.
