---
title: "Scheduled Jobs in D.L. AI"
type: decision
description: "The session daemon runs prompts or one exact pre-approved action at a time or on repeat; model warm-up, retries, catch-up, notices"
status: active
tags: [cli, schedule, daemon, proton]
created: 2026-10-15
updated: 2026-10-17
last_verified: 2026-10-15
---

# Scheduled Jobs in D.L. AI

## Summary

- 2026-10-15: D.L. AI can run work at an exact time or on repeat. The scheduler (`tools/dl_schedule.py`) runs inside the session daemon (`dl-ai-sessiond`), so it does not depend on the model being loaded or on the Strata server being up.
- **Approval (the user's choice: approve when scheduling):**
  - An **action job** (`{tool, args}`, e.g. `proton__send_mail` with exact To/Subject/Body) is approved on the card when it is scheduled. The card shows every argument and always asks, even in YOLO. At the time it runs exactly so, without the model.
  - A **prompt job** runs the agent in its own session (`dl-ai-schedule`). Anything it decides to do on its own asks on the Code tab's card, marked `[scheduled job #N]`, and the user also gets an email saying it waits. Unanswered after 30 minutes means no.
  - Typing `/schedule …` needs no card; adding through the model's `schedule__add` asks (YOLO skips it for a prompt job).
- **Model unloaded:** `POST /v1/load` `warmup_s` (180 s) before a prompt job. Cold load was about 60 s (measured 2026-10-05).
- **Server down:** `/health` is checked first and retried every minute for `retry_min` (30). Then the job fails and a notice email goes out.
- **Dropped half-way:** a job that only used read-only tools runs once more after the server is back; one that may have acted is marked `interrupted` and not run again.
- **PC or daemon off:** a missed job runs once at the next start ("late by N min"); a repeating one runs once, not once per missed time. More than `max_late_h` (12) late, counted from the last missed run, is skipped and reported.
- **Results:** posted to the Code tab (`⏰ Scheduled job #N: ok`); with `email_result` (`/schedule --email …`) also emailed. Notices and results go from the Proton identity (dl-ai-agent@) to `notify_email` (info@damir-lukina.com) in `~/.config/dl-ai/schedule.json`.
- **Keeping the daemon up:** drop-in `dl-ai-sessiond.service.d/restart.conf` sets `Restart=always`; the watchdog starts it when it is not running and restarts it after 3 failed `{"op": "state"}` probes on its socket.
- **Live check (2026-10-15 21:14):** `/schedule in 1m …` ran on time; the answer appeared in the Code tab and the job ended `ok`.

- 2026-10-15 (later), after the weather-email session (`~/Desktop/dl-ai-code-chat-2026-10-15-21-44.md`):
  - **A time that passed while the agent worked runs at once**, never tomorrow: `parse_when` takes `anchor` = when the user asked (set per turn in `dl_mcp.CALL`). A time still ahead then but past now becomes `{"at": now, "planned": <asked time>}`; the result says "planned 21:30, already passed: runs at once, 7 min late". A bare HH:MM already past when the user asked still means tomorrow; a past date is an error. The rule is also in the `schedule__add` description, so the model does not deliberate over it.
  - **Late scheduled emails say so** (the user's choice): `add_late_note` puts "Planned for 21:30, sent at 21:37 (7 min later than planned)." at the top of the body and the HTML, translated by DeepL into the email's own language (detected); English if DeepL is unreachable.
  - **Croatian date format** in listings and input: `pet 16.10.2026. 21:30`; input also takes `16.10.2026. 21:30`, `16.10. 21:30`, `sutra`, `danas`, `za 2h`, `pon`…`ned`.
  - **Scheduled actions are checked when scheduled:** the tool must be on and every parameter must exist (the weather email's `html_body` did not, and was silently dropped).
  - Jobs remember `yolo` from the turn that created them.

- **Testing gotcha (2026-10-15, audit round 14):** the tool registry calls the built-ins as loaded by dl_cli (`tools.dl_proton`, `tools.dl_schedule`, `tools.dl_translate`), not the `dl_*` copies a script imports from `tools/` on sys.path. A fuzz run that patched only the `dl_*` copies reached the real Proton Bridge: 4 empty drafts in Drafts (UIDs 60-63, 23:46) and one send refused by Bridge ("invalid return path", made-up sender). Patch the registered module (`dl_mcp.BUILTINS[name][1].__module__`) and replace `imap_connect`/`smtp_connect`/`_post`/`STORE` with fakes before any registry fuzzing.
- 2026-10-17: Resolved persistent SMTP 454 and IMAP "no such user" failures in Proton Bridge. At system boot, `protonmail-bridge.service` had started before desktop keyring (`SecretService`) unlock, leaving the vault unencrypted with 0 active accounts loaded in memory. The watchdog (`tools/strata-watchdog.sh`) was upgraded from a superficial TCP port ping to an authenticated IMAP probe (`dl_proton.imap_connect`); on boot when the keyring is initially locked, the watchdog automatically restarts Bridge once the user logs in and unlocks the desktop keyring.

## Usage

- `/schedule [--email] <when> <task>`, `/schedule list`, `/schedule off|on|run|rm N`.
- `when`: `2026-10-16 09:00`, `09:00`, `today 18:30`, `tomorrow 07:00`, `fri 09:00` (once); `daily 08:00`, `weekdays 07:30`, `mon-fri 07:30`, `every mon,wed 18:00`, `every 2h` (repeating). Local time, 24-hour.
- In chat: the on-demand built-in `schedule` (mcp.json `{"builtin": "schedule"}`) turns on for "remind", "schedule", "every morning", "tomorrow at", "podsjeti", "zakaži", "svako jutro", "erinnere", "jeden Morgen" …
- Jobs: `~/.local/state/dl-ai/schedule.json` (mode 600).

## Related

- [Shared CLI Session Daemon for Web and Terminal](shared-cli-session-daemon.md)
- [D.L. CLI On-Demand MCP Loading Plan](../artifacts/dl-cli-on-demand-mcp-plan.md) (Proton Mail, the approval cards)
- [Approval Gate for Destructive Agent Actions](destructive-action-approval-gate.md)

## Sources

1. User, chat, 2026-10-15: scheduling on a timer or at an exact time; "approve when scheduling"; what happens when the model is unloaded or the server is down.
2. `tools/dl_schedule.py`, `tools/test_dl_schedule.py` (18 tests), `tools/dl_sessiond.py` (JobRunner, /schedule), 2026-10-15.
