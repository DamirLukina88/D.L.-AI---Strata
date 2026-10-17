---
title: "Strata v0.1.43 Performance Switches and Memory Hygiene"
type: decision
description: "Activation of adaptive tier memory overlap, resident RAM soft-commit, and Linux page cache release on exit"
status: active
tags: [strata, rocm, hip, performance, memory, optimization]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Strata v0.1.43 Performance Switches and Memory Hygiene

## Context
Upstream Strata v0.1.43 introduced several opt-in runtime flags for MoE memory swapping and system hygiene. On AMD ROCm HIP setups (RX 7600 XT gfx1102 on CachyOS), HIP defaults to synchronous swapping unless explicitly opted into asynchronous overlap.

## Decisions

1. **`STRATA_ADAPT_OVERLAP=1` & `STRATA_ADAPT_OVERLAP_RESIDENT=1`:**
   - **Mechanism:** Overlaps GPU copies of the adaptive MoE tier so they land layer-by-layer while the next decode window runs, rather than blocking the entire window.
   - **Resident RAM Mode:** `STRATA_ADAPT_OVERLAP_RESIDENT=1` enables soft-commit of exchanges between system RAM and VRAM.
   - **Correctness:** Bitwise exact (generates identical token sequences).
   - **Configuration:** Set in `strata-coder-iq1_m.json` `"env"` block.

2. **`STRATA_DROP_CACHE_ON_EXIT=1`:**
   - **Mechanism:** On server shutdown or model idle unload, `serve/cache_drop.py` calls `posix_fadvise(POSIX_FADV_DONTNEED)` across all model shard files to release the ~20+ GB of model weights from the Linux page cache.
   - **Configuration:** Set in `strata-coder-iq1_m.json` `"env"` and exported in `strata-server.service`.

3. **`STRATA_NAN_GUARD` & `logit_bias` Support:**
   - `STRATA_NAN_GUARD` is active by default in C++ verify graphs (<0.01% overhead).
   - `serve/logit_bias.py` is verified via HTTP API probe to support token biasing without regression.

4. **MoE Expert Profile Tuning (`expert-profile-custom.bin`):**
   - Synthesized from 12 real coding traces using `tools/make_profile_mix.py --n-expert 256` matching `qwen3.8-flash-next-coder-iq1_m` architecture (12,288 pairs).
   - Preloads high-probability coding experts into VRAM during engine boot in 2.7s.

5. **AMD RDNA3 Hardware Acceleration & SMT Isolation (`STRATA_AUX_CPUS=auto`):**
   - **Kernel Fusions & Streams:** `STRATA_SH_STREAM=1` (independent stream for shared expert), `STRATA_LFUSE=1`, `STRATA_TSUM=1`, `STRATA_QFUSE=1`, `STRATA_PLE_BATCH=1`, `STRATA_GDN_HEAD=1`, `STRATA_GDN_PP=2`.
   - **Linux CPU Core Isolation:** `STRATA_AUX_CPUS=auto` moves helper and HIP driver threads to SMT siblings, eliminating host core preemption.
   - **Impact:** Record 16K prefill throughput (**291.70 tok/s**), record long-context TTFT (**55.11 s**), and sub-1.7s chat latency (**1.69 s**).

## Sources
- Upstream Strata v0.1.43 commits (`0d761d99`, `8c80a3ba`, `003ea8c6`, `248dbee5`)
- `docs/DETAILS.md` and `serve/cache_drop.py`
- [Strata v0.1.43 Optimization and Benchmarking Matrix](../artifacts/v0-1-43-optimization-benchmark-report.md)
