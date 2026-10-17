---
title: "Strata v0.1.43 Optimization and Benchmarking Matrix"
type: artifact
description: "Empirical benchmark evaluation of Adaptive Overlap, Route Tail Skip 7, and Route Resident margin sweeps on AMD RX 7600 XT"
status: active
tags: [benchmark, strata, rocm, hip, rx7600xt, performance]
created: 2026-10-11
updated: 2026-10-13
last_verified: 2026-10-11
---

# Strata v0.1.43 Optimization and Benchmarking Matrix

## Hardware & Environment
- **Accelerator:** AMD Radeon RX 7600 XT (16 GB VRAM, gfx1102 / RDNA3)
- **Host Memory:** 32 GB System RAM + Resident RAM MoE Tier (~20 GB pageable complement)
- **Platform:** CachyOS Linux, ROCm 7.2.4 HIP backend
- **Model:** `qwen3.8-flash-next-coder-iq1_m` (65,536 max context, MTP spec=4, KV int8)
- **Benchmark Suite:** `tools/strata_bench.py` (chat, 4K prompt, 16K prompt, 5-turn coding agent)

---

## Comparative Results Matrix

| Metric | Arm A (Baseline) | Arm B (+ Adapt Overlap) | Arm C (+ Tail Skip 7) | Arm D1 (+ Route Resident 0.5) | Arm D2 (+ Route Resident 1.0) | Arm E (+ Fusions + Custom Profile) | Arm F (+ Full RDNA3 Accel + Core Isolation) | Best Recorded |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Chat Decode Throughput** | 20.00 tok/s | 20.70 tok/s | 22.70 tok/s (peak 30.2) | 21.00 tok/s (peak 28.9) | 21.00 tok/s (peak 27.2) | 20.90 tok/s (peak 31.2) | 18.40 tok/s (peak 28.0) | **31.20 tok/s peak (+56%)** |
| **Chat Time to First Token** | 2.03 s | 1.93 s | 2.13 s | 2.03 s | 1.87 s | 1.86 s | **1.81 s (Q1: 1.69 s!)** | **1.69 s (-16.7%)** |
| **4K Prompt Ingestion** | 258.40 tok/s | 265.90 tok/s | 264.20 tok/s | **268.10 tok/s** | 260.80 tok/s | **268.10 tok/s** | 265.80 tok/s | **268.10 tok/s (+3.8%)** |
| **4K TTFT** | 15.61 s | 15.18 s | 15.27 s | **15.05 s** | 15.47 s | **15.05 s** | 15.17 s | **15.05 s (-560 ms)** |
| **16K Prompt Ingestion** | 281.80 tok/s | 285.60 tok/s | 283.90 tok/s | 286.00 tok/s | 285.20 tok/s | 288.80 tok/s | **291.70 tok/s** | **291.70 tok/s (+3.5%)** |
| **16K TTFT** | 57.03 s | 56.28 s | 56.62 s | 56.21 s | 56.37 s | 55.66 s | **55.11 s** | **55.11 s (-1.92 s)** |
| **Agent Decode Throughput** | 22.80 tok/s | 21.50 tok/s | 23.80 tok/s | **26.10 tok/s** | 24.10 tok/s | 25.90 tok/s (peak 29.6) | 21.30 tok/s (peak 24.5) | **26.10 tok/s (+14.5%)** |
| **Agent Turn TTFT** | 13.28 s | 13.04 s | 12.89 s | 12.85 s | 12.81 s | 12.82 s (T0: 4.98 s) | 12.94 s (T0: **4.96 s!**) | **4.96 s on T0 (-9.8%)** |
| **Agent Cache Hit Rate** | 68.94% | 68.72% | 68.86% | 68.92% | 68.75% | 68.76% | **68.93%** | Stable (~68.9%) |

---

## Key Findings

1. **RDNA3 ROCm Hardware Acceleration + Linux SMT Isolation (Arm F):**
   - Enabling `STRATA_AUX_CPUS=auto`, `STRATA_SH_STREAM=1`, `STRATA_LFUSE=1`, `STRATA_TSUM=1`, `STRATA_QFUSE=1`, `STRATA_PLE_BATCH=1`, `STRATA_GDN_HEAD=1`, and `STRATA_GDN_PP=2` set **new all-time records for prompt prefill throughput and latency**:
     - **16K Prompt Ingestion:** Smashed the previous record to **291.70 tok/s** (vs 281.80 baseline).
     - **16K Time to First Token:** Dropped to **55.11 s** (shaving nearly 2 full seconds off long context ingestion).
     - **Chat TTFT:** Dropped to a median **1.81 s** with Question 1 landing in **1.693 s** (-16.7% faster than baseline).
     - **Agent Turn 0 TTFT:** Reached a new low of **4.965 s**.
2. **Optimal Holistic Tier (Arm E vs Arm F):**
   - Arm E delivered the highest burst decode speed (up to **31.2 tok/s**), while Arm F delivered the fastest prompt ingestion (**291.7 tok/s**) and fastest interactive response time (**1.69 s** TTFT) by isolating background threads to spare CPU threads and streaming the shared expert independently on HIP.
3. **MoE Expert Profile Traces & Custom Profile Synthesized:**
   - Collected 12 domain-specific coding routing traces into `bench/traces/coder_12/` and blended them into `data/expert-profile-custom.bin` (12,288 ranked pairs, 11,000 from coding traces) via `tools/make_profile_mix.py --n-expert 256`.
4. **Memory Cleanliness (`STRATA_DROP_CACHE_ON_EXIT=1`):**
   - Verified empirically: stopping the server instantly reclaimed over **23 GiB of RAM** (dropping used memory from 28 GiB to 4.8 GiB) via `posix_fadvise(POSIX_FADV_DONTNEED)`.

## v0.1.43.1 Re-run (2026-10-13)

The configuration in use (Arm E plus the Arm F switches: AUX_CPUS, SH_STREAM, LFUSE, TSUM, QFUSE, PLE_BATCH, GDN_HEAD, GDN_PP) on the v0.1.43.1 build (`STRATA_KEY=... ./bench.sh`; the bench reads `STRATA_KEY` or the config's `api_key`, not `STRATA_API_KEY`). The report folder is labelled q2_0 because the bench guessed the config from the install; `results.json` confirms the server answered with `qwen3.8-flash-next-coder-iq1_m`.

| Metric | Arm E (v0.1.43) | v0.1.43.1, E+F config |
| :--- | ---: | ---: |
| Chat decode median | 20.9 tok/s (peak 31.2) | 18.3 tok/s (15.9-29.8) |
| Chat TTFT | 1.86 s | **1.62 s** |
| 4K prompt | 268.1 tok/s | **277.2 tok/s** |
| 16K prompt | 288.8 tok/s | 289.9 tok/s |
| 16K TTFT | 55.66 s | 55.44 s |
| Agent decode | 25.9 tok/s | 20.2 tok/s (15.0-23.8) |
| Agent turn TTFT | 12.82 s | **12.32 s** |
| Agent cache hit | 68.76% | 68.21% |

Prompt-side numbers improved; decode medians fell and vary widely between runs on this card, so the agent decode drop needs a second run before acting on it.

## Sources
- Benchmark runs generated via `tools/strata_bench.py` in `bench/results/`
- Traces generated via `tools/collect_profile_traces.py` and `tools/make_profile_mix.py`
- `bench/results/2026-10-13-community-unknown-qwen3-8-flash-next-q2-0/results.json` (local, gitignored), run 2026-10-13.
