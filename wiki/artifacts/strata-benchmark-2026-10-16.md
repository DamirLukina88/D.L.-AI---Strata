---
title: "Strata v0.1.44.1 Benchmark Report (2026-10-16)"
type: artifact
description: "Empirical benchmark evaluation of Strata v0.1.44.1 with Qwen3.8-Flash-Next-Coder-IQ1_M on AMD Radeon RX 7600 XT (ROCm 7.2.4 HIP)"
status: active
tags: [benchmark, strata, rocm, hip, rx7600xt, coder, performance]
created: 2026-10-16
updated: 2026-10-16
last_verified: 2026-10-16
---

# Strata v0.1.44.1 Benchmark Report (2026-10-16)

## Hardware & Environment

- **Accelerator:** AMD Radeon RX 7600 XT (16 GiB VRAM, gfx1102 / RDNA3)
- **Host CPU:** AMD Ryzen 5 3600 6-Core Processor (6 cores, 12 threads)
- **Host Memory:** 32 GiB System RAM (31.3 GiB usable)
- **Operating System:** CachyOS Linux (Kernel 7.2.9-2-cachyos), ROCm 7.2.4 HIP backend
- **Model:** `qwen3.8-flash-next-coder-iq1_m` (65,536 context, parallel slots: 1, temperature: 0, thinking: off)
- **Software Build:** Strata v0.1.44.1 (commit `79e27070`)
- **Benchmark Tool:** `tools/strata_bench.py` (3 repeats per test across short chat, 4K prompt, 16K prompt, and 5-turn agent session; total duration 460.2 s)

---

## Benchmark Results (2026-10-16)

| Workload | Actual Prompt Tokens | Reused Tokens | Generated Tokens | Runs | Prompt tok/s (Median & Range) | Decode tok/s (Median & Range) | TTFT Seconds (Median & Range) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Short Chat** | 88 (85–93) | 0 | 100 (100–100) | 9 | *not measured* | **24.0** (22.9–28.1) | **1.71 s** (1.66–1.77) |
| **4K Fresh Prompt** | 4,021 (4,021–4,021) | 0 | 24 cap | 3 | **302.3** (297.3–303.0) | *not measured* | **13.35 s** (13.31–13.57) |
| **16K Fresh Prompt** | 16,058 (16,058–16,058) | 0 | 24 cap | 3 | **332.1** (331.6–333.0) | *not measured* | **48.41 s** (48.28–48.48) |
| **Agent Coding Session** | 14,237 (last turn) | 11,338 (turn 5) | up to 64 | 3 | 248.7 (turn 5) | **25.4** (14.7–31.8) | **11.27 s** (6.94–12.12) |

---

## Turn-by-Turn Agent Session Breakdown (Run 1)

| Turn | Prompt Tokens | Reused (Cached) | Read Fresh | Prompt tok/s | First Token (TTFT) | Decode tok/s | Cache Hit % |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Turn 0** | 647 | 0 | 647 | 143.7 | 4.542 s | 20.5 | 0.0% |
| **Turn 1** | 3,444 | 702 | 2,742 | 244.3 | 11.274 s | 25.2 | 20.4% |
| **Turn 2** | 4,977 | 3,508 | 1,469 | 198.2 | 7.457 s | 25.4 | 70.5% |
| **Turn 3** | 8,421 | 5,041 | 3,380 | 282.3 | 12.025 s | 24.8 | 59.9% |
| **Turn 4** | 11,336 | 8,474 | 2,862 | 237.2 | 12.120 s | 17.4 | 74.8% |
| **Turn 5** | 14,237 | 11,338 | 2,899 | 248.7 | 11.709 s | 14.7 | **79.6%** |

- **Follow-up Turns Cache Hit Median:** 68.5% (range: 68.1%–68.5%).
- **Cold Turn 0 TTFT Median:** 4.67 s (range: 4.54–4.71 s).

---

## Comparison: Baseline (2026-10-15) vs Current (2026-10-16)

| Metric | Baseline (2026-10-15) | Current (2026-10-16) | Delta | Assessment |
| :--- | :---: | :---: | :---: | :--- |
| **Chat Decode Speed** | 23.90 tok/s | **24.00 tok/s** | +0.4% | Stable throughput |
| **Chat TTFT** | 1.89 s | **1.71 s** | **-9.5%** | Faster interactive response |
| **4K Prompt Prefill** | 295.20 tok/s | **302.30 tok/s** | **+2.4%** | Consistent improvement |
| **4K TTFT** | 13.67 s | **13.35 s** | **-2.3%** | Lower initial latency |
| **16K Prompt Prefill** | 331.10 tok/s | **332.10 tok/s** | **+0.3%** | Peak record on RX 7600 XT |
| **16K TTFT** | 48.55 s | **48.41 s** | **-0.3%** | Fast long-context response |
| **Agent Decode Speed** | 26.80 tok/s | **25.40 tok/s** | -5.2% | Within normal variance (ranges overlap) |
| **Agent Turn TTFT** | 11.50 s | **11.27 s** | **-2.0%** | Faster follow-up turns |
| **Agent Cache Hit Rate** | 68.80% | **68.49%** | -0.3% | KV prefix cache fully functional |

---

## Key Observations

1. **Prompt Ingestion Records:** 16K prompt ingestion reached **332.1 tok/s**, confirming that HIP kernel optimizations and memory tiering maintain steady maximum performance on RDNA3 hardware.
2. **Interactive Latency Reductions:** Chat time to first token dropped below 1.75s to **1.71s** median (-9.5% compared to 1.89s baseline).
3. **KV Prefix Caching Stability:** The agent session successfully re-used 11,338 tokens on turn 5 (79.6% cache hit rate), keeping turn latency at ~11.7s despite 14K total context.
4. **Reliability:** 0 errors, 0 timeout retries, 0 memory leaks across the 460-second test suite.

---

## Sources

- Raw results: `bench/results/2026-10-16-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`
- Community summary: `bench/results/2026-10-16-community-unknown-qwen3-8-flash-next-coder-iq1-m/README.md`
- Baseline report: `wiki/artifacts/v0-1-43-optimization-benchmark-report.md`
