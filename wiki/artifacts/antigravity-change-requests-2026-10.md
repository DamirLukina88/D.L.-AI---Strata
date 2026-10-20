---
title: "Antigravity Change Requests, 5-12 Oct 2026"
type: artifact
description: "The user's 92 change requests to Antigravity for Strata/D.L. AI, newest first; the last three were left unfinished"
status: active
tags: [antigravity, history, requests]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Antigravity Change Requests, 5-12 Oct 2026

Source: Antigravity conversation `44aeb44c…` ("Local Wiki Initialization", workspace `~/Desktop/Strata` → `/mnt/data/Strata`, 215 user turns, 5 Oct – 12 Oct 2026), plus 3 short side conversations from 11 Oct.
Only prompts that asked for a change are listed; questions, "status?" and "continue" turns are left out. Wording is condensed from yours, typos fixed. Secrets that were pasted into prompts are redacted.

## 16-19 Oct — later Antigravity conversations (added 2026-10-20)

Antigravity had no Strata conversation between 12 and 16 Oct. Five conversations from 16-19 Oct touched Strata / D.L. AI. Each topic links to the page that records it; the requests themselves are not repeated here.

- **`b2d3ff29…`** (16 Oct 13:51 – 17 Oct 20:03, 68 user turns):
  - Read-only full-project audit: [Strata Full Project Audit Report](strata-full-project-audit-2026-10-16.md).
  - Benchmark: [Strata v0.1.44.1 Benchmark Report](strata-benchmark-2026-10-16.md).
  - "Services not running after a reboot": they were running; the model only looked idle because of lazy loading. Autostart is linger + `WantedBy=default.target` + `Restart=always` + the watchdog ([Lazy Loading and GUI Force Restart](../decisions/lazy-loading-and-gui-force-restart.md)).
  - Monitor tiles: PCIe tile replaced by a live RAM meter, Context fill shows "Experts in System RAM", GPU temperature replaced by "KV cache memory", tiles reset on unload (same page).
  - Upstream v0.1.45 review, plan and components 1-5: [Upstream v0.1.45 Evaluation Plan](upstream-v0-1-45-evaluation-and-benchmark-plan.md), [v0.1.45 master report](v0-1-45-optimizations-and-tuning-report.md).
  - Native browser TTS, Piper voices, auto-speak only for STT input: [TTS plan](native-browser-tts-implementation-plan.md), [TTS report](native-browser-tts-implementation-report.md), [Desktop Piper Voice Switching](../decisions/desktop-piper-voice-switching-and-stt-auto-speak.md).
  - STT with the Brave/Firefox Speech Dispatcher issues, Android text duplication, the mandatory visual review window, instant submit (the 400 ms delay removed), auto-send in the Code tab and mobile keyboard suppression: [STT plan](native-browser-stt-implementation-plan.md), [STT report](native-browser-stt-implementation-report.md), [Local Whisper STT](../decisions/local-whisper-speech-to-text.md).
  - `/save` chat to Markdown: [CLI Chat Markdown Export](../decisions/cli-chat-markdown-export.md).
  - README updated and pushed (`74d597bd`, 17 Oct). It also asked how to contact the upstream maintainer; no change was made.
- **`47cce368…`** (17 Oct 13:20 – 18:44, 27 user turns):
  - Home Assistant Core and its Strata MCP server; Xiaomi integration and camera streams; `/help` and `/mcp` in the GUI; why the General Chat has no tools; outlets that are really light switches (native light wrappers, area-aware discovery); the Gree AC: [Home Assistant Core Deployment and Strata MCP](../decisions/home-assistant-strata-mcp.md), [HA plan](homeassistant-strata-core-plan.md), [HA walkthrough](homeassistant-and-session-tools-walkthrough.md), [Session Tools plan](session-commands-and-tools-plan.md).
  - TTS emoji and symbol filter: [Desktop Piper Voice Switching](../decisions/desktop-piper-voice-switching-and-stt-auto-speak.md).
  - Proton Bridge SMTP 454: [Scheduled Jobs in D.L. AI](../decisions/dl-ai-scheduled-jobs.md).
  - "Strata crashed" at 17:44 was a Cloudflare tunnel drop; it led to the switch to QUIC: [Cloudflare Tunnel](../decisions/cloudflare-tunnel-remote-exposure.md).
- **`9bf3cff9…`** (17 Oct 16:36 – 20:04, 6 user turns): the thinking-level weather benchmark, [Weather Reasoning Benchmark](../decisions/weather-reasoning-benchmark.md). A harder follow-up benchmark was planned but not built: [Async Queue Debugging Benchmark Plan](async-queue-debugging-benchmark-plan.md).
- **`96e34383…`** (17-19 Oct, 16 user turns): live control of SolidCraft over its MCP server (a 3D-printable dispenser model). It is not Strata work, and its plans stay in Antigravity's folder and `~/Desktop/SolidCraft_MCP_Architecture_Guide.md`.
- **`ed37fa1e…`** (19 Oct 20:19 – 21:09, 10 user turns): read-only status checks of the D.L. AI CONTRA run. What they found led to [D.L. CLI Keeps Its Task](../decisions/dl-cli-task-memory-and-finish-checks.md).
- Other conversations from those days were not about Strata (the CachyOS login screen, Antigravity errors and Remote, installing and updating SolidCraft).

## Last session — still open (12 Oct, ended on an Antigravity quota error)

**Update 2026-10-20: all three are done since.** (1) The zip download was fixed in `afc0e553` (13 Oct, "stream downloads from disk; resumable, any file name, no Blob"). (2) The README was rewritten in the 13 Oct plan ([D.L. AI Plan (2026-10-13): Shared Session, Guardrails, README](dl-ai-2026-10-13-plan-session-guardrails-readme.md)) and updated in `74d597bd` (17 Oct). (3) The guardrails were settled in [Approval Gate for Destructive Agent Actions](../decisions/destructive-action-approval-gate.md) (13 Oct: only destructive actions and writes outside the workspace ask; content is never restricted).

The repo is clean at `20142315` and in sync with `origin/main`, so none of these three were committed.

1. **12 Oct 08:19** — Downloading a large `.zip` from the server workspace with "download to browser" doesn't work (an `.md` file works). → Agent was reading `/api/workspace/download` in `serve/server.py` when it hit `RESOURCE_EXHAUSTED (429)`. **Not fixed.**
2. **11 Oct 23:20** — Rewrite the README on the app repo (DamirLukina88/D.L.-AI---Strata): remove the upstream Strata header, language links, pagoda video and upstream description; add our benchmark info; ask me questions. → Agent asked its questions, then "Development is paused". **README is still the upstream one.**
3. **11 Oct 23:15** — I use an uncensored model: list the guardrail types in the CLI system prompt with a description of each, so I can drop the ones that aren't about security (data leaks, unauthorised destructive actions). Ask me questions. → Agent listed them (in `tools/dl_cli.py` and `serve/frontend.py`); **no change made.**

## 11 Oct (evening) — upstream v0.1.43, performance, CLI consolidation

4. **22:51** — Upstream was updated again: what's new, any other performance improvements we haven't tried? → "proceed".
5. **22:48** — Profile-trace test was interrupted (`bench/traces/coder_12/` → `data/expert-profile-custom.bin`); resume it.
6. **22:03** — Implement and benchmark `STRATA_ADAPT_OVERLAP=1` + `STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`; benchmark `STRATA_ROUTE_RESIDENT=<margin>`; enable `STRATA_DROP_CACHE_ON_EXIT=1`; use `tools/strata_bench.py` + `bench.sh`, gather traces with `collect_profile_traces.py` / `make_profile_mix.py`; look at `serve/logit_bias.py`.
7. **21:56** — Anything else from the upstream repo we should implement?
8. **21:39 / 21:42** — Upstream Strata was updated: what's new, then a multi-step implementation plan (→ v0.1.43 merge).
9. **21:13** — Add `/exa` and `/context7` shortcuts to the mobile wrapper GUI.
10. **21:12** — After the first LLM reply `/health` and `/status` stop working on mobile; `/plan` confirmation shows only in the CLI view, not the wrapper — "there is a deeper issue".
11. **21:02** — "Reset terminal session" does nothing on mobile.
12. **21:01 / 21:32** — `/health` and `/status` graphs don't render in the mobile wrapper (raw ANSI escape codes shown).
13. **20:33** — On mobile the CLI output area stays empty whatever I type (works on desktop).
14. **20:30** — For DeepSeek, use the `deepseek-v4-pro` system prompt as the reference.
15. **20:29** — Remove Claude Code CLI and DeepSeek CLI from the app and GUI; keep only D.L. CLI, improved with the best parts of both. Keep the full Fable 5.1, Opus 5.5 and DeepSeek system prompts in the wiki as reference. Rename D.L. CLI to just "CLI". Session tag `dl-ai-code:agy` → `dl-ai-code`. Saved chats named `dl-ai-code-chat-YYYY-MM-DD-HH-MM.md`.
16. **20:20** — Audit the original Fable system prompt vs our stripped one and suggest changes; review the DeepSeek prompt for what to prune and what to bring into the D.L. AI prompt. Ask me questions.
17. **20:17** — Implement all 4 Claude Code directives in D.L. CLI: file-first bias, clickable `file_path:line` links, faithful error reporting, style matching.
18. **20:09** — Prune Claude Code to 6 core tools; raise the JIT idle-unload timeout to avoid cold 30 GB reloads (→ 8 h).
19. **19:53** — What else can we strip from the instructions that doesn't work with the local LLM? (It was my CLI that was slow, not Claude Code.)
20. **19:46** — Repeat: the model must be able to switch the working directory to any path I give; the wiki skill must initialise in the current working directory. No visible mobile improvements yet.

## 11 Oct (afternoon) — wiki, Fable prompt, mobile, hangs

21. **15:19** — The model says it can't switch the project working directory; it must be able to, and the wiki skill must follow that directory.
22. **15:13** — The model hangs on the 2nd prompt when the prompt is larger.
23. **15:06** — Stop the app and server, GPU stuck at 100%; restart it. (Later: force restart unloaded the model but GPU went back to 100%; restarted the PC; the server didn't autostart until the PC was unlocked.)
24. **15:04** — The CLI on smartphone is unusable — ask me questions and suggest a solution.
25. **14:17** — In my CLI, `/act` and `/execute` don't switch the model to act mode.
26. **12:32** — Claude Code CLI is too slow: use the Fable 5.1 system prompt, stripped of what can't work locally; review and ask me questions.
27. **12:29** — The project has changed a lot from upstream: update the project descriptions in the wiki; ask me questions; commit and push.
28. **12:09** — Show Claude Code CLI thinking the same way DeepSeek and D.L. CLI show it.
29. **12:10** — (side chat) Add the uncensored model `jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata` to both of my models in Strata.

## 11 Oct (morning) — CLIs in the Code tab

30. **11:24** — Codex CLI doesn't work: remove it from the app and uninstall it from CachyOS.
31. **11:17** — DeepSeek CLI should stream its thinking live, not drop a reasoning box at the end.
32. **11:04** — Recommend testing tools so the harness writes tests during development and repeats until they pass.
33. **11:00** — Add "save this chat as Markdown" to the CLIs (it exists in Chat). Ask me questions.
34. **10:59** — Add the guardrail/debug tools: `syntax_guard`, `scan_secrets`, `system_health`, `git_diff_audit`, `smart_test_runner`. Ask me questions.
35. **10:55** — The wiki skill must not default to a fixed wiki directory, be inactive by default, and create the wiki in the project folder I define when invoked.
36. **10:49** — Restyle all CLIs to match the Chat section. Ask me questions.
37. **10:43** — Default D.L. CLI thinking level to Medium.
38. **10:37** — Add the Server Workspace file-manager button from Chat to the Code environment. Ask me questions.
39. **10:35** — Add my local-wiki skill to the CLI.
40. **10:32** — Add plan mode to my CLI, modelled on Claude Code's plan mode.
41. **10:30** — Add Exa MCP web search (API key) and Context7 (key already in Antigravity) to my CLI.
42. **10:10** — Put my CLI first in the GUI list, before Claude Code.
43. **10:09** — Rebrand the custom "Antigravity CLI" to **D.L. CLI** and remove all Antigravity / Google DeepMind branding.
44. **09:18 / 09:47** — The Antigravity CLI in the app doesn't use the local LLM — make it use the local Qwen agent (Codex also failed: missing `STRATA_API_KEY`).

## 10 Oct (evening) — Code tab, audit, upstream fixes, GitHub fork

45. **22:47** — Antigravity CLI, DeepSeek CLI and Codex CLI must all use local Strata.
46. **22:39** — Fix the mobile width/menu issue in the Code view.
47. **22:22 / 22:32** — Add Antigravity CLI, DeepSeek CLI and Codex CLI as extra scaffolds in the Code section.
48. **22:18** — Default Claude Code to `/model haiku` after restart.
49. **22:16** — Commit and push.
50. **21:53** — Capture the difference in preloaded tokens between Fable / Opus / Haiku system prompts in Claude Code.
51. **21:45** — Enable CPU prefill expert sharing; test speculative drafting (not only for coding) and pick the best option; tune `--vram-reserve-mib`.
52. **21:31** — Thinking: off for the loaded model when used from Code CLI, but in Chat follow the Settings value (Off/Low/Medium/High).
53. **21:10** — Fix the audit findings.
54. **20:49** — Plan a code audit of the project (Antigravity `/boost`).
55. **20:42** — Implement the gateway change for the Claude Code auto-mode classifier-billing notice.
56. **20:35** — Speed up Claude Code's ~35K-token prompt prefill (option 1 only).
57. **20:17** — Code-tab restart breaks the ttyd websocket (`/code/token` fetch fails); restore the context window and KV precision to their originals. Ask me questions.
58. **20:09** — Start implementation (upstream v0.1.42 fixes, then plan 2).
59. **18:32** — Plan 2: push my customised version to my fork `DamirLukina88/D.L.-AI---Strata` with no credentials, keys or anything enabling unauthorised access.
60. **18:24 / 18:29** — Check upstream for fixes worth taking; detailed plan to implement them.
61. **18:12 / 18:18** — ttyd in the Code tab: API key passed in the URL treated as an unknown option (logs pasted).
62. **18:03** — Monitor shows "x / 35,651 tokens", wrong since the context limit was raised.
63. **17:57** — Workspace tree: all folders must be nested correctly with collapsible sub-menus at every depth.
64. **17:20** — Accept the Code-tab plan (pinned to `/mnt/data/DL-AI-workspace`, auth via API key, session persists) — execute.
65. **17:17** — Add to the plan: dropped folders must stay a folder, shown as a collapsible sub-section.
66. **17:13** — The Code CLI must use Strata by default, not Anthropic models.
67. **17:10** — New "Code" tab: web interface for Claude CLI on the host, authenticated through ai.damir-lukina.com, with its own icon between Chat and Monitor.

## 10 Oct (afternoon) — D.L. AI rebrand, Cloudflare, workspace, models

68. **16:52** — Drag-and-drop doesn't work on mobile; no server-workspace folder icon visible.
69. **16:45** — Hide (don't remove) the old Attach button, now redundant. Fix `favicon.ico` 404.
70. **16:39** — Resume the interrupted Shared Workspace plan.
71. **16:36** — Mobile GUI still breaks width and ignores the colour scheme in Brave; fix the Thinking label `<output>`.
72. **16:12 / 16:17** — Shared working folder on the D disk (`/mnt/data/DL-AI-workspace`) used by Claude CLI and the web app as default storage: upload with drag-and-drop, attach-from-folder picker, browser download. Overwrite on duplicate names.
73. **16:02** — Replace the About tagline with: "Dedicated private AI without external tracking. Your own model, your own rules."
74. **15:52** — Run the app as a CachyOS service at boot with a watchdog that restarts it if it hangs.
75. **15:44** — Point Logout at `https://damirl.cloudflareaccess.com/cdn-cgi/access/logout`.
76. **15:40** — Add a proper mobile theme (colours wrong, model selector/logout break the width).
77. **15:30 / 15:34** — Logout doesn't end the Cloudflare Access session (we use Cloudflare Access one-time code, not Google).
78. **15:24** — Raise context to 262,144 with hybrid K8V4 KV cache.
79. **14:57** — Raise the context window above 65,536; download the general model; enable image input for both models if possible.
80. **14:47** — Unload after 30 min idle; switching models unloads the current one (same model = reuse); rebrand Strata → **D.L. AI** in GUI and code; add a Logout button that clears the session cookie; Antigravity-2-style dark theme with orange accent.
81. **14:36** — Don't load a model at start, load on first request; model selector for the 2 models; Force-restart button in Monitor; don't cap thinking.
82. **14:20** — Prefill the web GUI API key so I don't enter it each time.
83. **13:50** — Use OAuth instead of entering the API key (Cloudflare Access with `/v1/*` bypass).
84. **13:36** — Go with the plan: expose the web GUI and CLI via my domain through a Cloudflare Tunnel.
85. **11:02** — Fish `claude` wrapper to route Claude Code CLI to Strata, auto-starting the Strata server on launch and stopping it on exit.
86. **10:58** — Make Claude Code CLI always use Strata without breaking Claude Desktop.
87. **10:32 / 10:35** — Update the Context7 API key; generate a Strata API key.
88. **09:54 / 09:56** — Check the repo for Strata updates; very detailed plan first (→ v0.1.41 upgrade).

## 5 Oct — initial setup

89. Clone `Niko1221/Strata` into the project folder and ingest into the wiki.
90. Detailed plan to deploy and install Strata on my OS (interview me).
91. MCP server so the local coding agent runs under the Antigravity harness, plus an Antigravity skill for Strata.
92. Configure the Bionic app on CachyOS to use Strata.

## Related

- [D.L. AI Implementation Plan (2026-10-13)](dl-ai-2026-10-13-implementation-plan.md) - finished the three open requests

## Sources

1. Antigravity conversation database `~/.gemini/antigravity/conversations/44aeb44c-4179-41a4-b503-f0e55de2e0a8.db` and three side conversations, extracted by Claude Code on 2026-10-13 (secrets redacted).
