---
title: "Strata v0.1.43 Optimization and Benchmarking Plan"
type: artifact
description: "Implementation and execution plan for activating runtime optimization switches, benchmarking speedup arms, and tracing MoE expert profiles"
status: active
tags: [strata, rocm, hip, optimization, benchmark, plan]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Strata v0.1.43 Optimization and Benchmarking Plan

## Goal Description
Integrate, activate, and empirically benchmark performance-enhancing switches from upstream Strata `v0.1.43` on the AMD Radeon RX 7600 XT (16 GB VRAM, gfx1102) with 32 GB Resident RAM running under CachyOS Linux:
1. **Activate Low-Overhead Swapping & Memory Cleanliness:** Enable `STRATA_ADAPT_OVERLAP=1`, `STRATA_ADAPT_OVERLAP_RESIDENT=1`, and `STRATA_DROP_CACHE_ON_EXIT=1`.
2. **Benchmark Empirical Speedup Flags:** Systematically measure `STRATA_ROUTE_TAIL_SKIP=7` and `STRATA_ROUTE_RESIDENT` margins (e.g., `0.5`, `1.0`) using the official benchmark suite (`tools/strata_bench.py` and `bench.sh`).
3. **MoE Expert Profile Tracing & Refinement:** Set up a pipeline with `tools/collect_profile_traces.py` and `tools/make_profile_mix.py` to collect routing distributions over time, generating an optimized `.bin` profile to maximize VRAM cache hit rates for coding and agent workloads.
4. **API Verification:** Validate request-scoped steerability via `serve/logit_bias.py`.

---

## Execution Decisions

1. **`STRATA_ROUTE_RESIDENT` Margin Values:**
   - **Approved:** Sweep both `margin=0.5` (conservative) and `margin=1.0` (upstream standard) against the baseline to measure tok/s speedup vs output quality.
2. **MoE Expert Trace Corpus (`collect_profile_traces.py`):**
   - **Approved:** Execute a curated 12-prompt coding & reasoning subset (~8–10 min) tailored to `qwen3.8-flash-next-coder-iq1_m` to extract routing traces and generate `data/expert-profile-custom.bin`.

---

## Proposed Changes

```
┌────────────────────────────────────────────────────────────────────────┐
│                   D.L. AI — Strata Optimization Flow                   │
│                                                                        │
│   [ strata-coder-iq1_m.json ] & [ strata-server.service ]             │
│      ├── STRATA_ADAPT_OVERLAP=1                                        │
│      ├── STRATA_ADAPT_OVERLAP_RESIDENT=1                              │
│      └── STRATA_DROP_CACHE_ON_EXIT=1                                   │
│                           │                                            │
│                           ▼                                            │
│   [ Phase 1: Benchmark Matrix (tools/strata_bench.py) ]                │
│      ├── Arm A: Baseline (Existing config)                             │
│      ├── Arm B: + Adaptive Overlap                                     │
│      ├── Arm C: + Adaptive Overlap + Tail Skip 7                       │
│      └── Arm D: + Adaptive Overlap + Tail Skip 7 + Route Resident 1.0  │
│                           │                                            │
│                           ▼                                            │
│   [ Phase 2: MoE Expert Trace & Mixing Pipeline ]                      │
│      ├── tools/collect_profile_traces.py (routing traces)              │
│      └── tools/make_profile_mix.py -> expert-profile-tuned.bin         │
│                           │                                            │
│                           ▼                                            │
│   [ Phase 3: Logit Bias & Local Wiki Report Generation ]               │
│      ├── Validate serve/logit_bias.py via HTTP probe                   │
│      └── Commit benchmark numbers to wiki/artifacts/ & wiki/decisions/ │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Component 1: Runtime Configuration & Systemd Environment

#### [strata-coder-iq1_m.json](file:///mnt/data/Strata/strata-coder-iq1_m.json)
Added the confirmed performance and memory reclamation flags to the engine's `"env"` block:

```json
   "env": {
    "STRATA_RESIDENT_PIN": "0",
    "STRATA_PREFILL_MMQ": "1",
    "STRATA_PREFILL_RING": "96",
    "STRATA_IO_THREADS": "32",
    "STRATA_PREFILL_CPU_SHARE": "auto",
    "STRATA_ADAPT_OVERLAP": "1",
    "STRATA_ADAPT_OVERLAP_RESIDENT": "1",
    "STRATA_DROP_CACHE_ON_EXIT": "1"
   }
```

#### [strata-server.service](file:///home/damirl/.config/systemd/user/strata-server.service)
Exported `STRATA_DROP_CACHE_ON_EXIT=1` in the systemd service environment so the Python server drops the page cache on service stops/restarts:

```ini
  Environment=STRATA_API_KEY=<STRATA_API_KEY>
  Environment=STRATA_WORKSPACE_DIR=/mnt/data/DL-AI-workspace
  Environment=STRATA_DROP_CACHE_ON_EXIT=1
```

---

### Component 2: Empirical Benchmark Matrix (`tools/strata_bench.py`)

1. **Arm A (Baseline):** Standard configuration.
2. **Arm B (Adaptive Overlap):** `STRATA_ADAPT_OVERLAP=1`, `STRATA_ADAPT_OVERLAP_RESIDENT=1`.
3. **Arm C (Overlap + Tail Skip):** Arm B + `STRATA_ROUTE_TAIL_SKIP=7`.
4. **Arm D1 (Overlap + Tail Skip + Route Resident 0.5):** Arm C + `STRATA_ROUTE_RESIDENT=0.5`.
5. **Arm D2 (Overlap + Tail Skip + Route Resident 1.0):** Arm C + `STRATA_ROUTE_RESIDENT=1.0`.

Each arm recorded:
- Decode generation throughput (tokens/sec).
- Time to First Token (TTFT) in seconds.
- 4K and 16K prefill processing speed (tokens/sec).
- 5-turn agent prompt cache hit rate and re-read latency.

---

### Component 3: Expert Profile Collection & Custom Tuning

1. Executed `tools/collect_profile_traces.py` with `--mode routing` on curated coding prompts 0–11 into `bench/traces/coder_12/`.
2. Mixed the collected traces using `tools/make_profile_mix.py` to produce `data/expert-profile-custom.bin`.

---

## Related
- Walkthrough: [Strata v0.1.43 Integration and Optimization Walkthrough](strata-v0-1-43-integration-and-optimization-walkthrough.md)
- Benchmark Matrix: [Strata v0.1.43 Optimization and Benchmarking Matrix](v0-1-43-optimization-benchmark-report.md)
- Decision: [Strata v0.1.43 Performance Switches and Memory Hygiene](../decisions/strata-v0-1-43-performance-and-memory-optimizations.md)

## Sources
- Session planning and execution, 2026-10-11
- Upstream Strata `v0.1.43` documentation and tools
