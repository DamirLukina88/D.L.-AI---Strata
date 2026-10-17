---
title: "D.L. CLI On-Demand MCP Loading Plan"
type: artifact
description: "Plan: one small mcp tool lets D.L. CLI load Fetch, Playwright, Google (Gmail/Drive/Docs) and translation MCP servers only when needed"
status: active
tags: [plan, cli, mcp, tools, prefill]
created: 2026-10-13
updated: 2026-10-15
last_verified: 2026-10-15
---

# D.L. CLI On-Demand MCP Loading Plan

## Status (2026-10-15)

**Built and live** for Fetch, DeepL, Playwright and Google (Google since 2026-10-15, see [Google: live setup](#google-live-setup-2026-10-15)).
- Code: `tools/dl_mcp.py` (registry, router, allowlist, approvals), hooks in `tools/dl_cli.py` and `tools/dl_sessiond.py`, chips and the mail approval card in the web Code tab, opt-in `env_inherit` in `serve/mcp.py`. Tests: `python tools/test_dl_mcp.py` (21), plus `serve.test_mcp`, `test_dl_sessiond`, `test_dl_auditing` all green.
- Config: `~/.config/dl-ai/mcp.json` (mode 600). Python servers live in `~/.local/share/dl-ai/mcp-venv`, npm servers in `~/.local/share/dl-ai/mcp-npm`. Pinned versions: mcp-server-fetch 2026.8.18, deepl-mcp-server 1.3.10, @playwright/mcp 0.0.82.
- Detailed plan: `~/.claude/plans/create-a-detailed-implementation-quirky-meadow.md`.

**Measured prompt size** (qwen3.8-flash-next-coder-iq1_m on the RX 7600 XT, request "hello", max_tokens 1, no prefix cache):

| Tools offered | Prompt tokens | Wall time |
|---|---|---|
| Today's 8 tools (no MCP) | 1,760 | 8.8 s |
| + `mcp` switch | 1,912 (+9%) | 8.7 s |
| + Fetch | 2,212 | 10.7 s |
| + DeepL (2 tools) | 2,839 | 12.4 s |
| + Playwright (14 tools) | 5,005 | 16.9 s |

Because of this, Fetch is **not** on by default (that would be +26%). A URL or `www.` in the message turns it on.

**Live checks through the daemon:**
- "Prevedi na njemački, neformalno: …" turned on `+deepl`, and the model sent `sourceLangCode: hr` and `formality: less` itself → "Bitte schick mir den Bericht bis Freitag."
- A URL turned on `+fetch`.
- "click the 'Learn more' link" turned on `+playwright`: navigate and snapshot ran without asking, and the click asked first.

**Gotchas:**
- Playwright MCP 0.0.82 needs `--browser chromium` and its own build: `playwright-mcp install-browser chrome-for-testing` (about 190 MB in `~/.cache/ms-playwright/chromium-1246`). Without `--output-dir` and `cwd`, it writes `.playwright-mcp/` snapshots into the current folder. Both now point at `~/.cache/dl-ai/playwright`.
- `browser_navigate` only links a snapshot file; the model then calls `browser_snapshot`, which returns the page inline.
- An old `STRATA_API_KEY` exported in the interactive shell overrides `secrets.env` (`load_env_file` lets the environment win). The systemd daemon is not affected.
- DeepL guesses Bosnian for short Croatian text unless `sourceLangCode` is given.

## Goal

Add MCP servers to D.L. CLI without growing the prompt. Each tool's schema is resent on every turn, and the local model pays for it in prefill time (see [Pruned Core Tools](../decisions/pruned-core-6-tools-and-8h-keepalive.md)). So only a few small tools stay loaded, and a server's tools appear only after the model asks for them.

## What the code does today (tools/dl_cli.py)

- `DL_TOOLS` has 9 tools, not 6: the 6 core ones plus `exa_web_search`, `resolve_library_id` and `get_library_docs`.
- Context7 is called by `call_context7_mcp_raw`: it starts `npx @upstash/context7-mcp` for each call, sends `initialize` and `tools/call`, then kills the process. It skips the `notifications/initialized` message.
- `run_agent_turn` asks `get_active_tools(ws, mode)` again after each tool call (around line 1235). That is the hook for adding and removing tools mid-conversation.
- `tools/antigravity_local.py` is a near-copy of `dl_cli.py`. Decide whether it gets the change too or stays as it is.

## Design

1. **`tools/dl_mcp.py`** (new, standard library only): a small stdio MCP client.
   - `McpServer`: starts the process once, does `initialize` plus `notifications/initialized`, `tools/list`, `tools/call`, with a timeout on every read. Reads stderr in a thread so the pipe can't fill up and block the process.
   - `McpRegistry`: reads `~/.config/dl-ai/mcp.json` (name, command, args, env names, description, `default: on|off`). Keys come from `secrets.env`, never from the JSON file.
   - Running servers are kept per session and closed on exit or `/mcp off`. An idle timeout (10 min) stops servers that aren't in use, such as Playwright with its browser.
   - Tool names get a prefix, `fetch__fetch` or `playwright__browser_navigate`, so they can't clash with core tools.
   - `MCP_TOOL_LIMIT` caps the tools loaded at once (default 25). Above the cap, the oldest server is unloaded first.
2. **One always-on meta tool `mcp`**, kept small:
   - `mcp(action="list")` returns each server's name and one-line description, without schemas.
   - `mcp(action="enable", server="playwright")` starts the server. Its tools join `active_tools` on the next model call.
   - `mcp(action="disable", server=...)` unloads it.
2b. **Automatic choice (user asked for it, 2026-10-13), in two layers:**
   - **Router before each model call** (no extra model turn): each server in `mcp.json` has `triggers`, which are keywords and regexes in English, Croatian and German. For example, Google gets `email|mail|pošalji|e-pošt|Drive|Docs|dokument`, DeepL gets `translate|prevedi|prijevod|übersetz`, Fetch gets a URL in the message, and Playwright gets `click|log in|prijavi|website form`. A match turns the server on before the model call. The model's own judgement wins: what the router turns on is only offered, never run without the model choosing it.
   - **Fallback**: the `mcp` meta tool's description lists the catalogue (one line per server), so the model can still turn a server on when the router misses one. That costs one extra round.
   - **Auto off**: a server whose tools went unused for 3 user turns is turned off again, so the prompt shrinks back down.
   - Show what happened in the terminal and web chips ("+google (router: 'pošalji')"), so wrong matches are easy to see. Log the hits and misses, then improve the triggers.
   - Later, if keywords miss too much: score the message against the one-line descriptions with a small embedding model on the CPU. Only add this if the logs show misses.
3. **`get_active_tools`** = core tools + `mcp` + tools of enabled servers. In plan mode, only read-only tools are offered (Fetch yes, Playwright no, or Playwright without click/type).
4. **`dispatch_dl_tool`**: a name containing `__` goes to the registry.
5. **Approval gate**: Playwright actions that submit or click go through the existing [approval gate](../decisions/destructive-action-approval-gate.md).
6. **Slash commands**: `/mcp` lists servers and their status, `/mcp on NAME`, `/mcp off NAME`. The web Code tab shows the active servers as chips, like the existing Exa/Context7 chips.
7. Later and optional: move Context7 onto `dl_mcp.py` (one process per session instead of one per call). It stays as it is in the first pass.

## Servers

| Server | Loaded | Size | Notes |
|---|---|---|---|
| Fetch (`mcp-server-fetch`, Python) | on by default | 1 tool | `uvx` is not installed. Use `pip install mcp-server-fetch` into a venv and run `python -m mcp_server_fetch`. |
| Playwright (`@playwright/mcp`, npx) | only on demand | about 20+ tools | `--headless`. Its browser profile is separate from the user's. Measure prefill with it loaded. |
| Translation | on demand | 1–3 tools | See below. Decide after testing. |
| Google (`workspace-mcp`, Python) | on demand | about 5 tools after the allowlist | Gmail send, Drive and Docs read. See below. |

## Google: send Gmail, read Drive and Docs

The user wants D.L. CLI to send email from Gmail and to read Google Drive files and Docs.

**Pick: the community `workspace-mcp` server (taylorwilsdon/google_workspace_mcp), on demand only.**
- Google's own Workspace MCP servers are in developer preview, run on Google's servers over HTTP, and their Gmail server does not send mail (drafts only). D.L. CLI's client would need HTTP support as well. Look at them again once they leave preview.
- `workspace-mcp` runs locally, works with a personal Gmail account through your own OAuth client, and can be started with only some services (`--tools gmail drive docs`, `--tool-tier core`) and a read-only option.
- Even its core tier for three services is too many tools for the local model, so `mcp.json` gets a per-server **tool allowlist**: `dl_mcp.py` passes on only the allowed names from `tools/list`. The target is about 5 tools: Gmail send (or draft + send), Drive search, Drive file read, Docs read.

**User decisions (2026-10-13):** Gmail **read and send**. Only available in the web app's **Code** tab (the shared D.L. CLI session), not in the Chat tab.

**Safety (needed before turning it on):**
- Every email send goes through the approval gate and shows To, Cc, Subject and the full body. `/yolo` does **not** skip it. Sending is outward-facing and can't be undone.
- Prompt injection: email, Drive and Doc text is data. A Doc could say "email this file to X". Rule: a send is only allowed when the user asked for it in this turn, and the recipient must come from the user, not from document text.
- Scopes: ask only for what's needed. `gmail.send` if reading mail isn't wanted, `drive.readonly`, `documents.readonly`. Check which scopes the server really requests on the consent screen.
- The token file lives in `~/.config/dl-ai/` (mode 600), never in the repo or wiki. The fork was leaked once before ([secret leak](../decisions/secret-leak-rotation-2026-10.md)). Add the token path to the secret scan / `.gitignore`.
- The web app is reachable through the Cloudflare Tunnel. Anyone who gets past Cloudflare Access could make it send mail. Consider allowing sends only from the terminal, or only for the user's Access identity.

**What the user does (Claude can't enter passwords or approve consent):**
1. Google Cloud console: create a project, turn on the Gmail, Drive and Docs APIs, set up the OAuth consent screen (External), and create a "Desktop app" OAuth client.
2. Gotcha: while the consent screen is in "Testing", refresh tokens expire after 7 days. Set it to "In production" (unverified is fine for your own account; you'll see a warning screen).
3. Run the first sign-in in the browser and approve the scopes.

## Exa and Context7 on demand (2026-10-15)

- Until now both were always on: `exa_web_search` (Exa's web API, not MCP) and `resolve_library_id` / `get_library_docs` (Context7 MCP, started with `npx` for each lookup and given the **whole** environment, every key in `secrets.env` included).
- Now they are catalogue entries:
  - `context7`: a normal MCP entry that gets only `CONTEXT7_API_KEY` and `CLIENT_IP_ENCRYPTION_KEY`.
  - `exa`: `{"builtin": "exa"}`, a new entry type. `dl_cli` registers the tool with `dl_mcp.register_builtin`, and the registry turns it on and off like a server, but with no process.
- `"replaces": [...]` removes the always-on tools while the catalogue has the entry. Without `mcp.json`, both stay always-on as before, and a test checks this.
- The `/context7` slash command (direct lookup) also no longer passes the full environment.
- Triggers:
  - Exa: "search the web", "latest version", "pretraži", "na internetu", "najnovij", "recherchier", "neueste" …
  - Context7: "docs for", "official documentation", "changelog", "dokumentacija za" …
  - The model can also turn either on with `mcp`.
- **Measured** (`prompt_tokens` for "hello" with the act tools, coder iq1_m, RX 7600 XT): 1,523 before (8 always-on tools + `mcp` switch) → 1,122 now (6 tools incl. the switch), **−401 tokens (−26%) on every model call**.
- `dl_mcp` can be loaded twice (as `dl_mcp` and `tools.dl_mcp`); `BUILTINS` is shared between the two copies, or a built-in registered in one copy is invisible to the other.

## Google: live setup (2026-10-15)

Moved to [Google Workspace MCP Live Setup for D.L. CLI](google-workspace-mcp-live-setup.md): tools, the gmail/drive/docs split and its token costs, approvals, the token location, the credential filter and its gaps.

## Proton Mail (2026-10-15)

- **Bridge:** `protonmail-bridge-core` 3.27.1 (Arch extra), run as the packaged user unit `protonmail-bridge.service` (`--noninteractive`), IMAP STARTTLS on 127.0.0.1:1143, SMTP on :1025. Bridge needs a paid Proton plan. A drop-in (`protonmail-bridge.service.d/dl-ai.conf`) sets `StartLimitIntervalSec=0`, so it keeps retrying while the keyring is still locked after boot. Linger is on, so it starts with the OS.
- **Built-in, not an MCP package:** `tools/dl_proton.py`, standard library only, registered as `{"builtin": "proton"}`. No outside code sees the Bridge password. `PROTON_BRIDGE_USER` / `PROTON_BRIDGE_PASSWORD` are read fresh from `secrets.env` on each call (no restart needed); only a loopback host is accepted; Bridge's certificate is pinned from `~/.config/protonmail/bridge-v3/cert.pem` when it exists.
- **Tools (7):** read-only `search_mail`, `read_mail` (BODY.PEEK: does not mark read), `get_attachment` (text only), `list_folders`; `ask`: `draft_mail`, `update_mail` (move, read, starred; Trash and Spam refused: the user chose no deleting); `ask_always`: `send_mail`. Only in the Code tab / `--attach` (`surfaces: ["code"]`).
- **Identity:** the user has five addresses on the account (default info@). The agent always sends as `dl-ai-agent@damir-lukina.com`: `fixed_args.from_address`, hidden from the model, shown on the approval card. Bridge does not add the Proton signature, so `dl_proton` appends `~/.config/dl-ai/proton-signature.txt` (the user's agent signature) to sends and drafts. The signature in Proton's settings is only added by Proton's own apps, not to mail sent through Bridge, so the file has to be kept the same as the settings text by hand (verified 2026-10-15: the test mail carried only the file's signature). Reading covers the whole account (Bridge combined mode); Bridge's split-address mode would limit it to the agent's own mailbox.
- **Routing:** the generic mail words (mail, e-mail, inbox, pošalji, e-pošta, Posteingang …) now turn on `proton`; `gmail` only turns on for "gmail" / "google mail". New catalogue field `unless`: Proton's triggers are skipped when the message names Gmail.
- **Measured** (`prompt_tokens` for "hello", coder iq1_m, RX 7600 XT): 79 with no tools, 1,256 with Proton's 7 tools, **+1,177** (Gmail: +5,251).
- **Watchdog:** `tools/strata-watchdog.sh` now also starts Bridge when its unit is enabled but not running, and restarts it after 3 failed IMAP greetings (30 s apart). The watchdog unit no longer `Requires=strata-server` (that had left it dead since a server restart at 20:00 on 2026-10-15); it skips the Strata check while the server is stopped on purpose.
- **Live check (2026-10-15 20:57):** Bridge signed in (IMAP user info@damir-lukina.com; the password is `PROTON_BRIDGE_PASSWORD` in private/.env and secrets.env), service enabled at boot. `list_folders` returned 12 folders; a test mail sent as dl-ai-agent@ to info@ arrived in INBOX with the signature. Bridge has no `cert.pem` in `bridge-v3`, so the certificate is not pinned (loopback only). Gotcha: Bridge locks the login for a while after a few wrong passwords ("too many login attempts").
- **Setup left to the user:** sign in once in `protonmail-bridge-core --cli` (`login`, then `info` for the Bridge password), put the two keys in `secrets.env`, then `systemctl --user enable --now protonmail-bridge`. To sign in again later, `disable --now` first, or the watchdog restarts the service under the CLI.

## Lessons from the weather-email session (2026-10-15)

Transcript: `~/Desktop/dl-ai-code-chat-2026-10-15-21-44.md` (search, hourly table, Croatian translation, Google Sheet, email at 21:30).
- **DeepL was right, the model ruined it:** DeepL returned correct Croatian; the model "corrected" it into invented words mixed with English and never put the translated labels into the table. Fix: the built-in `deepl` (`tools/dl_translate.py`, stdlib, replaces deepl-mcp-server): one call per whole text, `html=true` keeps tables (`tag_handling=html`), `file` -> `out_file` so the translation is never retyped; the result says "use exactly as is". Prompt rule: translate the finished text in one call, never edit DeepL's output, never mix languages. Live check: an HTML table email EN->HR came back correct with the table intact (DeepL wrote one decimal as `6,6`, the next as `6.8`).
- **Unknown parameters were silently ignored** (`html_body` on Proton): `McpRegistry.unknown_args` now refuses any parameter not in the tool's schema and lists the real ones. Proton `send_mail`/`draft_mail` take `html` and `html_file` (multipart, plain part made from the HTML, signature in both).
- **"Me" was guessed** (the Drive owner's Gmail): `~/.config/dl-ai/profile.json` (name, email info@damir-lukina.com, Europe/Zagreb) adds a `<user_profile>` block: "me" = that address; dates in Croatian format. +135 prompt tokens (679 -> 814 for "hello", coder iq1_m, RX 7600 XT). Every user message starts with `[Now: četvrtak, 15.10.2026. 21:17 (Europe/Zagreb)]` (not in the system prompt, so the conversation cache still works).
- **Tools dropped out:** `max_tools` 25 -> 45 (Drive alone is 15). New routing words: exa "online search", "weather", "forecast", "prognoz", "vremensk"; drive "google sheets", "spreadsheet", "tablic". The transcript's request now turns on exa, deepl, proton, drive and schedule at the start (27 tools). `mcp(enable)` takes several servers ("drive,proton").
- Fetch runs with `--ignore-robots-txt` (open-meteo's API was refused); Google servers get `ALLOWED_FILE_DIRS=/mnt/data/DL-AI-workspace:~/.workspace-mcp/attachments` (Drive refused workspace files).

### Live re-runs of the weather email (2026-10-15, 22:28-22:56, coder iq1_m, RX 7600 XT, YOLO on)

- **Run 1** (effort medium): after the weather data the model repeated the same 6-step plan in its thinking for 7,065 tokens (196 s, no tool call) until the user stopped it. Strata's opt-in `"reasoning_loop_recovery": "recover"` (#728) was off; it is now on in `strata-coder-iq1_m.json` (checks every 512 tokens; on a repeat it continues with the low-effort instruction, temperature >= 1.0, presence penalty >= 1.5). It did not have to trigger in runs 2-3.
- **Run 2** (medium, 495 s): the DeepL file-to-file flow worked and the Croatian file was correct, but: the credential filter treated `PROTON_BRIDGE_USER` (info@) as a secret and blocked the email to the user (fixed: names like `*_USER`/`*_EMAIL`/`*_HOST` and email-address values are not credentials); the subject was written by hand, mixed EN/HR (fixed: send_mail takes the subject from the HTML `<title>`, which DeepL translates); the model invented coordinates in the Italian Alps (45.74, 11.11; 1,475 m) and claimed a BBC cross-check it never made. Its job was removed.
- **Run 3** (effort switched to high by the user at 22:47, 587 s, no approval asked): correct coordinates (45.81, 15.98), the whole email in Croatian via two DeepL file translations, subject from the translated title, exact action job #6 to info@ for pet 16.10.2026. 09:30. Left over: the sheet name was typed by the model ("Satna prognoz", a typo); a relative `file_path` for the Drive import resolved against `~` (the model retried with an absolute path). The longest model call: 5,339 tokens in 184 s, building the HTML table.
- Found while previewing run 3's email: the plain-text part ran table cells together, and a bare `<table>` showed without lines; Proton now writes "a | b | c" rows and adds a simple grid style.

## Translation: Croatian, English, German

- **Chosen: DeepL** (user, 2026-10-13). Official server `deeplcom/deepl-mcp-server` via npx, `DEEPL_API_KEY` in `secrets.env`. Allowlist: translate text + target languages. The Free key ends in `:fx` and uses `api-free.deepl.com`.
- **Tested 2026-10-13 with the user's Free key:** HR, DE, EN-GB and EN-US are all target languages. EN→HR translates correctly. HR→DE detected the source as Bosnian (BS) while the output was still right, so always send `source_lang` when it's known (HR). German has a formality option (`formality: less` gives "du"); "molim te" came out as "Sie". The account's limit shows 1,000,000 characters (not 500k).
- DeepL lists Croatian (HR) among its supported languages, alongside English and German. The search did not confirm that Croatian works as a target language through the API. Test that on the Free plan (500k characters a month, needs a key) before choosing it.
- LibreTranslate / Argos: a forum report says Croatian is not supported. Check `/languages` on a running instance. If it's still missing, LibreTranslate is out.
- Lara Translate: not checked.
- Fallback with no extra service: the local Qwen model translates on its own.

## Steps

1. `dl_mcp.py` + `tools/test_dl_mcp.py` (a fake MCP server script, no network).
2. The `mcp` meta tool, `get_active_tools` and dispatch, `/mcp` slash commands.
3. Install Fetch and turn it on by default.
4. Playwright on demand, with the approval gate.
5. Measure: prompt tokens and time to first token with core tools only, + Fetch, + Playwright, on the RX 7600 XT.
6. Translation: try DeepL with Croatian, then pick one.
6b. Google: the user sets up the OAuth client; install `workspace-mcp` into a venv; allowlist; email approval with no `/yolo` bypass; test reading a Doc and sending a mail to the user's own address.
7. Web Code tab chips; update the wiki.

## Open questions

- Should the meta tool also offer a `search` action once there are many servers?
- Should `antigravity_local.py` get the same change?

## Sources

1. User, chat, 2026-10-13.
2. Code read: tools/dl_cli.py (DL_TOOLS, get_active_tools, call_context7_mcp_raw, run_agent_turn), 2026-10-13.
3. DeepL Pro service specification, https://www.deepl.com/en/pro-service-specifications
4. workspace-mcp, https://mcpservers.org/th/servers/taylorwilsdon/google_workspace_mcp; Google Workspace agent tools, https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html; Gmail MCP has no send, https://vorplabs.com/agent-tools/gmail-mcp
5. LibreTranslate, https://github.com/LibreTranslate/LibreTranslate; forum report https://discuss.techlore.tech/t/a-new-forum-feature-demo-beta/12347?page=2
6. Implementation plan: ~/.claude/plans/create-a-detailed-implementation-quirky-meadow.md (Claude Code, 2026-10-13); implemented 2026-10-13 to 2026-10-15.
7. User, chat, 2026-10-15: Proton Mail as a mail option, identity dl-ai-agent@, start with the OS, add to the watchdog.
