---
title: "Wiki Handoff Session Reset, Mid-Stream Recovery, and OOM Headroom"
type: decision
description: "4-section Wiki Handoff Diary + clean session reload, mid-stream error auto-retry, Monitor 50k/Show-all fixes, and 2.15 GiB RAM OOM headroom."
status: active
tags: [context, handoff, oom, monitor, dl-cli]
created: 2026-11-01
updated: 2026-11-01
last_verified: 2026-11-01
---

# Wiki Handoff Session Reset, Mid-Stream Recovery, and OOM Headroom

## Summary

Replaces mechanical 30k context pruning with a 4-section Wiki Handoff Diary + ~4k clean session reload (`handoff_session`), adds mid-stream SSE error detection and auto-retry in `tools/dl_cli.py`, fixes the Monitor's "Show all" table and `50k` effective context gauge, and reclaims ~2.15 GiB of unswappable RAM to prevent Linux `kswapd0` OOM kills.

## Details

### 1. Monitor UI Fixes (`serve/web/app.css`, `serve/web/app.js`, `serve/web/index.html`)
- **Show all (`#req-all`):** Previously, `.table-wrap.all { max-height: 420px; overflow-y: auto; }` shrank the 12-row table (~542px) down to ~9 visible rows, and clicking `#req-all` rendered the cached 12-item `lastMetrics` before fetching `metrics?requests=all`. Now `.table-wrap.all` uses `max-height: 75vh` with sticky table headers, clicking `#req-all` fetches `metrics?requests=all` immediately, and `renderMonitor` avoids rewriting `body.innerHTML` when the row HTML has not changed.
- **50k Effective Context Fill Gauge:** Because `tools/dl_cli.py` reserves `CONTEXT_RESERVE = 16000` tokens (`limit = 65536 - 16000 = 49536` ≈ `50k`), the Monitor's Context fill gauge (`ctx-fill`, `ctx-pct`, `ctx-sub`) now scales against `effCtx = ctx > 20000 ? ctx - 16000 : ctx` (`50k`), while the KV cache bar (`kv-text`, `kv-bar`) continues to report physical KV memory against the full `64K` (`65,536`) KV window.

### 2. Wiki Handoff + Clean Session Reload (`tools/dl_cli.py`, `tools/dl_sessiond.py`)
- Unlike the reverted 2026-10-24 struggle diary ([Revert struggle diary](revert-struggle-diary-and-modular-harness.md)), `handoff_session` adds **zero tokens** to `build_dl_system_prompt` on normal turns and **zero per-tool overhead**.
- When prompt tokens exceed `limit` (~49.5k) in a workspace session (or on `/handoff`), `generate_handoff_diary` summarizes the session (via a clean low-effort model call with a deterministic fallback) into a ~700-token diary with four strict sections:
  1. `## Goal & Live State`
  2. `## Completed Steps`
  3. `## Dead Ends & Do Not Repeat`
  4. `## Next Immediate Step`
- `save_handoff_diary` writes `wiki/handoffs/latest.md` and a timestamped archive `wiki/handoffs/handoff-<timestamp>-part<N>.md` (or `.dl-handoff/` when `wiki/` is not present).
- `handoff_session` then resets `messages` in-place to a clean session (`system` prompt + protected user messages + `HANDOFF_NOTE` + the last tool round), dropping prompt tokens from `~50k` down to `~3k–5k` instead of `~30k`, and chains cleanly across multiple handoffs (`part 1` → `part 2` → ...).
- Added `/handoff` slash command in `tools/dl_sessiond.py` for on-demand handoffs.

### 3. Mid-Stream Crash Detection & Auto-Retry (`tools/dl_cli.py`)
- When `strata` dies mid-stream (`verify: timed out at layer N (#267)` or `engine_silence_s`), `serve/server.py` emits SSE `data: {"error": {"message": "...; the next request restarts it"}}` followed by `data: [DONE]`.
- `stream_chat_turn` now inspects `chunk.get("error")` and raises `RuntimeError` instead of treating `[DONE]` as `finish_reason="stop"`.
- `chat_turn_in_context` catches transient engine errors (`TRANSIENT_ENGINE_ERR`), waits briefly (`ENGINE_RETRY_WAIT_S`), and retries automatically (up to `ENGINE_RETRIES = 2`), triggering `serve/server.py`'s `ensure_loaded()` so Ray reloads the model and continues mid-task without stopping.

### 4. Memory & OOM Headroom (`serve/server.py`, `strata-coder-iq1_m.json`, `strata-server.service`)
- Enabled elastic lifecycle for CPU vision encoders (`"elastic": true, "elastic_mib": 0, "elastic_idle_s": 120` in `strata-coder-iq1_m.json` and `serve/server.py`), so `strata-vision` is not spawned with the model and unloads 120s after any image turn, freeing **1.15 GiB of unswappable RAM** during text/coding work.
- Removed `--conversation-cache-mib 1024` from `strata-coder-iq1_m.json` (which was skipping 1,454 MiB long-context snapshots while holding up to **1.0 GiB of unswappable RAM** on medium turns; single-session prompt reuse remains active via `--prompt-cache 12 --prompt-cache-tail`).
- Set `OOMPolicy=continue` and `OOMScoreAdjust=100` in `~/.config/systemd/user/strata-server.service`.

### 5. Empirical Verification & Trimming Retirement
- On 2026-11-01, live hardware profiling on the RX 7600 XT and the A/B benchmark confirmed:
  - **Mechanical Trimming (`DL_HANDOFF=0`):** Pruning turns from the middle of history (`compact_history`) invalidates the KV cache prefix in autoregressive generation. Every single subsequent turn incurred a full 23,000–25,000 token re-prefill penalty taking **45–55 seconds** per turn on the target GPU. Furthermore, dropping intermediate tool responses caused reasoning amnesia.
  - **Two-Tier Wiki Handoff (`DL_HANDOFF=1`):** Appending the diary generation turn directly to history achieved a **~100% KV cache hit rate** (e.g., 9,744 of 9,749 tokens reused in <1s). The subsequent clean session reloaded with a lean ~4,000-token prompt that prefills in **~1.5–2.0 seconds** while preserving complete execution state in `wiki/handoffs/latest.md`.
  - **Conclusion:** Two-Tier Wiki Handoff (`DL_HANDOFF=1`) is adopted as the sole production default, and further comparative testing of trimming was retired.

## Sources

1. User, chat, 2026-11-01.
2. `tools/dl_cli.py`, `tools/dl_sessiond.py`, `tools/test_dl_context.py`, `serve/server.py`, `serve/test_vision_elastic.py`, `serve/web/app.js`, `serve/web/app.css`, `strata-coder-iq1_m.json`.
