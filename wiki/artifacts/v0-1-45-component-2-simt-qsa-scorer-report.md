---
title: "Component 2: HIP FP32 Tiled QSA Scorer Validation & Benchmark Report"
type: artifact
description: "Implementation, numerical verification, and dual-tier benchmark for upstream commit 4f21be87 (STRATA_SELECT_SIMT=1) on AMD Radeon RX 7600 XT"
status: active
tags: [strata, v0.1.45, qsa, simt, benchmark, amd, hip, gfx1102, rx7600xt]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Component 2: HIP FP32 Tiled QSA Scorer Validation & Benchmark Report

## 1. Feature Architecture & Porting Implementation

* **Port Target:** Upstream Strata v0.1.45 commit `4f21be87` ported the FP32 tiled QSA block scorer (`STRATA_SELECT_SIMT=1`) to AMD HIP.
* **Problem Solved:** On HIP architectures prior to RDNA4 (`gfx12`), Strata previously lacked a fast tensor-core scorer in the prompt path (`qsa_block_scores_tc` unconditionally returned `false`), forcing all prompt query-key block scoring onto the legacy warp kernel (`qsa_block_scores`).
* **Kernel Implementation Details (`src/kernels/cuda/qsa_select.cu`):**
  * Added `<atomic>` include and `sel_gfx103_device()` device inspection routine.
  * Templatized `block_scores_simt_kernel<int QT, int NB, int KC, int TN>` with compile-time assertions for float4 loads and 256 threads per CTA.
  * Created `block_scores_simt(...)` launch helper configuring tiles:
    * RDNA2 (`gfx103x`): `32/128/16/8` CTA geometry.
    * RDNA3 (`gfx1102`) & others: `32/64/32/4` CTA geometry.
  * Hooked `qsa_block_scores_tc` under `#if defined(__HIPCC__)`:
    * Enabled opt-in activation via `STRATA_SELECT_SIMT=1`.
    * Prints startup banner: `qsa select: FP32 tiled scorer (STRATA_SELECT_SIMT=1), tiles 32/64/32/4`.
* **Zero-Git Local Implementation:**
  * Byte-identical code parity with upstream commit `4f21be87:src/kernels/cuda/qsa_select.cu` verified via `git diff`.
  * Pre-modification baseline safely preserved in `/mnt/data/Strata-data/local_backups/v145_eval/qsa_select.cu`.

---

## 2. Tier 2: Microbenchmark & Numerical Accuracy Validation (`qsa_select_bench`)

Evaluated directly via the upstream GPU microbenchmark harness (`src/kernels/qsa_select_bench.cpp`) comparing the baseline warp scorer against the new FP32 tiled scorer across context depths under a 262,144-cell capacity (256 queries per batch, 20 repetitions each).

### Numerical Accuracy & Selection Parity Gates

* **FP64 Host Reference Gate:** **PASS**
  * Score scale: `269`
  * Warp kernel max relative error: `3.16e-05`
  * FP32 tiled scorer max relative error: `5.02e-05` (`1.9e-07` of scale, well within the `1e-5` gate).
* **Selection Parity:** **100% Identical**
  * Identical selections across queries: **256 / 256 (100.0%)**.
  * Differing cells: **0.0000%** across all context depths.

### Block Scoring Latency Across Context Depths

| Context Depth | Active Blocks | Legacy Warp Scorer | FP32 Tiled Scorer (`SIMT=1`) | Scoring Latency Speedup | Selections Match |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **4,096 tokens (4K)** | 1,025 | 0.653 ms | **0.193 ms** | **3.38x faster** | 256 / 256 (100%) |
| **16,384 tokens (16K)** | 4,097 | 2.034 ms | **0.445 ms** | **4.57x faster** | 256 / 256 (100%) |
| **32,768 tokens (32K)** | 8,193 | 3.489 ms | **0.861 ms** | **4.05x faster** | 256 / 256 (100%) |
| **65,536 tokens (64K)** | 16,385 | 6.654 ms | **1.134 ms** | **5.87x faster** | 256 / 256 (100%) |
| **131,072 tokens (131K)** | 32,769 | 11.014 ms | **2.002 ms** | **5.50x faster** | 256 / 256 (100%) |

---

## 3. Tier 1: End-to-End System Benchmark (`tools/strata_bench.py`)

Evaluated on `Qwen3.8-Flash-Next Coder (IQ1_M)` under the official exhaustive protocol (3 full repetitions across short chat, 4K prompt, 16K prompt, deep 32K context `--long`, and the 5-turn coding agent session).

### Comparative Benchmark Results

| Metric / Scenario | Arm 1A Baseline (`SIMT=0`, Warp Scorer) | Arm 2B Candidate (`SIMT=1`, FP32 Tiled) | Empirical Impact of Tiled SIMT |
| :--- | :---: | :---: | :---: |
| **Chat First Token (TTFT)** | 1.98 s (1.77 – 2.07) | **1.87 s** (1.80 – 2.00) | **-0.11 s (-5.56% faster)** |
| **Chat Decode Throughput** | 24.00 tok/s (19.90 – 32.40) | 23.50 tok/s (19.20 – 34.40) | Flat (memory-bound, within variance) |
| **4K Prompt Ingestion** | 299.80 tok/s (292.80 – 300.60) | **300.40 tok/s** (295.00 – 301.20) | +0.6 tok/s (+0.20%) |
| **4K TTFT** | 13.46 s (13.42 – 13.79) | **13.43 s** (13.39 – 13.68) | -0.03 s off TTFT |
| **16K Prompt Ingestion** | 325.90 tok/s (324.90 – 331.40) | **332.90 tok/s** (332.10 – 334.60) | **+7.0 tok/s (+2.15% faster)** |
| **16K TTFT** | 49.32 s (48.51 – 49.47) | **48.28 s** (48.05 – 48.41) | **-1.04 s off TTFT** |
| **32K Prompt Ingestion** | 326.40 tok/s (321.60 – 327.40) | **331.80 tok/s** (331.70 – 332.90) | **+5.4 tok/s (+1.65% faster)** |
| **32K TTFT** | 98.24 s (97.95 – 99.73) | **96.66 s** (96.35 – 96.69) | **-1.58 s off TTFT** |
| **Agent Follow-Up Turn TTFT** | 11.58 s (7.14 – 12.71) | **11.45 s** (7.06 – 12.11) | **-0.13 s per turn** |
| **Agent Decode Throughput** | 27.40 tok/s (22.60 – 33.70) | 26.80 tok/s (23.20 – 34.00) | Within standard run variance |
| **Agent Cache Hit Rate** | 68.37% (68.08 – 68.41) | 68.34% (68.32 – 68.39) | Identical KV cache behavior |

### Statistical Key Takeaways
1. **Statistically Significant High-Context Speedup:** At 16K, every single candidate run (332.10, 332.90, 334.60 tok/s) beat the highest run in baseline (331.40 tok/s). The prompt prefill throughput improved by **+7.0 tok/s**, shaving **1.04 seconds off 16K TTFT** and **1.58 seconds off 32K TTFT**.
2. **QSA Scoring Latency Reduced by up to 5.87x:** The microbenchmark isolated the kernel and proved that scoring time drops from 6.65 ms to 1.13 ms at 64K, and 11.01 ms to 2.00 ms at 131K.
3. **Flawless Quality & Accuracy:** 0 differing cells (0.0000%), 256/256 identical top-k selections across all contexts, and numerical error within `1.9e-07` of scale vs FP64 host reference.

---

## Sources

* Upstream Strata commit `4f21be87` (commit log and diff).
* Local microbenchmark harness: `src/kernels/qsa_select_bench.cpp` compiled via HIP for `gfx1102`.
* Local backups: `/mnt/data/Strata-data/local_backups/v145_eval/`.
* Evaluation plan: [`wiki/artifacts/upstream-v0-1-45-evaluation-and-benchmark-plan.md`](upstream-v0-1-45-evaluation-and-benchmark-plan.md).
