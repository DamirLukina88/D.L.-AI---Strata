---
title: "Lazy Loading and GUI Force Restart"
type: decision
description: "Implementation of JIT model loading on request, GUI force restart button, and model selection"
status: active
tags: [lazy-load, server, web-gui, restart, lifecycle]
created: 2026-10-10
updated: 2026-10-17
last_verified: 2026-10-17
---

# Lazy Loading and GUI Force Restart

## Summary

To prevent holding 20+ GB of system RAM and 7 GB of GPU VRAM at all times while allowing long, uncapped reasoning for coding tasks, Strata was configured for lazy JIT (just-in-time) model loading on startup, and equipped with a forceful engine termination and restart endpoint accessible from the Strata Web GUI Monitor tab.

## Key Facts

- **Lazy Loading (`lazy_load: true`):** Added to `strata-coder-iq1_m.json`. Strata starts the HTTP server in under 1 second using ~200 MB of RAM and leaving GPU VRAM at 8% (idle desktop). The engine and expert weights are only loaded into RAM/VRAM upon receiving the first inference request or when `/load` is triggered.
- **30-Minute Idle Auto-Unload (`idle_unload_s: 1800`):** Configured in the model configs and background monitor thread in `serve/server.py`. Automatically unloads the model process from RAM/VRAM if no requests arrive within 30 minutes, keeping system memory free when idle.
- **Dynamic Model Switching (`POST /switch_model` and `GET /available_models`):** Enabled on-the-fly model switching via the header dropdown in the web UI. Guarded by `switch_lock` and pre-validates model pack/weight presence on disk before terminating the active model to prevent OOM panics or invalid states. Recognizes if the selected model is already loaded and avoids redundant reloading.
- **GUI Rebranding & Theme ("D.L. AI"):** Rebranded the Web UI from "Strata" to "D.L. AI" and updated CSS theme variables to match the Antigravity 2.0 dark aesthetic (`#0b0d10` deep dark background, `#12161b` surface) with an orange accent palette (`#f97316` / `#fb923c`).
- **256K Context Window & Hybrid K8V4 KV Cache:** Upgraded context from 65,536 to 262,144 tokens (`--max-context 262144`) using hybrid K8V4 KV cache precision (`--kv k8v4`). At 256K context, K8V4 uses only ~816 B/cell (~2.7 GB total for 256K tokens) while keeping 8-bit addressing precision for attention Keys, ensuring zero degradation for code indexing and multi-file agentic reasoning while staying safely within 31 GB system RAM.
- **Multimodal Vision Integration:** Compiled native CPU vision binary `strata-vision` using llama.cpp `mtmd` with AVX2. Linked `/mnt/data/Strata-data/models/mmproj-Qwen3.8-Flash-Next-BF16.gguf` in the model configurations (`strata-coder-iq1_m.json` and `strata-general-q2_0.json`). Both `/health` and `/props` now report `"modalities": {"vision": true}`.
- **Cloudflare Access Direct Logout Navigation:** Updated the header logout button in `serve/web/app.js` to clear `localStorage`, `sessionStorage`, and domain cookies, and navigate the top-level window directly to `https://damirl.cloudflareaccess.com/cdn-cgi/access/logout?returnTo=https://ai.damir-lukina.com/`. This forces Cloudflare Access edge authentication to terminate the session and clear HttpOnly tokens.
- **Mobile Header Responsiveness & Default Dark Theme:** In `tokens.css`, `:root` defaults unconditionally to the Antigravity 2.0 dark palette (`#0b0d10` background, `#12161b` surface, `#f97316` orange accent) so mobile browsers defaulting to light mode do not trigger an unintended light theme. In `components.css` and `app.css`, `.st-header` and `.st-header__brand` enforce `white-space: nowrap !important`, `flex-wrap: nowrap`, and `word-break: keep-all` so "D.L. AI" never wraps vertically. On screens ≤600px, tab text labels are hidden in favor of compact icon-only buttons (`Chat`, `Monitor`, `About`), `.st-pill` becomes a circular dot indicator, and `#model-select` flex-shrinks with ellipsis down to 65px (50px on ≤380px), fitting all controls cleanly within 320px–390px viewports without horizontal page blowout.
- **Cache-Control & Cache-Busting:** Added `Cache-Control: no-cache, must-revalidate`, `Pragma: no-cache`, and `Expires: 0` headers to `/` (HTML) and `serve/web/` static assets in `serve/server.py`. Added version query strings (`?v=20261010-4` / `?v=20261017-1`) to stylesheets and scripts in `index.html` and `monitor.html` to eliminate aggressive caching by mobile browsers (e.g. Brave) and Cloudflare edge proxies.
- **Form Accessibility:** Resolved DevTools invalid `<label for>` violation by replacing `<label for="s-thinking">` with `<div class="st-label" id="label-thinking">` and `aria-labelledby="label-thinking"` on the `s-thinking` radiogroup.
- **Cleaned Available Models:** Configured `index.html` and server `available_models` to strictly list the 2 supported models: Qwen 3.8 Flash Coder (IQ1_M) (`qwen3.8-flash-next-coder-iq1_m`) and Qwen 3.8 Flash General (Q2_0) (`qwen3.8-flash-next-q2_0`). Removed stray `.bak` config files.
- **Forceful Restart Endpoint (`POST /restart` and `POST /v1/restart`):** Added `svc.force_restart()` to `serve/server.py`. It immediately issues `SIGKILL` to `engine/strata` to abort any stuck reasoning loops or unresponsive runs, cleans up locks, and resets server state. In lazy mode, it returns the engine to an unloaded state, instantly dropping VRAM back to 8%.
- **Web GUI Monitor Control:** Added a "Force Restart" button to the "Model state" card in `serve/web/index.html`, `serve/web/app.js`, `serve/web/monitor.html`, and `serve/web/monitor.js`.
- **Monitor Dashboard Live System RAM Meter & Context Fill:** Replaced PCIe Gen3x8 tile with a live System RAM usage meter (`#i-memory` icon, formatted `X.X / Total GB`, subtext `% in use · X.X GB free`, live history sparkline scaled against total RAM) and swapped positions with the CPU meter so CPU is 6th and System RAM is 7th in the metrics grid. In the Context fill card, updated the second progress bar from whole-system "System RAM" to "Experts in System RAM" (tracking model resident experts in RAM via `arena_mib`), and replaced the redundant third bar (formerly GPU temperature, which is already tracked in metric tile #4) with "KV cache memory" (tracking actual attention KV cache consumption against total context capacity and active quantization precision like `K8V4` / `INT8`).
- **Unloaded Telemetry Reset:** When the engine is unloaded (e.g. after idle auto-unload or Force Restart), `close()` and `force_restart()` in `serve/server.py` reset cached runtime `self.info`, and `/metrics` strips out active expert cache attributes (`expert_slots`, `expert_cache_mib`, `arena_mib`) while `not self.loaded()`. On the frontend (`serve/web/app.js`), `isLoaded = live.state !== "unloaded"` guards ensure "Experts in VRAM", "Experts in System RAM", and "KV cache memory" cleanly show `–` and `0%` progress instead of retaining stale ghost allocations.
- **Reasoning Budget Intact:** No cap was placed on `reasoning_budget_tokens`, maintaining full multi-thousand-token reasoning capability for complex coding tasks.
- **`strata.sh` CLI Updates:** Updated `strata.sh` to recognize `"status": "ok"` for lazy readiness, and added `./strata.sh start [model]` and `./strata.sh select` for multi-model selection.

## Related

- Deployment: [RX 7600 XT CachyOS Deployment](rx-7600-xt-cachyos-deployment.md)
- Remote Access: [Cloudflare Tunnel Remote Exposure](cloudflare-tunnel-remote-exposure.md)
- Engine: [Strata](../entities/strata.md)

## Sources

1. User request for lazy loading, idle unload, model switching, D.L. AI branding, and logout — chat, 2026-10-10.
2. `serve/server.py` — modified `force_restart()`, `switch_model()`, `available_models()`, and route handlers.
3. `serve/web/tokens.css`, `serve/web/components.css`, `serve/web/index.html`, `serve/web/app.js` — theme, branding, and logout changes.
4. `strata-coder-iq1_m.json` — verified `"lazy_load": true` and `"idle_unload_s": 1800`.
5. `rocm-smi` — verified VRAM drops back to 8% upon restart/unload.

