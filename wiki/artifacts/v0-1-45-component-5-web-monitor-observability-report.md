---
title: "Component 5: Web Monitor & Observability Updates Validation Report"
type: artifact
description: "Validation of upstream e69cbfa5 (reasoning_effort False) and a091cdf6 (windowed Prometheus throughput gauges #2341)"
status: active
tags: [strata, v0.1.45, observability, prometheus, metrics, reasoning-effort, telemetry, server]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Component 5: Web Monitor & Observability Updates Validation Report

## 1. Feature Architecture & Problem Solved

* **Problem 1 (Prometheus Idle Metrics Decay `#2341` / commit `a091cdf6`):**
  * Previously, `/metrics/prometheus` exposed `llamacpp:prompt_tokens_seconds` and `llamacpp:predicted_tokens_seconds` as cumulative lifetime averages. When an inference server went idle, third-party dashboards (e.g. Grafana, llama.cpp dashboards) continued to display the throughput of the last request indefinitely instead of decaying to 0.
  * **Solution:** Added `self.scrape_bucket = (0, 0.0, 0, 0.0)` in `Service.__init__`. On every Prometheus scrape, the server now calculates throughput deltas strictly over the window elapsed since the previous scrape:
    $$\Delta_{\text{prompt}} = \frac{n_{\text{prompt}} - n_{\text{prev}}}{t_{\text{prompt}} - t_{\text{prev}}}, \quad \Delta_{\text{decode}} = \frac{n_{\text{gen}} - n_{\text{prev\_gen}}}{t_{\text{decode}} - t_{\text{prev\_decode}}}$$
    If no requests ran between scrapes, both gauges report 0, while cumulative counters (`prompt_tokens_total`, `tokens_predicted_total`) remain monotonically increasing.
* **Problem 2 (Explicit False Reasoning Preservation / commit `e69cbfa5`):**
  * In `Service.with_shared()`, requests that explicitly specified `"reasoning_effort": false` or `"enable_thinking": false` were improperly overridden by server/model reasoning defaults because `not req.get("reasoning_effort")` evaluated to `True` for boolean `False`.
  * **Solution:** Narrowed the fallback guard to `req.get("reasoning_effort") in (None, "")`, preserving explicit `False` so clients can unconditionally disable thinking without model interference.
* **Preservation of Local Web GUI Monitor Customizations:**
  * Confirmed upstream v0.1.45 did NOT modify `serve/monitor.html`.
  * Local enhancements remain 100% intact:
    * Custom dark mode styling and UI layout.
    * Real-time resident system RAM usage meter (swapped with CPU tile).
    * Live KV cache telemetry in Context fill card.
    * Unloaded state cleanup for expert meters.

---

## 2. Automated Test Suite Verification

* **Unit Tests Executed:**
  * `serve.test_server.PrometheusMetrics`:
    * `test_totals`: Verifies cumulative counter accounting.
    * `test_throughput_gauges_cover_the_window_between_scrapes` (Ported from `#2341`): Verifies throughput reporting during active traffic and immediate decay to 0 upon idle second scrape.
  * `serve.test_effort_paths.EffortPaths`:
    * Verified explicit `reasoning_effort: False` preserves `none` effort level and disables reasoning.
* **Test Results:** **13 / 13 tests passed in 1.750s — OK**.

---

## 3. Live Protocol & Endpoint Verification

Tested against the active `strata-server.service` daemon on port 8080:

1. **Explicit False Reasoning Live Test:**
   * Request: `POST /v1/chat/completions` with `"reasoning_effort": false`, asking "Reply with the single word PONG".
   * Response:
     ```json
     {
       "choices": [{"index": 0, "message": {"role": "assistant", "content": "PONG"}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 61, "completion_tokens": 3, "total_tokens": 64}
     }
     ```
   * Result: Immediate answer generated in 3 tokens with **zero thinking tokens**, verifying that reasoning was cleanly bypassed.

2. **Prometheus Scrape Window Live Test:**
   * **Scrape 1 (Right after inference request):**
     * `llamacpp:prompt_tokens_seconds`: `32.35 tok/s`
     * `llamacpp:predicted_tokens_seconds`: `12.86 tok/s`
   * **Scrape 2 (Immediately after, with no intermediate traffic):**
     * `llamacpp:prompt_tokens_seconds`: `0`
     * `llamacpp:predicted_tokens_seconds`: `0`
     * Cumulative counters preserved: `llamacpp:tokens_predicted_total 3`.
   * Result: Perfect decay behavior matching Prometheus / Grafana specifications.

---

## 4. Summary & Verification Status

| Feature / Fix | Verification Target | Status |
| :--- | :--- | :---: |
| **Commit `a091cdf6`** | Windowed Prometheus throughput gauges (`#2341`) | **VERIFIED & ACTIVE** |
| **Commit `e69cbfa5`** | Explicit False reasoning parameter preservation | **VERIFIED & ACTIVE** |
| **Local Customizations** | Dark theme, Resident RAM meter, Live KV telemetry | **PRESERVED & INTACT** |

---

## Sources

* Upstream Strata commits `a091cdf6` (`#2341`) and `e69cbfa5`.
* Unit test suites: `serve/test_server.py` and `serve/test_effort_paths.py`.
* Live endpoint verification on `http://127.0.0.1:8080/metrics/prometheus` and `http://127.0.0.1:8080/v1/chat/completions`.
