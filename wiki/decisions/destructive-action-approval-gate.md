---
title: "Approval Gate for Destructive Agent Actions"
type: decision
description: "D.L. CLI asks before destructive commands or writes outside the workspace; /yolo disables per session; content never restricted"
status: active
tags: [cli, guardrails, security]
created: 2026-10-13
updated: 2026-10-15
last_verified: 2026-10-13
---

# Approval Gate for Destructive Agent Actions

- 2026-10-15: **YOLO is fully autonomous** (the user's decision, replacing "Gmail sending always asks, even in YOLO"): in YOLO nothing asks from the start to the end of a request, sending email and sharing Drive files included. YOLO is saved with the session (survives daemon restarts) until `/yolo` turns it off, and jobs scheduled while it is on run without asking too. Outside YOLO the cards stay as they were. The credential filter is not a confirmation and still blocks. See [Scheduled Jobs in D.L. AI](dl-ai-scheduled-jobs.md).

## Summary

- 2026-10-13: The user runs an uncensored model and wants no guardrails except against data leaks and unauthorised destructive actions. The prompt had no content restrictions, but run_command had no protection at all.
- tools/dl_auditing.py classify_command / classify_write flag: rm -r/-f, find -delete, sudo/doas/su, dd/mkfs/wipefs/parted, chmod/chown -R, git push --force / reset --hard / clean -f / branch -D / filter-repo / rebase, systemctl stop/disable/restart, kill -9/pkill, curl|sh, package removal, redirects/copies/writes outside the workspace (except /tmp, /dev/null).
- dispatch_dl_tool asks the approver (terminal y/N, or the web Approve/Deny card via the session daemon); a denial returns 'Denied by user' to the model. /yolo turns it off for one session.
- Plan Mode now ends with 'Execute this plan?'; yes switches to Act Mode and runs it (user choice). Kept as they were: scan_secrets and syntax_guard on writes (blocking), the sensitive-file guard, workspace path checks.

## Sources

1. User, chat, 2026-10-13.
