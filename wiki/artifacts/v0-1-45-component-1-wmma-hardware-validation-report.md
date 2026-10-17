---
title: "Component 1: RDNA3 WMMA Hardware Validation & Dual-Tier Benchmark Report"
type: artifact
description: "Empirical validation and dual-tier benchmark comparing native WMMA tensor cores against non-WMMA fallback on AMD Radeon RX 7600 XT"
status: active
tags: [strata, v0.1.45, wmma, benchmark, amd, hip, gfx1102, rx7600xt]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Component 1: RDNA3 WMMA Hardware Validation & Dual-Tier Benchmark Report

## 1. Hardware Architecture & Verification Findings

* **Hardware Identity Confirmed via `rocm-smi`:**
  * **Accelerator:** AMD Radeon RX 7600 XT (Device ID: `0x7480`, Subsystem ID: `0x7605`, SKU: `EXT95094`).
  * **Architecture:** `gfx1102` (Navi 33 / RDNA3) with 16 GB dedicated VRAM, 64 KiB LDS, wave32 instruction execution.
  * **System RAM:** 32 GB DDR4 + ~20 GB pageable resident expert tier.
* **Why Upstream `tune_rocblas` Does Not Apply:**
  * Upstream commit `57c95d5f` introduced `tune_rocblas` specifically for older RDNA2 cards (`gfx1030`/`gfx1032`) because RDNA2 lacks matrix cores and `hipBLASLt` kernels, falling back to legacy rocBLAS.
  * On our `gfx1102` RDNA3 GPU, Strata compiles `src/prefill/wmma_gemm.cu` directly targeting `__gfx1102__` with native wave32 **hardware WMMA tensor instructions** (`__builtin_amdgcn_wmma_f32_16x16x16_f16_w32`).
  * Upstream's `rocblas_tuning.hpp` explicitly guards against `gfx1102` and requires `gfx103x`.
  * RDNA3 prompt GEMMs run directly on hardware tensor cores via `STRATA_HIP_WMMA=1`, safely bypassing rocBLAS.

---

## 2. Empirical Benchmark Results (Exhaustive Suite)

Evaluated on `Qwen3.8-Flash-Next Coder (IQ1_M)` under the exhaustive protocol (3 full repetitions with statistical medians, scaling up to deep 32K context `--long`).

### Tier 1: Official Strata Benchmark Suite (`tools/strata_bench.py`)

| Metric | Arm 1A (Native WMMA: `STRATA_HIP_WMMA=1`) | Arm 1B (Non-WMMA Fallback: `STRATA_HIP_WMMA=0`) | Impact of Hardware WMMA |
| :--- | :---: | :---: | :---: |
| **Chat Decode Throughput** | **24.00 tok/s** (19.90 – 32.40) | 24.20 tok/s (20.20 – 32.10) | Identical (memory-bound) |
| **Chat Time to First Token** | 1.98 s (1.77 – 2.07) | 1.90 s (1.74 – 2.00) | Within run variance |
| **4K Prompt Ingestion** | **299.80 tok/s** (292.80 – 300.60) | 265.90 tok/s (263.60 – 272.10) | **+12.75% faster prefill** |
| **4K TTFT** | **13.46 s** (13.42 – 13.79) | 15.17 s (14.82 – 15.31) | **-1.71 s off TTFT (-11.3%)** |
| **16K Prompt Ingestion** | **325.90 tok/s** (324.90 – 331.40) | 282.30 tok/s (281.70 – 287.40) | **+15.44% faster prefill** |
| **16K TTFT** | **49.32 s** (48.51 – 49.47) | 56.94 s (55.92 – 57.06) | **-7.62 s off TTFT (-13.4%)** |
| **32K Deep Context Ingestion** | **326.40 tok/s** (321.60 – 327.40) | 280.00 tok/s (280.00 – 282.00) | **+16.57% faster prefill** |
| **32K TTFT** | **98.24 s** (97.95 – 99.73) | 114.52 s (113.72 – 114.53) | **-16.28 s off TTFT (-14.2%)** |
| **Coding Agent Turn TTFT** | **11.58 s** (7.14 – 12.71) | 12.84 s (7.68 – 14.08) | **-1.26 s per turn (-9.8%)** |
| **Coding Agent Decode** | **27.40 tok/s** (22.60 – 33.70) | 25.80 tok/s (21.30 – 32.50) | **+6.2% faster decode** |
| **Coding Agent Cache Hit Rate**| 68.37% | 68.41% | Stable parity (~68.4%) |

### Tier 2: Custom Prompt Scaling Benchmark (`custom_wmma_bench.py`)

| Prompt Scale | Arm 1A (Native WMMA ON) | Arm 1B (WMMA Fallback OFF) | Speedup from Hardware WMMA |
| :--- | :---: | :---: | :---: |
| **512 tokens** | 326.97 ms (1,229.49 tok/s) | 333.30 ms (1,206.12 tok/s) | +1.9% |
| **1,024 tokens** | 322.69 ms (2,321.13 tok/s) | 338.73 ms (2,211.19 tok/s) | +4.9% |
| **2,048 tokens** | **355.46 ms (4,065.21 tok/s)** | 406.53 ms (3,554.50 tok/s) | **+14.4% faster** |
| **4,096 tokens** | **409.43 ms (6,931.67 tok/s)** | 466.51 ms (6,083.47 tok/s) | **+13.9% faster** |
| **8,192 tokens** | **404.61 ms (13,899.71 tok/s)**| 537.63 ms (10,460.65 tok/s) | **+32.9% faster** |

---

## 3. Conclusions & Active Baseline

1. **Hardware Tensor Speedup Validated:** Native WMMA delivers **+12.8% to +16.6% higher prompt throughput**, shaving **16.3 seconds off a 32K prompt** and **1.26 seconds off every coding agent turn**.
2. **`tune_rocblas` Bypassed by Design:** Because our RDNA3 GPU runs the native WMMA matrix-core kernel, rocBLAS is not in the execution path, confirming why `tune_rocblas` is unnecessary on this PC.
3. **Active Configuration:** `STRATA_HIP_WMMA=1` is preserved as the active baseline in `/mnt/data/Strata/strata-coder-iq1_m.json`.

## Sources

- Upstream Strata commit `477ac13c` (v0.1.45 tag) and commit `57c95d5f` (`tune_rocblas`).
- Local benchmark reports: `bench/results/arm1a_wmma_on` and `bench/results/arm1b_wmma_off`.
- System telemetry: `rocm-smi` on CachyOS Linux (device `0x7480`, `gfx1102`).
- Evaluation plan: [`wiki/artifacts/upstream-v0-1-45-evaluation-and-benchmark-plan.md`](upstream-v0-1-45-evaluation-and-benchmark-plan.md).
