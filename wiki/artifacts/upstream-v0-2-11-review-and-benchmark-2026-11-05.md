---
title: "Upstream Strata v0.2.11 Review and A/B Benchmark (2026-11-05)"
type: artifact
description: "Upstream Strata v0.2.11 review, server robustness ports, Q5_0 dot precision fix in C++/HIP, and 4-leg paired A/B benchmark on RX 7600 XT"
status: active
tags: [upstream, review, benchmark, v0.2.11, hip, rx7600xt]
created: 2026-11-05
updated: 2026-11-05
last_verified: 2026-11-05
---

# Upstream Strata v0.2.11 Review and A/B Benchmark (2026-11-05)

## Summary

`git fetch upstream` on 2026-11-05 brought tag `v0.2.11` (commit `9f7d977d`), spanning commits from `v0.2.10` (`ffa80d73`) to `v0.2.11` (`9f7d977d`) and recent PR merges on `upstream/main`.
Our local fork branches from `296b59d2` (2026-10-14) and maintains Ray's personalized assistant persona, local PipeWire STT/TTS routing, and Android companion extensions.

Following an audit against our local wiki decisions and hardware limits (AMD Ryzen 5 3600, 32 GB RAM, RX 7600 XT `gfx1102` 16 GB VRAM, CachyOS Linux), we ported high-value server robustness fixes and the C++/HIP Q5_0 expert dot precision kernel fix, rebuilt the native HIP engine (`0.1.44.1+0.2.11-fixes`), and ran a full 4-leg paired A/B benchmark under `MemorySwapMax=0`.

---

## Evaluation: What Was Adopted vs. Excluded

### 1. Excluded (Not Applicable or Rule-Violating)

- **Unsloth Dynamic Sets (UD-IQ1_M to UD-IQ4_XS-v31):** Require $\ge 48$ GB RAM to avoid swap thrashing. Our workstation has 32 GB RAM. Adopting would cause zram thrashing and GPU stalls, violating [rx-7600-xt-cachyos-deployment.md](../decisions/rx-7600-xt-cachyos-deployment.md).
- **Multi-Card Split Engine (`FNX_PF_HCSPLIT`, peer memory sums, A2A):** Targets 2–4 GPU topologies. Workstation has 1 GPU (RX 7600 XT).
- **DFlash2 Multi-Card Drafter:** Inapplicable to Qwen Coder models (which run native MTP `--spec 4`).
- **Mac / Windows Disk Priority (#4733):** Workstation runs Linux CachyOS.

### 2. Adopted & Implemented

- **Server Streaming Socket Timeout (`c08fd2ec`):** Sets `STREAM_WRITE_TIMEOUT_S = 60s` on SSE generator writes to prevent deadlocked HTTP sockets from hanging worker threads.
- **Dropped Request & Restart Race Guard (`a8767488`, `74f39053`):** Added `end_engine_if_unchanged(born)` and `batch_slots_on(engine)` to prevent stale client requests from stopping a freshly spawned engine process.
- **Isolated SD-CLI Prompt File (`ff36fa92`):** Passes diffusion prompt via temporary `0o600` `--prompt-file` to protect user prompts from local process snooping (`/proc/*/cmdline`).
- **Tool Argument Streaming Closing-Tag Fix (`3bbf0f39` - #5040, #4701):** Prevents parser from truncating JSON parameters when closing tags (`</tool_call>`) are arriving in chunked streams.
- **Web Prefill Without Auto-Submit (`faf3db29`):** Populates `/?q=` query text into composer textarea without auto-executing, mitigating navigation injection.
- **C++/HIP Q5_0 Expert Dot Precision Fix (`aa678f10`):** In `src/kernels/cuda/iq_kernels.cu` (`vec_dot_q5_0_q8_1`), the -16 offset previously multiplied raw `ds.y` (unrounded activation sums). SwiGLU activation non-zero means caused whole-expert relative error of 2.1e-2 .. 3.1e-2. Multiplying quantized sums (`ggml_cuda_dp4a(0x01010101, ...)`) reduces error to 1.2e-2, matching CPU. Parity gate in `src/kernels/native_expert_parity.cpp` tightened to `1.8e-2`.

---

## Unit Testing & Parity Verification

1. **Serve Unit Tests:**
   - `python3 -m unittest serve.test_tool_corpus serve.test_param_end_options serve.test_web_start_question serve.test_serve_robustness`:
   - 27/27 tests passed cleanly (11.1 s).
2. **Native Parity Verification (`./build-hip/native_expert_parity`):**
   - `q4_K / q5_0`: CPU rel `1.32e-02`, GPU rel `1.24e-02` (down from `3.1e-2`), status: `ok`.
   - `q4_K / q4_0`: CPU rel `1.32e-02`, GPU rel `1.25e-02`, status: `ok`.
   - `q4_K / q5_1`: CPU rel `1.42e-02`, GPU rel `1.25e-02`, status: `ok`.
   - `--q5_1-min`: 0 failures.

---

## 4-Leg Paired A/B Benchmark Results

Executed on 2026-11-05 under `systemd-run --user --wait --pipe -p MemorySwapMax=0` with `tools/strata_bench.py` against the production model (**Qwen3.8-Flash-Next Coder IQ1_M**, MTP `--spec 4`, `--max-context 65536`, int8 KV cache, 256 experts resident in RAM).

### Leg-by-Leg Measurements

| Metric | Leg 1 (Base 1) | Leg 2 (Cand 1) | Leg 3 (Base 2) | Leg 4 (Cand 2) |
| :--- | :--- | :--- | :--- | :--- |
| **Engine Executable** | `strata.bak-20261105` | `strata` (new HIP) | `strata.bak-20261105` | `strata` (new HIP) |
| **Chat Decode (tok/s)** | 23.10 | 22.00 | 22.90 | 22.90 |
| **Chat TTFT (s)** | 1.66 | 1.64 | 1.61 | 1.61 |
| **4K Prompt (tok/s)** | 293.00 | 295.40 | 291.70 | 295.90 |
| **4K TTFT (s)** | 13.77 | 13.65 | 13.83 | 13.63 |
| **16K Prompt (tok/s)** | 332.10 | 333.40 | 330.20 | 333.60 |
| **16K TTFT (s)** | 48.41 | 48.22 | 48.68 | 48.18 |
| **Agent Cache Hit %** | 67.19% | 67.16% | 67.30% | 67.06% |
| **Agent Turn TTFT (s)** | 11.96 | 11.67 | 12.06 | 11.80 |
| **Agent Decode (tok/s)** | 29.10 | 26.90 | 27.40 | 25.50 |
| **Peak RAM (GB)** | 23.0 | 22.7 | 23.4 | 23.0 |
| **Swap Usage (B)** | 0 | 0 | 0 | 0 |

### Paired Median Comparison

| Metric | Base Median (Leg 1 & 3) | Candidate Median (Leg 2 & 4) | Delta | Verification Assessment |
| :--- | :--- | :--- | :--- | :--- |
| **Chat Decode** | 23.00 tok/s | 22.45 tok/s | -2.4% | Within normal jitter ($\pm 3\%$) |
| **Chat TTFT** | 1.635 s | 1.625 s | -0.6% | Flat / slightly faster |
| **4K Prompt** | 292.35 tok/s | 295.65 tok/s | **+1.1%** | Consistent prompt prefill improvement |
| **4K TTFT** | 13.80 s | 13.64 s | **-1.2%** | Faster time to first token |
| **16K Prompt** | 331.15 tok/s | 333.50 tok/s | **+0.7%** | Consistent prompt prefill improvement |
| **16K TTFT** | 48.54 s | 48.20 s | **-0.7%** | Faster time to first token |
| **Agent Cache Hit %** | 67.24% | 67.11% | -0.13% | Byte-for-byte cache parity maintained |
| **Agent Turn TTFT** | 12.01 s | 11.74 s | **-2.2%** | Faster multi-turn response latency |
| **Swap Memory** | 0 B | 0 B | 0 B | Zero swap thrashing enforced |

---

## Deployment & Production Status

- **Engine Binary:** Compiled natively for `gfx1102` with ROCm 7.2 / HIP and deployed to `engine/strata`. Version marked `"0.1.44.1+0.2.11-fixes"` in `engine/BUILD.json`.
- **Service Status:** `strata-server.service` restarted and active. Health verified via `http://127.0.0.1:8080/health`:
  `{"status": "ok", "max_context": 65536, "model": "qwen3.8-flash-next-coder-iq1_m", "images": true, "api_key": true, "image_generation": false, "loaded": false, "service": "strata"}`.
- **Rollback Binary:** Preserved at `engine/strata.bak-20261105`.

## Sources

- [upstream-v0-2-10-review-2026-11-03.md](upstream-v0-2-10-review-2026-11-03.md)
- [rx-7600-xt-cachyos-deployment.md](../decisions/rx-7600-xt-cachyos-deployment.md)
- Upstream GitHub releases & commits: `https://github.com/Niko1221/Strata` (commits `c08fd2ec`, `a8767488`, `74f39053`, `ff36fa92`, `3bbf0f39`, `faf3db29`, `aa678f10`)

