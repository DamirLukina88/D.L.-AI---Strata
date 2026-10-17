---
title: "Upstream v0.1.45 Enhancements: Evaluation and Dual-Tier Benchmark Plan"
type: artifact
description: "Evaluation, technical spec, validation protocol, and exhaustive dual-tier benchmarks for upstream v0.1.45 on RX 7600 XT"
status: active
tags: [strata, v0.1.45, benchmark, plan, wmma, qsa, tokenizer, thinking-budget, amd, hip, gfx1102]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Upstream v0.1.45 Enhancements: Evaluation and Dual-Tier Benchmark Plan

## 1. Executive Summary & Context

Upstream Strata has released **v0.1.45** (commit `477ac13c`, 264 commits ahead of local base). This document sets the definitive engineering plan to evaluate four candidate enhancements on our local system:

- **Host Hardware:** AMD Radeon RX 7600 XT (16 GB VRAM, `gfx1102` / RDNA3) on CachyOS Linux (ROCm 7.2.4 HIP backend) + Intel Core i5-10400 (6 cores, 12 threads) + 32 GB System RAM (with ~20 GB pageable resident expert tier).
- **Active Model Configuration:** Qwen 3.8 Flash Coder (`IQ1_M`), running under `strata-server.service` with local dynamic lazy loading, Web GUI force-restart, dark orange theme, and live KV cache telemetry.
- **Operating Policy:** **Strictly local execution.** Absolutely **zero git commits, branches, tags, or pushes**. All pristine safety snapshots are maintained in `/mnt/data/Strata-data/local_backups/v145_eval/`.
- **Execution Protocol:** **Step-by-step gatekeeper.** Each part is implemented, validated, and dual-benchmarked individually. Findings and metrics are reported to the user, who decides whether to **Keep** or **Revert** before the next part is initiated.

---

## 2. Safety Backups & Zero-Git Rollback Architecture

All safety backups are stored outside the git repository on the local NVMe storage:

```
/mnt/data/Strata-data/local_backups/v145_eval/
├── CMakeLists.txt
├── frontend.py
├── qsa_select.cu
├── server.py
├── strata                      (C++ engine binary: 25 MB)
├── strata-coder-iq1_m.json     (Active runtime config)
├── strata_tokenizer.py
└── test_server.py
```

### Rollback Commands by Component

| Component | Rollback Shell Command |
| :--- | :--- |
| **Component 1 (Architecture)** | Restore `STRATA_HIP_WMMA=1` in config if modified |
| **Component 2 (Tiled QSA Scorer)** | `cp /mnt/data/Strata-data/local_backups/v145_eval/qsa_select.cu src/kernels/cuda/qsa_select.cu`<br>`cp /mnt/data/Strata-data/local_backups/v145_eval/strata engine/strata` |
| **Component 3 (Thinking Budget)** | `cp /mnt/data/Strata-data/local_backups/v145_eval/server.py serve/server.py`<br>`cp /mnt/data/Strata-data/local_backups/v145_eval/frontend.py serve/frontend.py`<br>`cp /mnt/data/Strata-data/local_backups/v145_eval/test_server.py serve/test_server.py` |
| **Component 4 (Tokenizer Prefix)** | `cp /mnt/data/Strata-data/local_backups/v145_eval/strata_tokenizer.py tools/strata_tokenizer.py`<br>`cp /mnt/data/Strata-data/local_backups/v145_eval/server.py serve/server.py`<br>`rm -f serve/test_prompt_encoder.py` |

---

## 3. Decision Framework & Evaluation Thresholds (Aligned via /grill-me)

* **Progression:** Full sequential walkthrough (Component 1 &rarr; Component 2 &rarr; Component 3 &rarr; Component 4).
* **Acceptance Threshold:** Strict performance and stability threshold:
  * A change is **kept** only if it shows measurable gains (**&ge;2–3% latency/throughput improvement** or resolves an agent truncation failure) with zero stability regressions and no output quality degradation.
  * If the speedup is negligible (<2%) or introduces any issues, it is **reverted immediately**.
* **Benchmark Rigor:** **Exhaustive deep-context testing**: 3 full repetitions with statistical medians plus deep 32K context tests (`--long`) for every benchmark arm (~12–15 min per tier).
* **Interactive Gatekeeper:**
  * Implement &rarr; Validate &rarr; Dual-Benchmark &rarr; **Report Findings to User**.
  * **Wait for user decision (Keep vs Revert)** before proceeding to the next part.

---

## 4. Sequential Execution Plan & Dual-Tier Benchmarks

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                 Upstream v0.1.45 Dual-Tier Evaluation Pipeline                   │
│                                                                                  │
│   [ Part 1: Hardware Architecture Validation ]                                   │
│      ├── Verify gfx1102 WMMA hardware path vs RDNA2 rocBLAS fallback             │
│      ├── Tier 1: Official strata_bench.py (3 runs, up to 32K --long)             │
│      │     ├── Arm 1A: Native WMMA (STRATA_HIP_WMMA=1, Active Baseline)          │
│      │     └── Arm 1B: Non-WMMA Fallback (STRATA_HIP_WMMA=0)                     │
│      └── Tier 2: Custom wmma prompt GEMM scaling benchmark (512 - 8192 tokens)   │
│                                   │                                              │
│                                   ▼                                              │
│                    [ Decision Gate 1: User Review ]                              │
│                                   │                                              │
│                                   ▼                                              │
│   [ Part 2: HIP Tiled QSA Scorer (STRATA_SELECT_SIMT=1) ]                        │
│      ├── Port commit 4f21be87 to src/kernels/cuda/qsa_select.cu                  │
│      ├── Recompile HIP engine (ninja -C build-hip strata)                        │
│      ├── Validate via greedy decode parity + KL divergence check                 │
│      ├── Tier 1: Official strata_bench.py (3 runs, up to 32K --long, SIMT 0 vs 1)│
│      └── Tier 2: Custom deep-context TTFT & scoring bench (4K - 64K context)     │
│                                   │                                              │
│                                   ▼                                              │
│                    [ Decision Gate 2: Keep or Revert ]                           │
│                                   │                                              │
│                                   ▼                                              │
│   [ Part 3: Automatic Thinking Budget Protection (#984) ]                        │
│      ├── Port commits d0e990ba & 194c2688 (answer_room auto-reservation)        │
│      ├── Validate via serve/test_server.py -k ThinkingBudget & Anthropic tests   │
│      ├── Tier 1: Official strata_bench.py regression verification                │
│      └── Tier 2: Dual-API stress bench (OpenAI & Anthropic) under tight caps     │
│                                   │                                              │
│                                   ▼                                              │
│                    [ Decision Gate 3: Keep or Revert ]                           │
│                                   │                                              │
│                                   ▼                                              │
│   [ Part 4: Prompt Tokenizer Prefix Caching (#567 / #1852) ]                     │
│      ├── Port commit f13a870d (PromptEncoder in tools/strata_tokenizer.py)       │
│      ├── Validate via test_strata_tokenizer.py & test_prompt_encoder.py          │
│      ├── Tier 1: Official strata_bench.py multi-turn agent comparison            │
│      └── Tier 2: Custom 5-turn session tokenizer latency & memory profiling      │
│                                   │                                              │
│                                   ▼                                              │
│                    [ Decision Gate 4: Keep or Revert ]                           │
│                                   │                                              │
│                                   ▼                                              │
│   [ Final Deliverables: Wiki Artifact Report & Performance Walkthrough ]         │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

### Component 1: Hardware Architecture Validation (RDNA2 rocBLAS vs RDNA3 WMMA)

* **Objective:** Formally document and verify why `tune_rocblas` applies exclusively to RDNA2 (`gfx103x`) and benchmark our **AMD Radeon RX 7600 XT (`gfx1102` / RDNA3)** native **WMMA tensor core** execution path against a non-WMMA baseline across 4K, 16K, and 32K contexts.
* **Validation:**
  * Query `rocm-smi` confirming device ID `0x7480` / `gfx1102`.
  * Validate that `wmma_gemm.cu` compiles for `__gfx1102__` and that `rocblas_tuning.hpp` rejects non-`gfx103x` devices.
* **Dual-Tier Benchmark (Exhaustive: 3 runs, up to 32K `--long`):**
  * **Arm 1A (Current Native WMMA Baseline):** `STRATA_HIP_WMMA=1` active across chat decode, 4K prompt, 16K prompt, and 32K prompt (`--long`).
  * **Arm 1B (Non-WMMA Baseline Comparison):** `STRATA_HIP_WMMA=0` (WMMA disabled) across identical prompts.
  * **Custom Feature Benchmark (`custom_wmma_bench.py`):** Prompt prefill throughput and TTFT across token buckets (512, 1024, 2048, 4096, 8192) comparing WMMA on vs off.
* **Deliverable:** Present comparative metrics and tensor speedup report to user.
* **Revert Action:** Restore `STRATA_HIP_WMMA=1` in config if modified.

---

### Component 2: HIP Tiled QSA Scorer (`STRATA_SELECT_SIMT=1`)

* **Objective:** Port the 2D tiled cooperative FP32 QSA block scorer to HIP, bypassing the single-query warp kernel for deep-context prompt ingestion.
* **Implementation:**
  * Edit [`src/kernels/cuda/qsa_select.cu`](file:///home/damirl/Desktop/Strata/src/kernels/cuda/qsa_select.cu) to add `block_scores_simt` with geometry `<32, 64, 32, 4>` for `gfx1102`.
  * Build HIP engine: `ninja -C /mnt/data/Strata/build-hip strata`.
  * Copy new binary to `engine/strata`.
* **Validation:**
  * **Greedy Decode Parity:** Compare greedy token IDs on 5 diverse prompts.
  * **KL Divergence Verification:** If floating-point summation reordering causes token differences at late tokens, measure KL divergence to verify output distribution equivalence.
  * Check engine stderr output: `qsa select: FP32 tiled scorer (STRATA_SELECT_SIMT=1), tiles 32/64/32/4`.
* **Dual-Tier Benchmark (Exhaustive: 3 runs, up to 32K `--long`):**
  * **Tier 1 (Official Strata Suite):** `tools/strata_bench.py` with `STRATA_SELECT_SIMT=0` vs `STRATA_SELECT_SIMT=1` (3 runs each, 4K, 16K, 32K).
  * **Tier 2 (Custom Feature Benchmark `custom_qsa_simt_bench.py`):** Measure isolated QSA scoring time (ms) and prompt TTFT at 4K, 16K, 32K, and 64K context depths.
* **Decision Threshold:** Must achieve **&ge;2–3% TTFT reduction** on long prompts with zero regressions.
* **Revert Action if Rejected:**
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/qsa_select.cu /mnt/data/Strata/src/kernels/cuda/qsa_select.cu`
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/strata /mnt/data/Strata/engine/strata`

---

### Component 3: Automatic Thinking Budget Protection (`#984` / `d0e990ba` & `194c2688`)

* **Objective:** Prevent silent truncation in reasoning loops when coding agents send `max_tokens` (e.g. 1024 or 8192) without an explicit budget, and support Anthropic `thinking.budget_tokens`.
* **Implementation:**
  * Update [`serve/frontend.py`](file:///home/damirl/Desktop/Strata/serve/frontend.py) to map `thinking.budget_tokens` to `reasoning_budget_tokens`.
  * Update [`serve/server.py`](file:///home/damirl/Desktop/Strata/serve/server.py) with `ANSWER_ROOM_MIN_CAP = 1024` and auto-budgeting `budget = max_new - min(max(512, max_new // 4), max_new // 2)`.
  * Add unit tests to [`serve/test_server.py`](file:///home/damirl/Desktop/Strata/serve/test_server.py).
* **Validation:**
  * Automated unit tests: `serve/test_server.py -k ThinkingBudget` and `test_server.py -k Anthropic`.
  * **Dual-API Verification:** Test live HTTP requests against both:
    1. OpenAI format: `/v1/chat/completions` with `max_tokens: 1024`.
    2. Anthropic format: `/v1/messages` with `max_tokens: 1024` and `thinking: {"type": "enabled", "budget_tokens": 512}`.
* **Dual-Tier Benchmark:**
  * **Tier 1 (Official Strata Suite):** Run `tools/strata_bench.py` to ensure standard requests remain unaffected.
  * **Tier 2 (Custom Feature Benchmark `custom_thinking_budget_bench.py`):**
    * Stress-test complex multi-step reasoning queries under strict token caps (`max_tokens: 512`, `1024`, `2048`, `8192`) without explicit budget.
    * Measure Before vs After:
      * **Failure rate:** Truncated inside `<think>` with 0 output tokens and `finish_reason: length`.
      * **Success rate:** Auto-closed reasoning loop with complete code answer delivered and `finish_reason: stop`.
* **Decision Threshold:** Eliminates 0-token truncation failures on capped agent calls while preserving user-specified budgets.
* **Revert Action if Rejected:**
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/server.py /mnt/data/Strata/serve/server.py`
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/frontend.py /mnt/data/Strata/serve/frontend.py`
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/test_server.py /mnt/data/Strata/serve/test_server.py`

---

### Component 4: Prompt Tokenizer Prefix Caching (`#567` / `#1852` / `f13a870d`)

* **Objective:** Eliminate redundant BPE tokenization on multi-turn conversations by resuming from the last special-token boundary.
* **Implementation:**
  * Add `encode_marked`, `common_prefix_len`, `plain_agree_until`, and `PromptEncoder` to [`tools/strata_tokenizer.py`](file:///home/damirl/Desktop/Strata/tools/strata_tokenizer.py).
  * Integrate `PromptEncoder` into [`serve/server.py`](file:///home/damirl/Desktop/Strata/serve/server.py).
  * Add [`serve/test_prompt_encoder.py`](file:///home/damirl/Desktop/Strata/serve/test_prompt_encoder.py).
* **Validation:**
  * Run test suite: `/mnt/data/Strata/.venv/bin/python -m unittest tools/test_strata_tokenizer.py serve/test_prompt_encoder.py`.
  * Assert `cached_token_ids == fresh_token_ids` on 5 realistic multi-turn conversation traces.
* **Dual-Tier Benchmark:**
  * **Tier 1 (Official Strata Suite):** `tools/strata_bench.py` measuring the 5-turn coding agent scenario.
  * **Tier 2 (Custom Feature Benchmark `custom_tokenizer_prefix_bench.py`):**
    * Simulate a realistic 5-turn coding conversation growing from 2K &rarr; 6K &rarr; 12K &rarr; 24K &rarr; 36K tokens.
    * Measure wall-clock ms saved per turn (uncached vs cached).
    * Measure memory footprint of `PromptEncoder` across 4 kept conversation slots (assert <5 MB).
* **Decision Threshold:** Measurable tokenization latency reduction (&ge;50–200 ms on deep turns) with 100% token equivalence and negligible memory overhead.
* **Revert Action if Rejected:**
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/strata_tokenizer.py /mnt/data/Strata/tools/strata_tokenizer.py`
  * `cp /mnt/data/Strata-data/local_backups/v145_eval/server.py /mnt/data/Strata/serve/server.py`
  * `rm -f /mnt/data/Strata/serve/test_prompt_encoder.py`

---

## 5. Final Deliverable Artifacts

1. **Benchmark Report Artifact:** Compile all empirical numbers into [`wiki/artifacts/v0-1-45-optimizations-and-tuning-report.md`](file:///home/damirl/Desktop/Strata/wiki/artifacts/v0-1-45-optimizations-and-tuning-report.md).
2. **Decision Log:** Record adoption decisions in [`wiki/decisions/`](file:///home/damirl/Desktop/Strata/wiki/decisions/).
3. **Walkthrough Document:** Summary walkthrough in `walkthrough.md`.

## Sources

- Upstream Strata commit `477ac13c` (v0.1.45 tag) and upstream commits `57c95d5f`, `4f21be87`, `d0e990ba`, `194c2688`, `f13a870d`.
- Local configuration `/mnt/data/Strata/strata-coder-iq1_m.json` and hardware profile `AMD Radeon RX 7600 XT` (`gfx1102`).
- Previous optimization benchmark records: [`wiki/artifacts/v0-1-43-optimization-benchmark-report.md`](file:///home/damirl/Desktop/Strata/wiki/artifacts/v0-1-43-optimization-benchmark-report.md) and [`wiki/decisions/rx-7600-xt-cachyos-deployment.md`](file:///home/damirl/Desktop/Strata/wiki/decisions/rx-7600-xt-cachyos-deployment.md).
