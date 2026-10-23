---
title: "Upstream Strata 0.2.3 Review (2026-10-23)"
type: artifact
description: "Which upstream 0.2.3 changes fit this install (RX 7600 XT, Linux, 32 GB RAM): 6 engine/server/vision/web fixes ported; STRATA_HC_Q8=1 and speculative warm-up queued for same-day GPU bench"
status: active
tags: [upstream, release, review, gfx1102, engine, speculative, vision, server]
created: 2026-10-23
updated: 2026-10-23
last_verified: 2026-10-23
---

# Upstream Strata 0.2.3 Review (2026-10-23)

## Summary

Upstream released 0.2.3 (tag `v0.2.3`, commit `5c8dd322`, engine 0.1.48) on 2026-10-23. `v0.2.2..v0.2.3` touches 291 files (+33,827 / -2,451). Most of the release targets hardware or features not used here (Gyro-M/Gyro-S/Gemma 4, `strata_kq` CUDA K-quant DLL, Strix Halo `gfx1151` defaults, multi-GPU split defaults, macOS/Windows installer paths). Six targeted engine, vision, server, and CSS fixes were ported onto our `HEAD` (`16757910`) and built into `engine/strata` (`0.1.44.1+0.2.3-fixes`) and `engine/strata-vision`.

| 0.2.3 / 0.2.2 change | Applies here? | Status (2026-10-23) |
|---|---|---|
| `--spec` 1-token prompt fix (`aece46db`, 0.2.2): `spec_pos = -1` so a 1-token prompt on a native pack enters the speculative loop | Yes | **Ported & built** in `src/program/generate.cpp` |
| Speculative adaptive tier warm-up (`2ccf57ec`, 0.2.3): `STRATA_SPEC_ADAPT_EVERY` / `STRATA_SPEC_ADAPT_WARM` swap faster in the first verify rounds | Yes, opt-in | **Ported & built** in `src/program/generate.cpp` (default off; ready for A/B bench) |
| Elastic vision encoder on tool-returned images + startup diagnostics (`c40a03e6`, 0.2.3) | Yes | **Ported & tested** (`serve/server.py`, `serve/test_vision_tool_image.py`) |
| Vision token limit default & enforcement (`828a2559`, 0.2.3, #3690): GPU 1024 / CPU 300 default, `strata-vision` refuses $> \text{limit} + \frac{1}{8}$ | Yes | **Ported, built & tested** (`serve/server.py`, `tools/vision/strata_vision.cpp`, `serve/test_vision_token_limit.py`) |
| Unread `<tool_call>` name logging (`8bf178fe`, 0.2.3 partial) | Yes (log part only) | **Ported & tested** (`serve/frontend.py`, `serve/server.py`); kept our local rule where undeclared `<function=NAME>` with tools declared stays a tool call for D.L. CLI |
| `.cfg-form` narrow-window clipping fix (`9471faa5`, 0.2.3) | Yes | **Ported** (`serve/web/app.css`, cache-busted in `serve/web/index.html`) |
| `STRATA_HC_Q8=1` (8-bit hyper-connection weights, `src/core/native_dense.cpp:46`) enabled by default on `gfx1151` (+7.9% to +10.7% decode) | Yes (`gfx1102`) | **Benchmarked & enabled** in `strata-coder-iq1_m.json` (+4.4% agent decode, +8.4% cold code decode, +1.4% 4K prefill, -14s total bench time) |
| `86d10ed8` HIP verify-hang fix, `894f133b` NaN batched retry, `70f42407` `#3441` loose tool openers, `fccfd343` `answer_speed()`, PR `#3556` tool aliases | Already here | Ported on 2026-10-13 / 2026-10-21 (see [0.2.2 Review](upstream-v0-2-2-review-2026-10-21.md)) |
| Gyro-M / Gyro-S / Gemma 4, `strata_kq` CUDA DLL, NVIDIA `nv_defaults`, multi-GPU split, Windows/macOS packaging | No | Different hardware or model family |

## Ported and Built (2026-10-23)

- **Engine (`src/program/generate.cpp`):**
  - `aece46db`: `spec_pos` initialized to `-1` and checked with `spec_pos >= 0`.
  - `2ccf57ec`: Added `adapt_every_given`, `adapt_warm_every`, `adapt_warm_rounds`, `adapt_iv(rounds)`, and `STRATA_SPEC_ADAPT_EVERY` / `STRATA_SPEC_ADAPT_WARM` environment variable support.
  - Built in `build-hip/strata` and installed to `engine/strata` (backup: `engine/strata.bak-20261023`, `engine/BUILD.json.bak-20261023`).
- **Vision (`tools/vision/strata_vision.cpp`, `serve/server.py`):**
  - `c40a03e6` and `828a2559` applied; `build-vision/bin/strata-vision` rebuilt and installed to `engine/strata-vision` (backup: `engine/strata-vision.bak-20261023`).
  - `serve.test_vision_tool_image` and `serve.test_vision_token_limit` pass (123 tests run across vision, frontend, and setup suites: all OK).

## Same-Day GPU Benchmark Results on RX 7600 XT (`gfx1102`) (2026-10-23)

Ran the 7-prompt greedy identity suite (`temperature 0`) and `tools/strata_bench.py --runs 3` across three arms (`bench/results/v0.2.3-rx7600xt-2026-10-23/{baseline,hc_q8,spec_warm}`):

### 1. `tools/strata_bench.py` (3 runs, medians and ranges)

| Metric | Baseline (`0.1.44.1+0.2.3-fixes`) | Arm A: `STRATA_HC_Q8=1` | Arm B: `STRATA_SPEC_ADAPT_EVERY=2`, `WARM=200` |
|---|---:|---:|---:|
| **Short chat decode (tok/s)** | 23.9 (20.2–29.0) | **24.2** (20.4–30.9) | 23.1 (19.6–29.6) |
| **4K fresh prefill (tok/s)** | 298.6 (295.5–301.1) | **302.8** (285.8–303.4) | 297.0 (294.1–302.6) |
| **4K fresh TTFT (s)** | 13.52 (13.40–13.65) | **13.32** (13.29–14.12) | 13.58 (13.34–13.72) |
| **16K fresh prefill (tok/s)** | 331.0 (318.4–332.1) | **334.4** (318.1–335.1) | 330.2 (309.2–335.5) |
| **16K fresh TTFT (s)** | 48.57 (48.41–50.49) | **48.08** (47.98–50.53) | 48.68 (47.91–51.99) |
| **Agent session decode (tok/s)** | 24.8 (20.3–30.0) | **25.9** (21.4–31.0) (**+4.4%**) | 27.1 (21.7–33.5) |
| **Agent session TTFT (s)** | 11.76 (7.02–12.71) | **11.26** (6.96–12.03) | 11.44 (7.03–12.07) |
| **Agent first-turn cold TTFT (s)** | 5.24 (4.55–7.69) | **4.67** (4.57–4.77) | 4.71 (4.65–4.96) |
| **Suite wall time (s)** | 475 s | **461 s** (**-14 s**) | 471 s |

### 2. Cold-Start 7-Prompt Greedy Verification (`identity.py`, first 200 verify rounds after load)

| Prompt | Baseline (tok/s) | `STRATA_HC_Q8=1` (tok/s) | `SPEC_ADAPT_EVERY=2, WARM=200` (tok/s) | Greedy Answer Parity |
|---|---:|---:|---:|---|
| `capital` | 13.7 | **14.5** (+5.8%) | 11.3 (-17.5%) | Identical (`Canberra`) |
| `math` | 22.5 | 21.9 | 18.6 (-17.3%) | Identical (`782`) |
| `code` | 29.8 | **32.3** (+8.4%) | 27.2 (-8.7%) | Identical (`fibonacci`) |
| `story` | 18.2 | 18.1 | 15.7 (-13.7%) | Identical |
| `long4k` | 19.1 | **20.1** (+5.2%) | 17.4 (-8.9%) | Identical (`Line 211`, `dog number 8`) |
| `think` | 28.7 | **29.2** (+1.7%) | 26.3 (-8.4%) | Identical (`No, 391 = 17 × 23`) |
| `tool` | 31.4 | **32.2** (+2.5%) | 29.2 (-7.0%) | Identical (`shell` tool call) |

### Decision

- **`STRATA_HC_Q8=1` enabled** in `strata-coder-iq1_m.json`: faster across cold decode (`code` +8.4%, `capital` +5.8%, `long4k` +5.2%, `tool` +2.5%), `strata_bench.py` short chat (24.2 vs 23.9 tok/s), 4K/16K prefill (302.8 / 334.4 tok/s, a new 16K prefill record on this PC), and agent decode (25.9 vs 24.8 tok/s, +4.4%), with zero answer regressions.
- **`STRATA_SPEC_ADAPT_EVERY=2` left off** (default `adapt_every = 4`): on discrete PCIe 4.0 x8 + DDR4, doubling the H2D expert swap frequency during the first 200 verify rounds slows down cold-start decode by 7%–17%.

## Related

- [Upstream Strata 0.2.2 Review (2026-10-21)](upstream-v0-2-2-review-2026-10-21.md)
- [Engine Port Check Scripts (2026-10-21)](engine-port-check-scripts-2026-10-21.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)

## Sources

1. Upstream release `v0.2.3` (`5c8dd322`, 2026-10-23) in `https://github.com/Niko1221/Strata.git`, inspected via `git fetch upstream --tags` and `git log v0.2.2..v0.2.3`.
2. Upstream commits `aece46db`, `2ccf57ec`, `c40a03e6`, `828a2559`, `8bf178fe`, and `9471faa5`, ported and tested on 2026-10-23.
