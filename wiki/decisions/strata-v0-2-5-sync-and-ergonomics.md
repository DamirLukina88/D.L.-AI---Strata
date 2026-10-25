---
title: "Strata v0.2.5 Sync, Web Ergonomics, and Server Reliability"
type: decision
description: "Selective synchronization of upstream Strata v0.2.5 ergonomics, dynamic startup timeouts, and clean shard deletion on RX 7600 XT"
status: active
tags: [decision, upstream, v0.2.5, ergonomics, markdown, clipboard, pdf, timeout, cleanup, rx7600xt]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Strata v0.2.5 Sync, Web Ergonomics, and Server Reliability

## Summary

Following the release of upstream Strata v0.2.5 on 2026-10-25, we conducted a technical review, established local safety backups (`backup/before-v025-sync-20261025` and `~/.config/dl-ai/backup-20261025/`), and selectively synchronized high-value user-facing ergonomics and server reliability improvements while strictly preserving our local architecture (Ray voice persona, PipeWire/speechd audio routing, Home Assistant MCP, D.L. CLI autonomous task harness, and `/effort auto` adaptive reasoning).

Upstream introduced single-installer packaging and in-app support for DeepSeek-V4.1-Flash. As confirmed in our earlier hardware assessment, DeepSeek-V4.1 requires $\ge 46$ GB RAM and RDNA4 graphics, which is incompatible with our 32 GB RAM / RX 7600 XT (`gfx1102`) workstation. We remained on our production **Qwen3.8-Flash-Next Coder IQ1_M** deployment and ported the web ergonomics and server robustness suites.

## Implemented Components

### 1. Web & Chat Ergonomics Suite
- **CommonMark Soft Linebreaks ([#3818](https://github.com/Niko1221/Strata/issues/3818)):** `blocks(text)` in `serve/web/app.js` now renders single newlines within paragraphs as soft spaces (`" "`) instead of `<br>`. Hard breaks require two trailing spaces or a trailing backslash (`\`), conforming to GFM/CommonMark standards.
- **Direct Clipboard Screenshot Pasting (`Ctrl+V`) ([#3748](https://github.com/Niko1221/Strata/issues/3748)):** Added paste listener on `code-mobile-input` detecting clipboard `items` (`image/*`). Pasted screenshots are auto-saved to workspace storage as timestamped PNGs and referenced via `@pasted-image-...` for Ray's multimodal vision pipeline.
- **Window Drag & Drop & PDF Support ([#3838](https://github.com/Niko1221/Strata/issues/3838)):** Global dragover/drop handlers prevent accidental browser tab navigation and ingest dropped PDF/image files directly into the workspace with `@<file>` reference insertion.
- **User Bubble Formatting & Unified Copy Toast ([#3720](https://github.com/Niko1221/Strata/issues/3720), [#3731](https://github.com/Niko1221/Strata/issues/3731)):** Added `.st-bubble__text { white-space: pre-wrap; overflow-wrap: anywhere; }` to `serve/web/app.css` and unified toast notifications for code and message copy actions.
- **Resilient Decimal Input Parsing ([#3736](https://github.com/Niko1221/Strata/issues/3736)):** Added `parseDecimal()` and `partialDecimal()` helpers supporting European comma/dot formats without resetting while typing.
- **Cache Busting:** Updated `serve/web/index.html` script parameter to `v=20261025-v025sync`.

### 2. Engine & Server Reliability Suite
- **Dynamic Model Load Timeout Scaling ([#3949](https://github.com/Niko1221/Strata/issues/3949), [#3459](https://github.com/Niko1221/Strata/issues/3459)):** Added `calculate_start_wait(cfg, model_path)` and `MAX_START_WAIT = 1800.0` in `serve/server.py`. Automatically scales engine readiness wait time (10 min base + 8s per GB over 40 GB, capped at 30 min / 1800s) and respects explicit `engine_ready_s` in configs or `STRATA_ENGINE_READY_S`.
- **Clean Shard & Model Deletion ([#3716](https://github.com/Niko1221/Strata/issues/3716)):** Added `made_by_strata()`, `removal_plan()`, and `strata_remove` in `tools/strata_mcp.py` with `.done` marker and `conversions.json` validation, purging model files safely across external paths upon confirmation while leaving foreign/user files untouched.
- **ROCm hipBLAS Warm-up:** Verified and explicitly ensured `"STRATA_PREFILL_WARM": "1"` in `strata-coder-iq1_m.json` under `env`.

## Verification & Performance Baseline

- Automated tests:
  - Markdown soft breaks verified via Node.js script (soft break spaces, `<br>` trailing escapes, `<p>` paragraphs).
  - Timeout formula verified across 20 GB (900s), 83 GB (~944s), and 250 GB (1800s cap).
  - Strata MCP clean deletion tested for `.done` marker recognition and dry-run safety.
- Performance Benchmark (`tools/strata_bench.py` against active server, 479s, 0 failures):
  - **Short Chat Decode:** **25.20 tok/s** (+1.6%, peak 31.10 tok/s)
  - **4K Fresh Prompt:** **302.20 tok/s** (peak 305.10 tok/s), TTFT 13.35s (-0.2%)
  - **16K Fresh Prompt:** **323.50 tok/s** (peak 324.20 tok/s)
  - **Agent Coding Decode:** **27.30 tok/s** (peak 34.60 tok/s), TTFT 11.70s
  - **Agent Cache Hit Rate:** **68.46%** (up to 11,571 cached tokens)
  - **Reliability:** **100% pass (0 / 18 failures)**

## Sources

1. Upstream Strata v0.2.5 release notes: `https://github.com/Niko1221/Strata/releases/tag/v0.2.5`
2. Upstream Git commits: `c1e80f79`, `780a69b4`, `c7899f9c`, `353c9f25`, `27cbbfe6`, `47ccec7c`
3. Walkthrough report: `wiki/artifacts/strata-v0-2-5-sync-and-ergonomics-walkthrough.md`
4. Performance benchmark: `wiki/artifacts/strata-benchmark-2026-10-25-v025-sync.md`
