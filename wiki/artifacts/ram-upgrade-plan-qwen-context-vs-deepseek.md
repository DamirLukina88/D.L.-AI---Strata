---
title: "Workstation RAM Upgrade Plan: Qwen3.8 Context & Quantization Scaling vs. DeepSeek V4.1"
type: artifact
description: "Hardware analysis and execution plan for upgrading workstation RAM to scale Qwen3.8 Coder context window and quantization tier."
status: active
tags: [hardware, ram, upgrade, qwen38, deepseek, context, quantization, benchmark]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Workstation RAM Upgrade Plan: Qwen3.8 Context & Quantization Scaling

## Executive Summary

This plan documents the hardware upgrade pathway for the local Strata AI workstation (AMD Ryzen 5 3600, 32 GB DDR4 RAM, AMD Radeon RX 7600 XT 16 GB VRAM on CachyOS Linux).

It evaluates allocating additional physical memory (64 GB to 96 GB+) between two target outcomes:
1. **Target A (Recommended): Scaling Qwen3.8-Flash-Next Coder** from 65K context up to 262K (full native window) or 1M (YaRN), and promoting the quantization tier from `IQ1_M` (91.3% SWE-bench retained) to `IQ2_XS` (96.8%) or `IQ3_S` (99.2%).
2. **Target B: Running DeepSeek-V4.1-Flash locally** (552B MoE, 111 GB Engram table).

---

## 1. Comparison Matrix: Allocation of 64 GB - 96 GB RAM

| Metric | Current Baseline (32 GB RAM) | Upgraded RAM: Qwen3.8 Coder (`IQ2_XS` or `IQ3_S`) | Upgraded RAM: DeepSeek-V4.1-Flash (`IST-DAS-2.00bpw`) |
|---|---|---|---|
| **Active Model** | `qwen3.8-flash-next-coder-iq1_m` | `qwen3.8-flash-next-coder-iq2_xs` or `iq3_s` | `deepseek-v4.1-flash-ist-das-2.00bpw` |
| **Max Context Window** | **65,536 tokens** (pinned) | **262,144 tokens** (native full) up to **1,048,576** (YaRN) | ~16,384 – 32,768 tokens (constrained by disk bandwidth) |
| **Decode Speed** | **25.2 – 27.3 tok/s** | **18.5 – 24.0 tok/s** (smooth interactive flow) | **4.5 – 7.0 tok/s** (bound by DDR4 bus bandwidth) |
| **Prefill Speed** | **302.2 – 324 tok/s** | **250 – 290 tok/s** | **100 – 140 tok/s** |
| **SWE-Bench Retained** | 69.0% (91.3% of unquantized) | **73.2% – 75.0% (96.8% – 99.2% retained)** | 78.5% – 82.0% |
| **Disk Space Footprint** | ~28 GB | ~35 GB (`IQ2_XS`) or ~50 GB (`IQ3_S`) | **257 GB** (94% of free disk exhausted) |
| **Viability for Daily Coding** | Excellent (fast iteration) | **Optimal (Large repository context + high precision)** | Poor (high latency, agent workflows 4-5x slower) |

---

## 2. Technical Feasibility & Architectural Details

### A. Qwen3.8 Context Window Expansion
Qwen3.8-Flash-Next uses hybrid GQA (Grouped Query Attention) and GDN linear attention:
- **Current constraint:** At 32 GB RAM, base system processes + Strata resident buffers leave ~3.4 GiB free. Context is restricted to `--max-context 65536` (~0.9 GB KV buffer) to prevent Linux page cache eviction and swap thrashing.
- **With 64 GB RAM:** Unlocks native **262,144 context window** (~3.6 GB KV buffer + 5 GB prefill staging).
- **With 96 GB RAM:** Safely enables up to **524K or 1M context** using YaRN RoPE scaling (`--rope-scaling yarn`), allowing entire codebases, deep logs, and API specifications to remain active in memory without conversation compaction.

### B. Qwen3.8 Quantization Promotion (`IQ1_M` $\rightarrow$ `IQ3_S`)
- `IQ1_M` is highly optimized for constrained RAM, but occasionally drops complex typing or loops during subtle multi-file refactoring.
- With 64–96 GB RAM, Strata can load `IQ2_XS` (35 GB) or `IQ3_S` (50 GB).
- Because Qwen's MoE routes only 3.4B active parameters per token, streaming experts from DDR4 memory still sustains **18–24 tok/s** on AMD Zen 2.

### C. DeepSeek-V4.1-Flash Bottlenecks (Why 96 GB RAM is Still Constrained)
1. **Memory Bandwidth Ceiling:** DeepSeek activates 6 experts across 40 layers (240 expert evaluations per token). At 2.00 bpw, this requires reading ~1.95 GB of dynamic expert weights across the DDR4 bus **per generated token**. With dual-channel DDR4 bandwidth capped at 42–48 GB/s on AM4, decode speed hits a hard theoretical ceiling of ~5–7 tok/s.
2. **Disk Exhaustion:** The model shards + 111 GB Engram table require 257 GB. With 274 GB free on `/mnt/data`, disk utilization exceeds 94%, risking `ENOSPC` errors during agent runs.

---

## 3. Step-by-Step Execution Plan (Upon Hardware Upgrade)

When physical RAM is installed (64 GB or 96 GB):

### Step 1: Verify Hardware & Timings
1. Check Linux kernel memory recognition:
   ```bash
   free -h
   numactl --hardware
   ```
2. Verify memory speed in BIOS/dmidecode to ensure 4-DIMM configuration did not downclock below 2933/3200 MT/s.

### Step 2: Scale Context Window (Immediate Zero-Download Win)
1. In `strata-coder-iq1_m.json`:
   - Change `"--max-context": "65536"` to `"--max-context": "262144"`.
   - Update `limit.context` in client configs if applicable.
2. Restart service:
   ```bash
   sudo systemctl restart strata-server.service
   ```
3. Run prompt benchmark at 32K and 64K to verify prefill stability.

### Step 3: Upgrade to `IQ2_XS` or `IQ3_S` (Optional Higher Quality)
1. Download official GSQ pack for `coder-IQ2_XS` or `coder-IQ3_S` using setup:
   ```bash
   python setup.py --family qwen --model IQ2_XS --context 262144 --yes --no-start
   ```
2. Update systemd service / model JSON pointer to the new pack.
3. Validate memory headroom with `free -h` and ensure decode speed remains $\ge 20$ tok/s.

---

## 4. Architectural Decision Record

- **Decision:** Prioritize RAM upgrades for **Qwen3.8-Flash-Next Coder context expansion (262K native) and quantization promotion (`IQ2_XS`/`IQ3_S`)**.
- **DeepSeek Strategy:** Maintain DeepSeek-V4.1 integration via **Cloud API (`deepseek-api` skill)** for high-complexity math/science reasoning spikes, keeping local hardware dedicated to low-latency, real-time agent pair programming.

---

## Sources

- [docs/DETAILS.md](file:///home/damirl/Desktop/Strata/docs/DETAILS.md)
- [wiki/artifacts/upstream-v0-2-4-review-2026-10-24.md](file:///home/damirl/Desktop/Strata/wiki/artifacts/upstream-v0-2-4-review-2026-10-24.md)
- [strata-coder-iq1_m.json](file:///home/damirl/Desktop/Strata/strata-coder-iq1_m.json)
