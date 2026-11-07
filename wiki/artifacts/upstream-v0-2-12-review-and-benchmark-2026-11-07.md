---
title: "Upstream Strata v0.2.12 Review and A/B Benchmark (2026-11-07)"
type: artifact
description: "Audit of upstream Strata v0.2.12, C++/HIP engine guards (MMQ row margin and Flag-B ordering), and 4-leg A/B benchmark on RX 7600 XT"
status: active
tags: [upstream, review, benchmark, v0.2.12, hip, rx7600xt, qwen-coder]
created: 2026-11-07
updated: 2026-11-07
last_verified: 2026-11-07
---

# Upstream Strata v0.2.12 Review and A/B Benchmark (2026-11-07)

## Summary

On 2026-11-07, upstream Strata released tag `v0.2.12`. We audited the release against Ray's host profile (AMD Ryzen 5 3600, 32 GB RAM, AMD Radeon RX 7600 XT 16 GB VRAM `gfx1102`, CachyOS Linux with ROCm 7.2.4 HIP) and Ray's architecture constraints:
- Serving **Qwen3.8-Flash-Next-Coder-IQ1_M** (256 resident experts in RAM, MTP `--spec 4`, int8 KV cache, 64K context).
- Strict non-swap policy (`MemorySwapMax=0`).
- Local-only persona preservation (PipeWire TTS/STT, system prompt, Android companion bridge).

We performed an audit, implementation plan, selective port, C++/HIP rebuild (`0.1.44.1+0.2.12-fixes`), unit test validation (70/70 passing), and a full 4-leg interleaved A/B benchmark (Base -> Cand -> Base -> Cand).

---

## What Was Adopted vs. Excluded

### 1. Excluded (Violates Constraints or Inapplicable)
- **Unsloth Dynamic Sets (UD-IQ1_M .. UD-IQ4_XS):** Require $\ge 48$ GB RAM. Running on 32 GB RAM would cause heavy zram pressure or OOM stalls, violating our [deployment decision](../decisions/rx-7600-xt-cachyos-deployment.md).
- **Multi-Card Prefill Splits & DFlash2 Multi-Card Drafter:** Designed for 2–4 GPU topologies; Ray uses a single RX 7600 XT with MTP speculative decoding (`--spec 4`).
- **Intel Arc (SYCL) & Apple Metal Kernels:** Hardware architecture is AMD RDNA3 (`gfx1102`).
- **Context Expansion past 65,536:** Prior measurements showed context $>64$K exceeds safe RAM budgets and causes lendable slot thrashing.

### 2. Adopted & Implemented
- **Python `serve/frontend.py` & `serve/server.py`:**
  - *Parser Lookback Bound (`#5409`):* Restricted prefix and misspelt opener scans to a 256-character tail lookback (`_PREFIX_LOOKBACK`), preventing quadratic token re-scanning on long files.
  - *MCP Member Suffix Resolution (`#5281`):* Unambiguous resolution of flattened tools like `mcp__playwright__browser_navigate` and bare member names (`browser_navigate`).
  - *Programmatic Tool Calling Prefixes (`#4751`):* Normalization of `tools.<name>`, `functions.<name>`, and `default_api.<name>`.
  - *Anthropic Tool Pairing by ID (`#5096`):* Restored original call sequence when parallel tool outputs arrive out of sequence from Claude Code.
  - *Undeclared Tool Calls Setting (`#3075`):* Maintained `"text"` mode to prevent undeclared tool hallucinations from issuing invalid client tool calls.
  - *Admission Accounting:* Corrected timing accounting across multi-leg segmented requests.
- **C++/HIP Engine Correctness (`src/`, `include/`):**
  - *MMQ Row Table Margin Guard (`#5108`):* Integrated `include/strata/prefill/mmq_ids_margin.hpp` (`mmq_ids_table_rows()`) in `src/prefill/moe_mmq.cu` and `src/prefill/prefill.cpp`. Prevents Xid 31 PDE faults caused by llama.cpp MMQ fixup over-reading up to $J$ rows past the table boundary.
  - *Adaptive PCIe Overlap Flag-B Ordering (`#5096`):* Integrated `include/strata/core/flag_order.hpp` (`raise_flag_b_ordered()`) across `src/core/verify.cpp` (`publish_plan`, `run_slot_rows`, `batch_serve`, `service`, `fetch_dma`). Empty plans now strictly wait behind in-flight DMA copies on the copy stream.
  - *Adaptive Range Logic (`#4844`):* Integrated `include/strata/program/adaptive_range.hpp`.

---

## Verification & Unit Testing

1. **Serve Unit Test Suites:**
   Executed 8 comprehensive test suites:
   - `serve.test_tool_corpus`
   - `serve.test_param_end_options`
   - `serve.test_web_start_question`
   - `serve.test_serve_robustness`
   - `serve.test_anthropic_tool_results`
   - `serve.test_tool_name_mcp_member`
   - `serve.test_tool_name_prefix`
   - `serve.test_tool_opener_misspelt`
   **Result:** 70/70 tests passed cleanly in 11.9 s.

2. **Native C++ Engine Tests:**
   - `./build-hip/mmq_ids_margin_test`: `ok`
   - `./build-hip/adaptive_range_test`: `ok`
   - `./build-hip/native_expert_parity --synthetic IQ1_M/Q8_0`: `0 failures`, bitwise equal.

---

## 4-Leg Interleaved A/B Benchmark Results

Executed on 2026-11-07 under `systemd-run --user --wait --pipe --working-directory=. -p MemorySwapMax=0` with `tools/strata_bench.py` against production model `qwen3.8-flash-next-coder-iq1_m`.

### Leg-by-Leg Measurements

| Metric | Leg 1 (Base 1) | Leg 2 (Cand 1) | Leg 3 (Base 2) | Leg 4 (Cand 2) |
| :--- | :--- | :--- | :--- | :--- |
| **Engine Binary** | `strata.bak-20261107` | `build-hip/strata` | `strata.bak-20261107` | `build-hip/strata` |
| **Chat Decode (tok/s)** | 26.30 | 24.40 | 25.00 | 23.90 |
| **Chat TTFT (s)** | 1.56 | 1.59 | 1.66 | 1.65 |
| **4K Prompt (tok/s)** | 307.00 | 305.80 | 303.00 | 306.80 |
| **4K TTFT (s)** | 13.14 | 13.19 | 13.31 | 13.15 |
| **16K Prompt (tok/s)** | 333.30 | 334.60 | 334.70 | 331.70 |
| **16K TTFT (s)** | 48.22 | 48.04 | 48.02 | 48.47 |
| **Agent Cache Hit %** | 67.12% | 67.18% | 67.03% | 67.23% |
| **Agent Turn TTFT (s)** | 11.32 | 11.58 | 11.49 | 11.74 |
| **Agent Decode (tok/s)** | 28.80 | 28.00 | 27.60 | 28.00 |
| **Peak RAM (MB)** | 52.9 | 53.6 | 53.4 | 55.0 |
| **Swap Usage (B)** | 0 B | 0 B | 0 B | 0 B |

### Paired Median Comparison

| Metric | Base Median (Leg 1 & 3) | Candidate Median (Leg 2 & 4) | Delta | Verification Assessment |
| :--- | :--- | :--- | :--- | :--- |
| **Chat Decode** | 25.65 tok/s | 24.15 tok/s | -5.8% | Within expected CPU/thermal jitter |
| **Chat TTFT** | 1.61 s | 1.62 s | +0.5% | Identical latency |
| **4K Prompt** | 305.00 tok/s | 306.30 tok/s | **+0.4%** | Faster prefill |
| **4K TTFT** | 13.23 s | 13.17 s | **-0.4%** | Faster time to first token |
| **16K Prompt** | 334.00 tok/s | 333.15 tok/s | -0.2% | Consistent high throughput |
| **16K TTFT** | 48.12 s | 48.26 s | +0.3% | Stable prompt latency |
| **Agent Cache Hit %** | 67.07% | 67.21% | **+0.2%** | Cache parity fully preserved |
| **Agent Turn TTFT** | 11.41 s | 11.66 s | +2.2% | Flat response latency |
| **Agent Decode** | 28.20 tok/s | 28.00 tok/s | -0.7% | Stable multi-turn speed |
| **Swap Usage** | 0 B | 0 B | 0 B | **Zero swap thrashing enforced** |

---

## Production Deployment Status

- **Engine Binary:** Deployed to `engine/strata` (checksum matches `build-hip/strata`).
- **Build Metadata:** Version updated to `"0.1.44.1+0.2.12-fixes"` in `engine/BUILD.json`.
- **Service Status:** Active under `systemd --user` with `/health` returning:
  `{"status": "ok", "max_context": 65536, "model": "qwen3.8-flash-next-coder-iq1_m", "images": true, "api_key": true, "image_generation": false, "loaded": true, "service": "strata"}`.
- **Rollback Backups:**
  - Binary: `engine/strata.bak-20261107`
  - Build info: `engine/BUILD.json.bak-20261107`
- **Upstream Community Benchmark PR:** Submitted as **[PR #5486](https://github.com/Niko1221/Strata/pull/5486)** from `DamirLukina88:pr/community-benchmark-rx-7600-xt` (`4219bff0`).

## Related

- Implementation Plan: [Strata v0.2.12 Port and Validation Plan](strata-v0212-port-and-validation-plan-2026-11-07.md)
- Deployment Decision: [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)

## Sources

- Upstream release tag `v0.2.12`: `https://github.com/Niko1221/Strata/releases/tag/v0.2.12`
- Implementation Plan: [Strata v0.2.12 Port and Validation Plan](strata-v0212-port-and-validation-plan-2026-11-07.md)
- RX 7600 XT CachyOS Deployment: [rx-7600-xt-cachyos-deployment.md](../decisions/rx-7600-xt-cachyos-deployment.md)
- Benchmark Data:
  - Leg 1: `bench/results/2026-11-07-leg1-base/2026-11-07-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`
  - Leg 2: `bench/results/2026-11-07-leg2-cand/2026-11-07-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`
  - Leg 3: `bench/results/2026-11-07-leg3-base/2026-11-07-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`
  - Leg 4: `bench/results/2026-11-07-leg4-cand/2026-11-07-community-unknown-qwen3-8-flash-next-coder-iq1-m/results.json`

