---
title: "Strata v0.2.5 Web Ergonomics and Engine Reliability Sync Walkthrough"
type: artifact
description: "Walkthrough documenting local safety backup, Web & Chat Ergonomics Suite, and Engine & Server Startup Reliability implementations from Strata v0.2.5"
status: active
tags: [upstream, v0.2.5, ergonomics, markdown, clipboard, pdf, timeout, cleanup, rx7600xt]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Walkthrough: Strata v0.2.5 Web Ergonomics & Engine Reliability Sync

## Overview
We successfully synchronized and implemented high-value features and stability fixes from upstream [Strata v0.2.5](https://github.com/Niko1221/Strata/releases/tag/v0.2.5) while preserving all local customizations (D.L. CLI, Ray voice persona with PipeWire/speechd, Home Assistant MCP, and `/effort auto` adaptive thinking) on our production **Qwen3.8-Flash-Next Coder IQ1_M** setup (AMD Ryzen 5 3600, 32 GB RAM, AMD Radeon RX 7600 XT `gfx1102`).

---

## 1. Safety & Local Backup Completed

Prior to modifying any files, complete local backups were established:
* **Git Safety Tag & Branch:** `backup/before-v025-sync-20261025`
* **Local File Snapshot Directory:** `~/.config/dl-ai/backup-20261025/` containing exact pre-change copies of:
  * `serve/web/app.js`
  * `serve/web/app.css`
  * `serve/server.py`
  * `tools/strata_mcp.py`
  * `strata-coder-iq1_m.json`

---

## 2. Changes Implemented

### Component 1: Web & Chat Ergonomics Suite
* **CommonMark Soft Linebreaks ([#3818](https://github.com/Niko1221/Strata/issues/3818)):**
  * Updated `blocks(text)` in `serve/web/app.js`: single newlines within paragraphs are joined with spaces (`" "`) instead of `<br>`, while lines ending in two spaces or a trailing backslash (`\`) produce hard breaks.
* **Direct Screenshot Clipboard Paste (`Ctrl+V`) ([#3748](https://github.com/Niko1221/Strata/issues/3748)):**
  * Added paste listener to `code-mobile-input` in `serve/web/app.js` inspecting clipboard `items` (`image/*`). Screenshots taken with system tools (e.g. `PrintScreen` or `Spectacle`) are automatically saved to workspace as timestamped PNGs and referenced as `@pasted-image-...`.
* **Window-Level Drag & Drop & PDF Support ([#3838](https://github.com/Niko1221/Strata/issues/3838)):**
  * Added global window dragover/drop handlers preventing accidental browser navigation and routing dropped PDFs or images directly to workspace upload.
* **User Message Formatting & Unified Clipboard Feedback ([#3720](https://github.com/Niko1221/Strata/issues/3720), [#3731](https://github.com/Niko1221/Strata/issues/3731)):**
  * Added `.st-bubble__text { white-space: pre-wrap; overflow-wrap: anywhere; }` to `serve/web/app.css`.
  * Upgraded `copyText()` in `serve/web/app.js` with fallback detection and clear toast notifications (`Copied` vs `Couldn’t copy`).
* **Resilient Decimal Input Parsing ([#3736](https://github.com/Niko1221/Strata/issues/3736)):**
  * Added `parseDecimal()` and `partialDecimal()` helpers handling commas, dots, and in-progress typing states.
* **Cache Busting:**
  * Updated `serve/web/index.html` cache buster parameter to `v=20261025-v025sync`.

### Component 2: Engine & Server Startup Reliability Suite
* **Dynamic Model Load Timeout Scaling ([#3949](https://github.com/Niko1221/Strata/issues/3949), [#3459](https://github.com/Niko1221/Strata/issues/3459)):**
  * Added `calculate_start_wait(cfg, model_path)` and `MAX_START_WAIT = 1800.0` to `serve/server.py`.
  * Automatically scales engine readiness wait time (10 minutes baseline, +8s per GB over 40 GB, capped at 30 min / 1800s) and respects explicit `engine_ready_s` config entries or `STRATA_ENGINE_READY_S` environment variables.
* **Clean Shard & Model Deletion ([#3716](https://github.com/Niko1221/Strata/issues/3716)):**
  * Implemented `made_by_strata()`, `removal_plan()`, and `strata_remove` in `tools/strata_mcp.py`.
  * Safely identifies Strata-generated shards (`.done` markers) and conversion packs (`conversions.json`), purges model files across external paths upon confirmation, and leaves foreign/user files untouched.
* **ROCm hipBLAS Warm-up:**
  * Configured `"STRATA_PREFILL_WARM": "1"` in `strata-coder-iq1_m.json` under `env`.

---

## 3. Validation & Verification Results

| Test / Check | Verification Procedure | Result |
|---|---|:---:|
| **Markdown Soft Breaks** | Node test verifying single newlines become spaces, trailing spaces/backslash produce `<br>`, and blank lines produce `<p>` | **PASSED** |
| **Timeout Formula Scaling** | Unit test verifying 20 GB (900s), 83 GB (~944s), and 250 GB (capped at 1800s) | **PASSED** |
| **Model Shard Deletion Guard** | Python test validating `made_by_strata` with `.done` marker and dry-run `strata_remove` | **PASSED** |
| **Bytecode Compilation** | `python -m py_compile serve/server.py tools/strata_mcp.py` | **PASSED** |
| **Live Server Health** | `curl -s http://127.0.0.1:8080/health` | **HTTP 200 OK** |
| **Served Assets Verification** | `curl -s http://127.0.0.1:8080/web/app.js` | **Verified** |
| **Systemd Services** | `systemctl --user status strata-server.service dl-ai-sessiond.service` | **Active & Healthy** |

## Sources

1. Upstream Strata v0.2.5 release: `https://github.com/Niko1221/Strata/releases/tag/v0.2.5`
2. Git commits: `c1e80f79`, `780a69b4`, `c7899f9c`, `353c9f25`, `27cbbfe6`, `47ccec7c`
3. Safety backup snapshot: `~/.config/dl-ai/backup-20261025/` and git tag `backup/before-v025-sync-20261025`

