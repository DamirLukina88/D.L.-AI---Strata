---
title: "Strata Performance Benchmark Report (2026-11-01 Two-Tier Handoff & 64K Context)"
type: artifact
description: "Performance benchmark of Strata Qwen3.8-Flash-Next-Coder-IQ1_M on AMD RX 7600 XT with Two-Tier Wiki Handoff on the 64K context window"
status: active
tags: [benchmark, strata, rocm, hip, rx7600xt, coder, performance, handoff]
created: 2026-11-01
updated: 2026-11-01
last_verified: 2026-11-01
---

# Strata Performance Benchmark Report (2026-11-01 Two-Tier Handoff & 64K Context)

Official benchmark executed with `tools/strata_bench.py --long` following the deployment of Two-Tier Wiki Handoff, opt-in GDN chunked kernels, and the 64K full context window configuration.

## Hardware & Environment

- **Accelerator:** AMD Radeon RX 7600 XT (16 GiB VRAM, gfx1102 / RDNA3)
- **Host CPU:** AMD Ryzen 5 3600 6-Core Processor (6 cores, 12 threads)
- **Host Memory:** 32 GiB System RAM (31.3 GiB usable)
- **Operating System:** Linux 7.3.1-1-cachyos, ROCm 7.3 HIP backend
- **Model:** `qwen3.8-flash-next-coder-iq1_m` (65,536 context, parallel slots: 1, temperature: 0, thinking: off)
- **Software Build:** Strata v0.1.44.1 with Two-Tier Wiki Handoff and opt-in GDN chunked kernels (commit `5b8ba884`)
- **Benchmark Suite:** `tools/strata_bench.py --long` against active HTTP server (`http://127.0.0.1:8080`), 3 runs per workload, 742 seconds total duration.

---

## Benchmark Results Summary

| Workload | Actual Prompt Tokens | Reused Tokens | Generated Tokens | Runs | Prompt tok/s (Median & Range) | Decode tok/s (Median & Range) | TTFT Seconds (Median & Range) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Short Chat** | 88 (85–93) | 0 | 100 (100–100) | 9 | *not measured* | **24.70** (23.50–35.30) | **1.54 s** (1.47–1.57) |
| **4K Fresh Prompt** | 4,021 (4,021–4,021) | 0 | 24 cap | 3 | **308.00** (299.80–308.70) | *not measured* | **13.10 s** (13.07–13.46) |
| **16K Fresh Prompt** | 16,058 (16,058–16,058) | 0 | 24 cap | 3 | **337.00** (336.90–337.40) | *not measured* | **47.70 s** (47.64–47.71) |
| **32K Fresh Prompt** | 32,050 (32,050–32,050) | 0 | 24 cap | 3 | **334.70** (334.50–334.80) | *not measured* | **95.82 s** (95.78–95.89) |
| **Agent Coding Session** | 14,411 (last turn) | 11,521 (turn 5) | up to 64 | 15 turns | 252.4 (turn 5) | **27.50** (25.00–35.40) | **11.16 s** (6.93–11.89) |

---

## Comparison Table: Current Run vs. 2026-10-29 Baseline

| Metric | 2026-10-29 Baseline | **2026-11-01 Run** | Delta | Assessment |
| :--- | :---: | :---: | :---: | :--- |
| **Chat Decode Speed** | 26.00 tok/s | **24.70 tok/s** (peak 35.30) | **-5.0%** | Stable generation throughput across all 3 prompts |
| **Chat First Token (TTFT)** | 1.71 s | **1.54 s** | **-10.1%** | 10.1% faster initial token delivery |
| **4K Fresh Prompt** | 304.80 tok/s | **308.00 tok/s** | **+1.0%** | Higher prefill throughput on short inputs |
| **4K TTFT** | 13.23 s | **13.10 s** | **-1.1%** | TTFT improved to 13.10 s |
| **16K Fresh Prompt** | 335.40 tok/s | **337.00 tok/s** | **+0.5%** | Consistent ~337 tok/s prefill speed |
| **16K TTFT** | 47.92 s | **47.70 s** | **-0.5%** | Faster time-to-first-token |
| **32K Fresh Prompt** | 334.10 tok/s | **334.70 tok/s** | **+0.2%** | High throughput sustained at 32K context |
| **32K TTFT** | 96.00 s | **95.82 s** | **-0.2%** | Stable at 95.82 s |
| **Agent Cache Hit %** | 68.67% | **68.52%** | **-0.2%** | Prefix conversation cache reuses identical prefixes |
| **Agent Re-read Tokens/Session** | 72.00 | **4.00** | **-94.4%** | Dramatic reduction in re-read tokens across sequential turns |
| **Agent Turn TTFT** | 11.48 s | **11.16 s** | **-2.8%** | Multi-turn latency improved |
| **Agent Decode Speed** | 27.50 tok/s | **27.50 tok/s** (peak 35.40) | **0.0%** | Identical median decode rate |

---

## Agent Turn Cache Progression (Run 1)

| Turn | Prompt Tokens | Reused Tokens | Read Tokens | Prompt tok/s | TTFT (s) | Decode tok/s |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 647 | 0 | 647 | 151.7 | 4.30 | 22.6 |
| 1 | 3,554 | 670 | 2,884 | 247.1 | 11.71 | 26.6 |
| 2 | 5,119 | 3,547 | 1,572 | 208.6 | 7.58 | 26.3 |
| 3 | 8,563 | 5,183 | 3,380 | 285.3 | 11.89 | 29.4 |
| 4 | 11,469 | 8,607 | 2,862 | 248.2 | 11.58 | 29.4 |
| 5 | 14,420 | 11,521 | 2,899 | 252.4 | 11.53 | 33.8 |

## Related

- [Wiki Index](../index.md)
- [Two-Tier Wiki Handoff and OOM Fixes](../decisions/wiki-handoff-and-oom-fixes.md)
- [Strata v0.1.44.1 Benchmark Report (2026-10-23 Baseline)](strata-benchmark-2026-10-23-baseline.md)

## Sources

1. Raw benchmark output and JSON results: `bench/results/2026-11-01-community-unknown-qwen3-8-flash-next-coder-iq1-m/`
2. Baseline comparison: `bench/results/b450-baseline-2026-10-29/2026-10-29-community-unknown-qwen3-8-flash-next-coder-iq1-m/`
3. Engine: `qwen3.8-flash-next-coder-iq1_m` running on `http://127.0.0.1:8080` via `strata-server.service`.
