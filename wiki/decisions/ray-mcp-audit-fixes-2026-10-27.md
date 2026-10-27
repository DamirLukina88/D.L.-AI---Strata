---
title: "Ray MCP Audit Fixes (2026-10-27)"
type: decision
description: "DeepSeek approval card, live identity and fuel data, sourced Zagreb data, faster Stop, Code tab stream watchdog, privacy pre-commit"
status: active
tags: [ray, mcp, deepseek, web-app, scheduler, privacy]
created: 2026-10-27
updated: 2026-10-27
last_verified: 2026-10-27
---

# Ray MCP Audit Fixes (2026-10-27)

## Summary

User decisions, 2026-10-27: (1) DeepSeek asks on a card before every call (mcp.json ask + ask_reason + ask_full_args shows the whole prompt); the user can type /mcp trust deepseek to stop asking for the session, /mcp ask deepseek to undo; the model's mcp tool cannot do this. The server reads only DEEPSEEK_API_KEY handed over by env_from_secrets; that key is not in secrets.env yet. (2) Machine paths and the user's email stay out of git: code now derives paths (Path.home(), the checkout's parent folder) and User-Agents name the repository; the pre-commit hook blocks added lines with the home path, the checkout's parent folder or the profile email. The wiki itself and the git history still carry them (open). (3) Hardcoded civic data is checked against public sources: fuel prices are read live from the Ministry of Economy register (webservis.mzoe-gor.hr/data.gz, median per grade; matched the 20.10.2026 decree: ES95 1.73, ED 1.88, plavi 1.44); Zagreb pharmacies from the City of Zagreb list (page dated 20.10.2025; Ilica 291 not 301, Ljekarna ZEUS added, day 7-20 / night 20-7); ZET line ends from ZET GTFS feed 000397 (14 and 33 were wrong); the invented per-district waste schedule was removed (Cistoca schedules by address). (4) /effort default means auto. (5) ray_identity reads hardware, engine settings, address and services when called (it said 0.0.0.0 and 2,560 MiB; real: 127.0.0.1, 3,584 MiB). Also: Stop now shuts the model request socket at once (measured 1.0 s against a silent server, was up to the next 10 s heartbeat); the Code tab reconnects a dead event stream (40 s of silence, or no event 5 s after Clear/Stop/a prompt), which was why Clear and Stop looked unresponsive until a tab switch. All 27 new MCP servers no longer reply to notifications, answer ping, and set isError. The AMS run-out watcher (job 14) missed the 01:07 run-out because the AMS Lite kept reporting the untagged spool as loaded; the script now also fires on extruder_filament on->off during a print. A job-14 run (an agent prompt with YOLO) then removed that rule itself and generated 28,192 tokens over 503 s, blocking the engine; job 14 was paused.

## Sources

1. User, chat, 2026-10-27: answers 1-5 to the Ray MCP audit questions, and the reports on the missed AMS email and slow Clear/Stop.
