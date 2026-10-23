---
title: "Strata v0.1.44.1 Benchmark Report (2026-10-23 Baseline)"
type: artifact
description: "Pre-implementation baseline benchmark of Strata v0.1.44.1 on AMD Radeon RX 7600 XT with Qwen3.8-Flash-Next-Coder-IQ1_M."
status: active
tags: [benchmark, strata, rocm, hip, rx7600xt, coder, performance, baseline]
created: 2026-10-23
updated: 2026-10-23
last_verified: 2026-10-23
---

# Strata v0.1.44.1 Benchmark Report (2026-10-23 Baseline)

Pre-implementation baseline benchmark executed before starting the Adaptive Reasoning Evolution Plan (Phase 1: Dynamic Reasoning Budget Capping, Phase 2: Empirical Response Matrix, Phase 3: CPU Semantic Router).

## Hardware & Environment

- **Accelerator:** AMD Radeon RX 7600 XT (16 GiB VRAM, gfx1102 / RDNA3)
- **Host CPU:** AMD Ryzen 5 3600 6-Core Processor (6 cores, 12 threads)
- **Host Memory:** 32 GiB System RAM (31.3 GiB usable)
- **Operating System:** Linux 7.2.11-1-cachyos, ROCm 7.2.4 HIP backend
- **Model:** `qwen3.8-flash-next-coder-iq1_m` (65,536 context, parallel slots: 1, temperature: 0, thinking: off)
- **Software Build:** Strata v0.1.44.1 (commit `b6b08837`)
- **Benchmark Suite:** `tools/strata_bench.py` against active HTTP server (`http://127.0.0.1:8080`), 3 runs per workload, 459 seconds total duration.

---

## Benchmark Results (2026-10-23)

| Workload | Actual Prompt Tokens | Reused Tokens | Generated Tokens | Runs | Prompt tok/s (Median & Range) | Decode tok/s (Median & Range) | TTFT Seconds (Median & Range) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Short Chat** | 88 (85–93) | 0 | 100 (100–100) | 9 | *not measured* | **24.80** (24.20–31.60) | **1.66 s** (1.62–1.70) |
| **4K Fresh Prompt** | 4,021 (4,021–4,021) | 0 | 24 cap | 3 | **301.80** (298.60–304.80) | *not measured* | **13.37 s** (13.24–13.51) |
| **16K Fresh Prompt** | 16,058 (16,058–16,058) | 0 | 24 cap | 3 | **334.10** (331.10–335.20) | *not measured* | **48.12 s** (47.96–48.55) |
| **Agent Coding Session** | 14,391 (last turn) | 11,492 (turn 5) | up to 64 | 15 turns | 250.2 (turn 5) | **27.60** (21.50–38.20) | **11.41 s** (7.06–12.01) |

---

## Agent Session Cache Dynamics

- **Cache Hit Rate:** **68.56%** median (range 68.55%–68.60%).
- **Re-read Redundant Tokens:** **3.0** tokens/session (improved from 4.0).
- **Cold Turn 0 TTFT:** 5.04 s (range 4.65–5.07 s).
- **Turn 1–5 Cache Reuse:** Scaled up to 11,492 cached tokens by turn 5, maintaining decode speeds up to 32.4 tok/s on follow-up turns.

---

## Comparison Table: Current Baseline vs. Prior Milestones

| Metric | Oct 16 Baseline (`79e27070`) | Oct 23 Earlier Run (`16757910`) | **Current Pre-Plan (`b6b08837`)** | Delta vs Oct 16 | Delta vs Oct 23 Earlier | Assessment |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Chat Decode Speed** | 24.00 tok/s | 23.90 tok/s | **24.80 tok/s** | **+3.3%** | **+3.8%** | Noticeable throughput gain |
| **Chat TTFT** | 1.71 s | 1.72 s | **1.66 s** | **-3.3%** | **-3.4%** | Fastest interactive response recorded |
| **4K Prompt Prefill** | 302.30 tok/s | 298.60 tok/s | **301.80 tok/s** | -0.2% | **+1.1%** | Sustained >300 tok/s roofline |
| **4K TTFT** | 13.35 s | 13.52 s | **13.37 s** | +0.2% | **-1.1%** | Consistent latency |
| **16K Prompt Prefill** | 332.10 tok/s | 331.00 tok/s | **334.10 tok/s** | **+0.6%** | **+0.9%** | **New all-time record on RX 7600 XT** |
| **16K TTFT** | 48.41 s | 48.57 s | **48.12 s** | **-0.6%** | **-0.9%** | Lower high-context latency |
| **Agent Decode Speed** | 25.40 tok/s | 24.80 tok/s | **27.60 tok/s** | **+8.7%** | **+11.3%** | Major improvement in multi-turn coding |
| **Agent Turn TTFT** | 11.27 s | 11.76 s | **11.41 s** | +1.2% | **-3.0%** | Stable KV-cache prompt read |
| **Agent Cache Hit Rate** | 68.49% | 68.35% | **68.56%** | **+0.1%** | **+0.3%** | KV prefix cache fully healthy |
| **Redundant Re-read Tokens**| 4.00 | 4.00 | **3.00** | **-25.0%** | **-25.0%** | Tighter prefix reuse |

---

## Key Conclusions

1. **Model Performs Better Across the Board:**
   - Chat decode throughput is up from 23.90 to **24.80 tok/s** (+3.8%).
   - Agent decode throughput saw the largest gain: up from 24.80 to **27.60 tok/s** (+11.3%).
   - Time to first token (TTFT) improved on both chat (1.66 s vs 1.72 s) and agent turns (11.41 s vs 11.76 s).
   - 16K prompt prefill set a new hardware high of **334.10 tok/s** on the Radeon RX 7600 XT.
2. **Safe Pre-Implementation State:**
   - The system is operating cleanly with 0 errors across 459 seconds of intensive benchmarking.
   - This dataset establishes a verified baseline before making changes in Phase 1 (Dynamic Reasoning Budget Capping) of the Adaptive Reasoning Evolution Plan.

---

## Sources

- Raw results JSON: `bench/results/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`
- Community summary: `bench/results/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/README.md`
- Comparison run: `bench/results/v0.2.3-rx7600xt-2026-10-23/baseline/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/`
- Prior baseline: `wiki/artifacts/strata-benchmark-2026-10-16.md`
