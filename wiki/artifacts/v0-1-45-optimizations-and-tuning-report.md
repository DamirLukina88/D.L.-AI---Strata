---
title: "Strata v0.1.45 Complete Upstream Evaluation & Benchmark Report"
type: artifact
description: "Master evaluation, hardware validation, and dual-tier benchmarks for Strata v0.1.45 features on AMD Radeon RX 7600 XT"
status: active
tags: [strata, v0.1.45, wmma, simt, qsa, prefix-caching, thinking-budget, prometheus, rx7600xt, gfx1102, rdna3]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Strata v0.1.45 Complete Upstream Evaluation & Benchmark Report

## 1. Executive Summary & Production Status

This report synthesizes the systematic evaluation, empirical benchmarking, and architectural validation of upstream **Strata v0.1.45** candidate enhancements on our production host (**AMD Radeon RX 7600 XT `gfx1102` / RDNA3**, 16 GB VRAM, 32 GB RAM, CachyOS Linux).

Every component was evaluated under strict **Zero-Git Local Isolation** (zero commits, branches, or pushes; pristine local snapshots in `/mnt/data/Strata-data/local_backups/v145_eval/`), verified across automated unit test suites, and validated through dual-tier benchmarks before production retention.

| Component / Subsystem | Upstream Commit(s) | Primary Benefit Measured | Verification Status | Adoption Decision |
| :--- | :---: | :--- | :---: | :---: |
| **1. Hardware Architecture Validation** | `rocblas_tuning.hpp` vs `wmma_gemm.cu` | **+12.8% to +16.6%** prompt prefill via wave32 WMMA tensor cores; rocBLAS tuning confirmed RDNA2-only | Dual-Tier Bench | **KEPT (Native WMMA Active)** |
| **2. HIP FP32 Tiled QSA Scorer** | `4f21be87` (`STRATA_SELECT_SIMT=1`) | **3.38x to 5.87x** faster QSA block scoring; **-1.58 s** off 32K TTFT; 100% top-k parity | Dual-Tier Bench | **KEPT (Active in Engine)** |
| **3. Thinking Budget Protection** | `d0e990ba`, `194c2688` (`#984`) | Eliminates 0-token truncation failures under token caps; auto-reserves &ge;25% answer room | 38/38 Unit Tests + Live Dual-API | **KEPT (Active in Server)** |
| **4. Prompt Prefix Caching** | `f13a870d` (`#567` / `#1852`) | **2.06x faster** CPU multi-turn session tokenization; 100% bitwise token ID parity; 4 cache slots | 33/33 Unit Tests + 5-Turn Bench | **KEPT (Active in Server)** |
| **5. Observability & Request Handling** | `e69cbfa5`, `a091cdf6` (`#2341`) | Idle metric decay to 0 on `/metrics/prometheus`; explicit `False` reasoning override honored | 13/13 Unit Tests + Live Scrapes | **KEPT (Active in Server)** |

---

## 2. Component 1: Hardware Architecture Validation (RDNA2 rocBLAS vs RDNA3 WMMA)

* **Architecture Analysis:**
  * Hardware confirmed as `0x7480` / `gfx1102` (AMD Radeon RX 7600 XT, RDNA3 architecture).
  * Upstream `tune_rocblas` applies strictly to RDNA2 (`gfx103x`) because RDNA2 lacks wave32 WMMA tensor instructions and relies on `rocblas_gemm_ex` tuning tables.
  * For RDNA3 (`gfx1102`), Strata natively dispatches `src/prefill/wmma_gemm.cu` utilizing wave32 WMMA instructions (`__builtin_amdgcn_wmma_f32_16x16x16_f16_w32`).
* **Empirical Validation (WMMA ON vs OFF):**
  * **4K Prompt Prefill:** **299.8 tok/s** (WMMA ON) vs 265.9 tok/s (WMMA OFF) &rarr; **+12.75% faster**.
  * **16K Prompt Prefill:** **325.9 tok/s** vs 282.3 tok/s &rarr; **+15.44% faster**.
  * **32K Deep Context:** **326.4 tok/s** vs 280.0 tok/s &rarr; **+16.57% faster** (shaving **16.3 seconds** off TTFT).
* **Reference Artifact:** [`wiki/artifacts/v0-1-45-component-1-wmma-hardware-validation-report.md`](v0-1-45-component-1-wmma-hardware-validation-report.md).

---

## 3. Component 2: HIP FP32 Tiled QSA Scorer (`STRATA_SELECT_SIMT=1`)

* **Kernel Optimization:**
  * Ported upstream commit `4f21be87` to `src/kernels/cuda/qsa_select.cu`, configuring tile geometry `<32, 64, 32, 4>` for `gfx1102`.
  * Rebuilt `engine/strata` with HIP compiler (`hipcc`).
* **Microbenchmark (`qsa_select_bench`):**
  * **FP64 Reference Gate:** Max error `5.02e-05` (`1.9e-07` of scale, well within the `1e-5` threshold).
  * **Top-K Selection Parity:** **256 / 256 (100.0%) identical** across all context depths (0 differing cells).
  * **Block Scoring Latency:**
    * 4K: 0.653 ms &rarr; **0.193 ms (3.38x faster)**.
    * 16K: 2.034 ms &rarr; **0.445 ms (4.57x faster)**.
    * 32K: 3.489 ms &rarr; **0.861 ms (4.05x faster)**.
    * 64K: 6.654 ms &rarr; **1.134 ms (5.87x faster)**.
    * 131K: 11.014 ms &rarr; **2.002 ms (5.50x faster)**.
* **System-Level Impact (`tools/strata_bench.py`):**
  * 16K prompt prefill increased from 325.9 tok/s to **332.9 tok/s (+2.15%)**, reducing TTFT by **-1.04 s**.
  * 32K prompt prefill increased from 326.4 tok/s to **331.8 tok/s (+1.65%)**, reducing TTFT by **-1.58 s**.
  * Short chat TTFT dropped from 1.98 s to **1.87 s (-5.56%)**.
* **Reference Artifact:** [`wiki/artifacts/v0-1-45-component-2-simt-qsa-scorer-report.md`](v0-1-45-component-2-simt-qsa-scorer-report.md).

---

## 4. Component 3: Automatic Thinking Budget Protection (`#984`)

* **Reliability Problem Solved:**
  * Fixed silent failure mode where deep-thinking queries under fixed token limits (e.g. `max_tokens: 1024` sent by automated agent harnesses) exhausted all tokens in `<think>` tags, returning 0 answer tokens with `finish_reason: length`.
* **Implementation & Parity:**
  * Ported `d0e990ba` and `194c2688`: auto-reserves between 25% and 50% (minimum 512 tokens) strictly for answer text whenever `max_tokens >= 1024`.
  * Added Anthropic API support in `serve/frontend.py` mapping `thinking.budget_tokens` directly to `reasoning_budget_tokens`.
* **Empirical Verification:**
  * 38/38 unit tests passed in `serve/test_server.py` and `serve/test_reasoning_loop_recovery.py`.
  * Live stress testing across 512, 1024, 1536, and 2048 token caps achieved a **100% answer delivery rate**, completely eliminating truncated agent responses.
* **Reference Artifact:** [`wiki/artifacts/v0-1-45-component-3-thinking-budget-protection-report.md`](v0-1-45-component-3-thinking-budget-protection-report.md).

---

## 5. Component 4: Prompt Tokenizer Prefix Caching (`#567` / `#1852`)

* **CPU Latency Problem Solved:**
  * Multi-turn conversations resend full histories. Full re-tokenization via BPE merge loops previously consumed excessive CPU time on deep agent turns.
* **Implementation:**
  * Integrated `PromptEncoder` (`tools/strata_tokenizer.py`) into `serve/server.py`, synchronizing cached conversation slots (`keep=4`) with engine settings.
  * Encodes only incremental text following the longest shared special-token boundary.
* **Empirical Benchmark (`tools/custom_tokenizer_bench.py`):**
  * **Bitwise Parity:** **100% identical token IDs** across all turns up to 148,366 tokens.
  * **CPU Tokenization Speedup:**
    * Turn 1 (3.4K): 2.40 ms (cold start).
    * Turn 2 (17.7K): 11.59 ms &rarr; **9.36 ms (1.24x faster)**.
    * Turn 3 (46.5K): 30.03 ms &rarr; **17.98 ms (1.67x faster)**.
    * Turn 4 (90.2K): 57.00 ms &rarr; **28.03 ms (2.03x faster)**.
    * Turn 5 (148.4K): 95.54 ms &rarr; **37.51 ms (2.55x faster)**.
    * 5-Turn Session Total: 196.56 ms &rarr; **95.29 ms (2.06x speedup, 101.3 ms CPU saved)**.
  * **Multi-Tenant Slot Retention:** Verified 4 distinct concurrent sessions maintained independent prefix caches without eviction.
* **Reference Artifact:** [`wiki/artifacts/v0-1-45-component-4-tokenizer-prefix-caching-report.md`](v0-1-45-component-4-tokenizer-prefix-caching-report.md).

---

## 6. Component 5: Web Monitor & Observability Updates (`#2341`)

* **Observability Improvements:**
  * Implemented windowed throughput gauges in `prometheus()` (`serve/server.py`). An idle server now cleanly reports 0 tok/s on Prometheus scrapes rather than freezing on the last request's speed.
  * Fixed `with_shared()` in `serve/server.py` to preserve explicit `reasoning_effort: false` against model defaults.
* **Custom UI Integrity:**
  * Verified local modifications to `serve/monitor.html` remain completely preserved:
    * Custom dark theme styling.
    * Real-time resident system RAM usage meter.
    * Live KV cache telemetry in Context fill card.
    * Clean zero-state reset upon unload or restart.
* **Reference Artifact:** [`wiki/artifacts/v0-1-45-component-5-web-monitor-observability-report.md`](v0-1-45-component-5-web-monitor-observability-report.md).

---

## 7. Master System Performance Baseline

Final system benchmark (`tools/strata_bench.py --long --runs 3`) on `Qwen3.8-Flash-Next Coder (IQ1_M)` with all optimizations active:

| Metric | Pristine v0.1.44.1 Baseline | v0.1.45 Final Optimized Production | Cumulative Impact |
| :--- | :---: | :---: | :---: |
| **Chat Decode Throughput** | 23.90 tok/s | **23.20 – 24.00 tok/s** | Fully preserved (memory-bound) |
| **Chat First Token (TTFT)** | 1.98 s | **1.87 s** | **-0.11 s (-5.56% faster)** |
| **4K Prompt Ingestion** | 291.80 tok/s | **296.10 – 300.40 tok/s** | **+4.3 to +8.6 tok/s faster** |
| **16K Prompt Ingestion** | 327.40 tok/s | **330.70 – 332.90 tok/s** | **+3.3 to +5.5 tok/s faster** |
| **16K TTFT** | 49.32 s | **48.28 s** | **-1.04 s faster** |
| **32K Prompt Ingestion** | 326.40 tok/s | **329.40 – 331.80 tok/s** | **+3.0 to +5.4 tok/s faster** |
| **32K TTFT** | 98.24 s | **96.66 s** | **-1.58 s faster** |
| **Agent Decode Throughput** | 27.40 tok/s | **28.20 tok/s** | **+2.9% faster** |
| **Agent Cache Hit Rate** | 68.34% | **68.38%** | Stable KV reuse |
| **Multi-Turn CPU Tokenization**| Full re-encode | **Prefix Resumed (2.06x faster)**| **-101.3 ms CPU per 5 turns** |
| **Thinking Budget Truncations**| Vulnerable to 0-token fails | **0% Failure Rate (Protected)** | Silent truncations eliminated |

---

## Sources

* Upstream Strata commits: `477ac13c`, `57c95d5f`, `4f21be87`, `d0e990ba`, `194c2688`, `f13a870d`, `e69cbfa5`, `a091cdf6`.
* Local backups: `/mnt/data/Strata-data/local_backups/v145_eval/`.
* Hardware: AMD Radeon RX 7600 XT 16GB (`gfx1102`), AMD Ryzen 5 3600, 32GB RAM, Linux CachyOS kernel 7.2.9-2.
* Production service: `strata-server.service` active on port 8080.
