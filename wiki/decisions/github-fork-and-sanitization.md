---
title: "GitHub Fork and Public Sanitization Architecture"
type: decision
description: "Architecture for publishing customized Strata fork to GitHub while preventing credential leakage"
status: active
tags: [git, github, fork, security, sanitization]
created: 2026-10-10
updated: 2026-10-23
last_verified: 2026-10-23
---

# GitHub Fork and Public Sanitization Architecture

## Summary
The customized Strata platform (featuring the authenticated Claude Code Web Terminal, recursive N-ary server workspace tree, mobile GUI enhancements, MCP agentic coder tools, system watchdog, and upstream v0.1.42 cherry-picks) was published to the public GitHub repository at [https://github.com/DamirLukina88/D.L.-AI---Strata](https://github.com/DamirLukina88/D.L.-AI---Strata). A zero-secret sanitization architecture was enforced to guarantee no API keys, private domains, or machine paths are leaked publicly.

- 2026-10-13: The 2026-10-10 sanitization missed four secrets hardcoded as fallbacks in tools/dl_cli.py and tools/run-code-session.sh; they reached the public fork. Rotated, moved to ~/.config/dl-ai/secrets.env, history scrubbed with filter-repo limited to our own refs, and a pre-commit secret-scan hook added. See [Public Secret Leak and Rotation](secret-leak-rotation-2026-10.md).

- 2026-10-13 (night): Pushed 30 commits (the 13 upstream PR merges, see [Upstream Open PR Review (2026-10-13)](../artifacts/upstream-open-prs-review-2026-10-13.md)) to the fork: `51fae4a6..b5e5b3ff`, fast-forward, no force. Before the push, `dl_auditing.scan_secrets_in_text` was run over all 40 changed files and the added lines were checked for the private domain, home paths and host name: 0 findings. Claude Code's auto mode blocks `git push` to this public fork, so the user ran the push.

- 2026-10-13 (late): Pushed the v0.1.44 merge to the fork, `b5e5b3ff..9d614675` (273 commits, fast-forward). The secret scan beforehand checked 344 files and 46,263 added lines: 0 findings. This push went through from Claude Code after the user's explicit "Push".

- 2026-10-15: Pushed `9d614675..3b6dfb4f` (one commit: on-demand MCP, outgoing credential filter, agent bench; 25 files), fast-forward. Before the commit, `dl_auditing.scan_secrets_in_text` (now also matching the exact stored credential values) checked all 25 files: only the marked fake fixtures in the two test files hit. The added lines had no private domain, home path or host name; `/mnt/data` paths were already in the tracked code. Pushed from Claude Code after the user's "commit and publish to git".

- 2026-10-15 (later): Pushed `3b6dfb4f..937c318f` (Proton Mail, scheduled jobs, DeepL built-in, autonomous YOLO; 13 files), fast-forward. Secret scan of all changed files: only marked fake fixtures (the marker was added to `tools/test_dl_schedule.py`); no private domain, home path, host name or phone number in the added lines.

- 2026-10-15 (late): Pushed `937c318f..4274fb11` (fixes from the live weather-email runs; 6 files), fast-forward. Secret scan: only the marked fake fixtures in `tools/test_dl_mcp.py`; no private strings in the added lines.

- 2026-10-15 (late): Pushed `4274fb11..5209d07d` (audit fixes; 10 files), fast-forward. Secret scan: only the marked fake fixtures; no private strings in the added lines.

- 2026-10-21: Pushed 5 commits to the fork (`74d597bd..f67a53a6`, fast-forward, `main` only, no force): the D.L. CLI task-memory and finish-check work, the YOLO and plan-chip fixes, the Cloudflare logout fix, and the CONTRA-run D.L. CLI fixes. Before the push, `scan_secrets_in_text` ran over all 11 staged files. The only hit was the existing fake OAuth tokens in `tools/test_dl_mcp.py` (`...FAKEfake...`). The diff adds no email addresses, but it does add 12 lines with machine paths (checkout-parent paths and a Claude scratchpad path) and one with the private domain. The fork already had the same kind of detail (36 of its 82 wiki pages carry machine paths, 15 files name the domain), so the 2026-10-10 "no private domains or machine paths" rule is not being kept for the wiki. *(Open: sanitize the wiki or keep it out of the fork.)*

- 2026-10-22: Pushed 7 commits to the fork (`d53a4361..964c4a67`, fast-forward, `main` only, no force): the four
  ported upstream 0.2.2 fixes and their wiki pages, the Ray rename, persona and female voice, thinking off for spoken
  prompts, and the Home Assistant area script. `scan_secrets_in_text` passed on all 29 changed files (a planted fake key
  was caught, so the scan ran). The added lines have no email address, home IP or host name; 6 carry `/mnt/data` paths,
  as before. The Ray persona in `serve/web/app.js` names the user (Damir) and this PC's hardware, on purpose.

- 2026-10-23: Pushed the upstream 0.2.3/0.2.2 fixes port (`aece46db`, `2ccf57ec`, `c40a03e6`, `828a2559`, `8bf178fe`,
  `9471faa5`), `0.2.3.1` `setup.py` `BUILD.json` `archs`/`vision_archs` fixes (`0edd96cc`, `f5f205be`), `/effort auto`
  (`tools/dl_effort.py`, `tools/dl_sessiond.py`, `tools/dl_cli.py`, `tools/test_dl_effort.py`, `tools/test_dl_sessiond.py`,
  `tools/test_dl_auto_raise.py`), `README.md` updates, and wiki pages (`upstream-v0-2-3-review-2026-10-23.md`,
  `auto-thinking-level.md`, `cli-graphical-styling-and-thinking-defaults.md`, `rx-7600-xt-cachyos-deployment.md`)
  to `origin/main` (fast-forward, no force) after `scan_secrets_in_text` verified 0 findings across all staged files.

- 2026-10-27: Pushed `92b7249a..1c564fc4` (11 commits, fast-forward, `main` only, no force): the v0.2.7 engine/server fixes, web side-by-side view, Home Assistant light groups, the Code feed scroll fix, saved sessions, edit/rewind/branch and the README. Before the push, `scan_secrets_in_text` ran over all 31 changed files (0 findings; a planted fake key was caught), and the 1,971 added lines were checked for the home path, the checkout's parent folder, the host name, the profile email, the private domain and the LAN IPs: 0 hits. Pushed from Claude Code after the user's explicit "then push main to origin".

## Decisions & Configuration

### 1. Remote Layout
- 2026-10-29: Pushed `9b890835..510141f2` (3 commits, fast-forward, `main` only, no force): the red panda persona and small-talk tool guard, the cocoa break, and the long-task work animations with their README GIFs. Before the commit, `scan_secrets_in_text` ran over the 6 changed text files (0 findings) and the added lines were checked for the home path, the data-disk path, the host name, the profile email and LAN IPs: 0 hits. Pushed from Claude Code after the user's "git commit and push".
- 2026-10-29 (later): Pushed `510141f2..c7bf1d11` (1 commit, fast-forward, `main` only): the Home Assistant control panel animation and its README GIFs. `scan_secrets_in_text` over the 7 changed text files: 0 findings. The pre-commit privacy hook blocked the first try because this page named the data-disk path in a note; it was reworded. Pushed after the user's "Commit and push".
- 2026-10-29 (evening): Pushed `c7bf1d11..13e1f53e` (1 commit, fast-forward, `main` only): the thermostat panel removed, the README listing the control panel. Secret scan over the 6 changed text files: 0 findings; no private paths, host name, email or LAN IPs in the added lines. Pushed after the user's "Commit and push update readme".
- 2026-10-30: Pushed `13e1f53e..040a5ba6` (2 commits, fast-forward, `main` only): the upstream 0.2.8 tool-call parser port and sentence-by-sentence speech with preambles. Secret scan over 21 changed files: 0 findings; no home path, data-disk path, host name, email, LAN IPs or private domain in the added lines. Pushed after the user's "test, update wiki, and read me, commit and push".
- 2026-10-31: Pushed `040a5ba6..5834e522` (1 commit, fast-forward, `main` only): the honest benchmark and the finish review fix. `scan_secrets_in_text` over the 23 changed files: all clean (a planted fake key was caught); no home path, data-disk path, host name, email, private domain or LAN IPs in the added lines. The pre-commit privacy hook first blocked the data-disk path in two wiki pages; they now say `../DL-AI-workspace`. The uncommitted Xiaomi remote work (web app push-to-talk, udev files, its wiki page) was left out. Pushed after the user's "Commit and push".
- 2026-11-01: Pushed the queued-input feature (`README.md`, `serve/server.py`, `serve/web/index.html`, `serve/web/app.css`, `serve/web/app.js`, `tools/dl_sessiond.py`, `tools/dl_cli.py`, `tools/dl_attach.py`, `tools/test_dl_sessiond.py`, `wiki/decisions/shared-cli-session-daemon.md`, `wiki/changelog.md`) to `origin/main` (fast-forward, no force) after `scan_secrets_in_text` and the pre-commit privacy hook verified 0 findings. The uncommitted Xiaomi remote and GDN chunked experiment files were left out.
- 2026-11-01 (later): Pushed persistent Code speaker toggle and light-theme avatar border hardening (`README.md`, `serve/web/index.html`, `serve/web/app.css`, `serve/web/app.js`, `serve/web/rayface.js`, `tools/test_stt_controller.js`, `wiki/decisions/desktop-piper-voice-switching-and-stt-auto-speak.md`, `wiki/decisions/ray-talking-face.md`, `wiki/changelog.md`) to `origin/main` (fast-forward, no force) after `scan_secrets_in_text` and the pre-commit privacy hook verified 0 findings. The uncommitted Xiaomi remote and GDN chunked experiment files were left out.
- 2026-11-01 (evening): Pushed Two-Tier Wiki Handoff and clean session reload, mid-stream SSE auto-retry, Monitor 50k effective context gauge and Show-all fixes, CPU elastic vision (1.15 GiB RAM reclaimed) and systemd OOM protection (`README.md`, `serve/server.py`, `serve/test_vision_elastic.py`, `serve/web/app.css`, `serve/web/app.js`, `serve/web/index.html`, `tools/dl_cli.py`, `tools/dl_sessiond.py`, `tools/test_dl_context.py`, `wiki/decisions/wiki-handoff-and-oom-fixes.md`, `wiki/decisions/dl-cli-task-memory-and-finish-checks.md`, `wiki/changelog.md`) to `origin/main` (fast-forward, no force) after `scan_secrets_in_text` verified 0 findings. The uncommitted Xiaomi remote and GDN chunked experiment files were left out.
- 2026-11-03: Pushed `840c30d2..43c7ee56` (23 commits, fast-forward, `main` only, no force): the Ray Android companion (Antigravity's hybrid WebView app and Phone MCP, then the layout, icon, voice drawer, helmet, setup screen, About card, workspace upload/download, drawer thinking and panda) and its wiki pages. `scan_secrets_in_text` and `find_known_secrets` ran over the 94 changed text files and over the added lines of every one of the 23 commits (162 file changes): 0 findings. The real LAN IP and domain were in 4 files; the current files now use placeholders (`192.168.1.10`, `example.com`), and the user chose to push without rewriting the older commits that still contain them (the domain was already public on the fork; the LAN IP is private-range). Pushed after the user's "commit push".
- 2026-11-03 (later): Pushed `43c7ee56..effd0f36` (15 commits, fast-forward, `main` only, no force): "Ok Ray", the companion security fixes, phone tools for app prompts (`origins`), the phone-relay key fix, cleanup and tests, the short README with screenshots and `docs/RAY_*.md`, and the audit. `scan_secrets_in_text` and `find_known_secrets` over the added lines of all 14 content commits (63 file changes): 0 findings; the one added line with the LAN IP was reworded before the push; screenshots were checked by eye (demo conversation, status bar cropped). Pushed under the approved plan's final step after the user's earlier "commit push".
- **Upstream:** `https://github.com/Niko1221/Strata.git` tracked under remote name `upstream`.
- **Origin:** Personal fork `https://github.com/DamirLukina88/D.L.-AI---Strata.git` tracked under remote name `origin`.
- **Branch Tracking:** Local `main` branch tracks `origin/main`.

### 2. Zero-Secret Sanitization Architecture
- **Web App Keys:** Hardcoded `DEFAULT_KEY` and index `<script>` pre-seed values were replaced with `""`. In the local environment, existing browser `localStorage` (`strata.apikey`) maintains transparent authentication without prompt.
- **Dynamic Access Logout:** Domain-hardcoded Cloudflare Access logout links were replaced with `window.STRATA_LOGOUT_URL || "/cdn-cgi/access/logout"`, allowing portable session termination across any reverse proxy.
- **Dynamic Systemd Injection:** `tools/run-code-session.sh` dynamically reads `STRATA_API_KEY` and `STRATA_WORKSPACE_DIR` from environment variables passed by systemd user unit `claude-terminal.service`.
- **Runtime Ignores:** `.gitignore` excludes local runtime logs (`strata-server.out`, `strata-server.pid`), `.directory`, and `*.orig` files. Local hardware configs (`strata-*.json`) and `wiki/` remain strictly uncommitted.
- **Graceful Workspace Fallback:** `serve/server.py` defaults `WORKSPACE_DIR` to `./workspace` if `STRATA_WORKSPACE_DIR` is not provided in the environment.

## Verification
- Staged git diff checked with zero matches for API key hashes, private domains, or local home paths.
- Unit tests (`serve/test_request_hardening.py`) passed cleanly.
- Live push succeeded: commit `ba2e5869` pushed to `origin/main`.

## Related
- [Local-Only Repository](../preferences/local-only-repository.md)
- [Fork Attribution Requirement in MIT License](fork-attribution-license-requirement.md)
- [Claude Code CLI Integration on Strata](claude-code-cli-integration.md)
- [GitHub Fork Sanitization and Push Plan](../artifacts/github-fork-sanitization-and-push-plan.md)
- [Public Secret Leak and Rotation (2026-10-13)](secret-leak-rotation-2026-10.md)

- 2026-11-03: pushed `ead9228e..4e3ca937` (10 commits: phone camera photos, gallery tool, YouTube Music control). Secret scan: only the known fake OAuth fixtures in `tools/test_dl_mcp.py` (already on the fork, not added); private-string check clean.

## Sources
- GitHub Fork: [https://github.com/DamirLukina88/D.L.-AI---Strata](https://github.com/DamirLukina88/D.L.-AI---Strata)
- Upstream: [https://github.com/Niko1221/Strata](https://github.com/Niko1221/Strata)
- Systemd user service: `~/.config/systemd/user/claude-terminal.service`
1. User, chat, 2026-10-13.

- 2026-11-05: pushed from `4e3ca937` (32 commits including this wiki one, fast-forward, `main` only, no force): the helmet voice fixes, the Opus voice, phone tools without adb, one assistant volume and the panda's mouth sync. `scan_secrets_in_text` over the 65 changed files: 0 findings (it returns `(True, None)` when clean, and a planted fake key was caught). Private-string check: only the generic `~/.local/share/dl-ai/helmet-tests` path.
