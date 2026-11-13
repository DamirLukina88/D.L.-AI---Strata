---
name: verify
description: How to see a change to Ray (tools/dl_cli.py, tools/dl_sessiond.py), the shared memory store (tools/dl_memory.py) or the web app (serve/) working at runtime without touching the live services, the real store or the loaded model.
---

# Verifying Strata / Ray changes at runtime

Never drive the live `dl-ai-sessiond` or `strata-server` for a check: they hold the user's conversation and the one
GPU model. Run isolated copies instead.

## Session daemon (Ray's tools, slash commands, approval cards)

1. A fake engine on a spare port that streams a fixed answer (and, for a marker word in the prompt, a tool call),
   logging the `reasoning_effort` / tool results it receives. Keep it in the scratchpad, not the repo.
2. Start `tools/dl_sessiond.py` with `env -i` and: a temp `HOME`, a **short** `XDG_RUNTIME_DIR`
   (Unix socket paths over ~107 bytes fail with "AF_UNIX path too long"; use e.g. `/tmp/claude-1000/vfy/run`),
   `STRATA_URL=http://127.0.0.1:<port>`, `STRATA_WORKSPACE_DIR=<a folder>`, `DL_MCP_CONFIG=/nonexistent/mcp.json`
   (or a fake catalogue using `serve/mcp_fake_server.py`), and `RAY_MEMORY_DIR=<temp store>` + `JJ_CONFIG=<file with
   [user] name/email>` + `RAY_JJ_BIN=<jj>`.
3. A socket client: send `{"op":"attach","session":"verify"}`, then `{"op":"input",...,"text":...}` per prompt; read
   events with `select` until ~2.5 s of silence. Answer `approval_request` events with
   `{"op":"approve"|"deny","id":...}`. Don't truncate `output` events when judging them (they are multi-line).
4. The temp HOME has no `~/.local/share/dl-ai/models`, so Model2Vec is off there ("Router: Model2Vec not available"):
   expected, not a bug.

## Memory store

- Test on a copy: `rsync -a --exclude private --exclude .memory/quarantine <store>/ <scratch>/store/`, where
  `<store>` is the `root` in `~/.config/dl-ai/memory.json`,
  then `RAY_MEMORY_DIR=<scratch>/store`. jj warns the repo was copied; harmless.
- CLI: `.venv/bin/python tools/dl_memory.py <cmd>` with `</dev/null`; `setsid -w` removes the terminal, which is how
  an agent's shell looks (global writes must be refused there).
- Hooks: pipe JSON payloads into `dl_memory.py hook claude` (`hook_event_name`, `session_id`, `cwd`, `tool_name`,
  `tool_input`) or `hook antigravity <Event>` (`conversationId`, `workspacePaths`, `toolCall`); set
  `RAY_MEMORY_CACHE=<scratch>` so hook state stays out of `~/.cache`.
- MCP: newline-delimited JSON-RPC on stdin of `dl_memory.py mcp`.
- In zsh, `$CMD args` does not word-split a command held in a variable; use a shell function.

## Not reachable from here

- `claude -p` is not signed in on this machine (the desktop app has its own sign-in), so Claude Code permission rules
  (e.g. the `ask` rule on `memory_write_global`) can only be checked in a fresh desktop-app session.
- Antigravity itself: only its hook and MCP entry points can be driven.

## Web app

`.venv/bin/python serve/server.py --engine strata --config <copy of strata-coder-iq1_m.json with its own "log"> --host
127.0.0.1 --port 18080` with `env -u STRATA_API_KEY`; `lazy_load` keeps the model unloaded. Drive it in the built-in
browser; stub `codeOp` in the page before clicking Apply so `/effort` doesn't reach the live daemon.
