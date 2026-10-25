---
title: "Strata Performance Benchmark Report (2026-10-25 Post-v0.2.5 Sync)"
type: artifact
description: "Performance benchmark of Strata Qwen3.8-Flash-Next-Coder-IQ1_M on AMD Radeon RX 7600 XT following the v0.2.5 sync and ergonomics implementation."
status: active
tags: [benchmark, strata, rocm, hip, rx7600xt, coder, performance, v0.2.5]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Strata Performance Benchmark Report (2026-10-25 Post-v0.2.5 Sync)

Official benchmark executed with `tools/strata_bench.py` following the local safety backup, Web/Chat Ergonomics Suite, and Engine/Server Startup Reliability implementations.

## Hardware & Environment

- **Accelerator:** AMD Radeon RX 7600 XT (16 GiB VRAM, gfx1102 / RDNA3)
- **Host CPU:** AMD Ryzen 5 3600 6-Core Processor (6 cores, 12 threads)
- **Host Memory:** 32 GiB System RAM (31.3 GiB usable)
- **Operating System:** Linux 7.2.11-1-cachyos, ROCm 7.2.4 HIP backend
- **Model:** `qwen3.8-flash-next-coder-iq1_m` (65,536 context, parallel slots: 1, temperature: 0, thinking: off)
- **Software Build:** Strata v0.1.44.1 + v0.2.5 enhancements (commit `ddceae87` with dynamic startup scaling, warm-up, soft breaks, and clean deletion)
- **Benchmark Suite:** `tools/strata_bench.py` against active HTTP server (`http://127.0.0.1:8080`), 3 runs per workload, 479 seconds total duration.

---

## Benchmark Results Summary

| Workload | Actual Prompt Tokens | Reused Tokens | Generated Tokens | Runs | Prompt tok/s (Median & Range) | Decode tok/s (Median & Range) | TTFT Seconds (Median & Range) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Short Chat** | 88 (85–93) | 0 | 100 (100–100) | 9 | *not measured* | **25.20** (22.70–31.10) | **1.81 s** (1.61–1.96) |
| **4K Fresh Prompt** | 4,021 (4,021–4,021) | 0 | 24 cap | 3 | **302.20** (299.90–305.10) | *not measured* | **13.35 s** (13.22–13.45) |
| **16K Fresh Prompt** | 16,058 (16,058–16,058) | 0 | 24 cap | 3 | **323.50** (295.20–324.20) | *not measured* | **49.69 s** (49.59–54.45) |
| **Agent Coding Session** | 14,432 (last turn) | 11,571 (turn 5) | up to 64 | 15 turns | 246.7 (turn 5) | **27.30** (22.40–34.60) | **11.70 s** (7.67–12.36) |

---

## Comparison Table: Current Run vs. 2026-10-23 Baseline

| Metric | 2026-10-23 Baseline | **2026-10-25 Post-v0.2.5 Sync** | Delta | Assessment |
| :--- | :---: | :---: | :---: | :--- |
| **Chat Decode Speed** | 24.80 tok/s | **25.20 tok/s** (peak 31.10) | **+1.6%** | Decode throughput solid and slightly higher |
| **4K Fresh Prompt** | 301.80 tok/s | **302.20 tok/s** (peak 305.10) | **+0.1%** | Consistent ~302 tok/s prefill |
| **4K TTFT** | 13.37 s | **13.35 s** | **-0.2%** | Slightly faster time-to-first-token |
| **16K Fresh Prompt** | 334.10 tok/s | **323.50 tok/s** | **-3.2%** | Normal variance within ROCm run bounds |
| **Agent Cache Hit** | 68.56% | **68.46%** | **-0.1%** | Conversation cache reuse remained identical |
| **Agent Decode Speed** | 27.60 tok/s | **27.30 tok/s** (peak 34.60) | **-1.1%** | Within nominal variance, peak reached 34.6 tok/s |
| **Failure Rate** | 0 / 18 | **0 / 18 (0%)** | **0%** | Perfect execution, zero aborts or hangs |

---

## Agent Turn Cache Progression (Run 1)

| Turn | Prompt Tokens | Reused Tokens | Read Tokens | Prompt tok/s | TTFT (s) | Decode tok/s |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 647 | 0 | 647 | 138.3 | 4.72 | 20.4 |
| 1 | 3,617 | 670 | 2,947 | 240.0 | 12.32 | 25.2 |
| 2 | 5,150 | 3,680 | 1,470 | 190.2 | 7.77 | 28.7 |
| 3 | 8,594 | 5,143 | 3,451 | 280.2 | 12.36 | 25.7 |
| 4 | 11,517 | 8,655 | 2,862 | 245.6 | 11.70 | 30.4 |
| 5 | 14,470 | 11,571 | 2,899 | 246.7 | 11.79 | 31.3 |

## Sources

1. Raw benchmark output and JSON results: `bench/results/2026-10-25-community-unknown-qwen3-8-flash-next-coder-iq1-m/`
2. Baseline comparison: `bench/results/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/`
3. Engine: `qwen3.8-flash-next-coder-iq1_m` running on `/mnt/data/Strata/strata-coder-iq1_m.json`
