# [Benchmark] AMD Radeon RX 7600 XT 16 GB (gfx1102), CachyOS Linux, Ryzen 5 3600

## Problem and result
Upstream lacks baseline community benchmark measurements for mid-range AMD RDNA3 desktop GPUs (`gfx1102`, 16 GB VRAM) running on Linux with ROCm 7.2.4 under 32 GB system RAM constraints with 256 resident MoE experts.

This results-only PR adds a 4-leg interleaved A/B benchmark report and all four raw `results*.json` files for `Qwen3.8-Flash-Next-Coder-IQ1_M` at 65,536-token context on an AMD Radeon RX 7600 XT 16 GB (`gfx1102`, Ryzen 5 3600, 32 GB DDR4, CachyOS Linux, systemd `MemorySwapMax=0`):
- **4K prompt prefill:** 305.8 tok/s (298.3-307.0) and 306.8 tok/s (300.2-307.8) across candidate legs (13.19 s and 13.15 s TTFT).
- **16K prompt prefill:** 334.6 tok/s (334.5-335.3) and 331.7 tok/s (326.4-333.7).
- **Short chat decode:** 24.4 tok/s (21.6-35.6) and 23.9 tok/s (20.6-34.1), 1.59 s and 1.65 s TTFT.
- **Multi-turn agent session:** 28.0 tok/s decode, 67.2% conversation cache hit rate, 5 re-read tokens per session.
- **Engine swap:** 0 B across all 4 legs under `MemorySwapMax=0`.

## Related discussion
None (results-only submission following `docs/COMMUNITY_BENCHMARKS.md` and `CONTRIBUTING.md`).

## Approach
- Added `bench/results/2026-11-07-community-rx-7600-xt-v0-2-12/README.md` with full hardware, ROCm 7.2.4 driver, model, CLI launch flags, `STRATA_*` environment variables, provenance notes (locally built `0.1.44.1` fork base `37f6ceea` with cherry-picked `v0.2.12` `#5108` MMQ row margin and `#5096` Flag-B ordering guards), and per-leg medians with min-max ranges.
- Included all 4 raw per-request JSON files (`results.json`, `results-leg1-base.json`, `results-leg3-base.json`, `results-leg4-cand.json`).
- Added an index entry in `docs/COMMUNITY_BENCHMARKS.md` under `## Community reports`.
- Zero engine, server, or script changes.

## Validation
**Passed:**
- `python tools/strata_bench.py` executed across 4 alternating legs (Base 1 -> Candidate 1 -> Base 2 -> Candidate 2, 3 runs per test per leg) on Linux 7.3.1-1-cachyos (`gfx1102`, ROCm 7.2.4), 0 failed requests.
- Verified 0 B engine swap (`VmSwap: 0 kB` in `/proc/<pid>/status`) under `MemorySwapMax=0`.
- Verified native unit tests on the tested binary: `./build-hip/mmq_ids_margin_test`, `./build-hip/adaptive_range_test`, and `./build-hip/native_expert_parity --synthetic IQ1_M/Q8_0` (0 failures).

**Failed:**
none observed.

**Not run:**
- Needle recall or coding quality suite (speed-only suite run via `tools/strata_bench.py`).
- Prompts above 16K tokens (configured context is 65,536 tokens on 32 GB RAM).
- Unmodified upstream `v0.2.12` release binary comparison (measured on our local fork build `37f6ceea` with `STRATA_HIP_WMMA=1` and experimental speed projection `cvec: project:4-44` enabled, documented in `README.md`).

## Limits
Single desktop workstation in normal use without GPU clock or power telemetry; speed-only benchmark on a modified local fork build.
