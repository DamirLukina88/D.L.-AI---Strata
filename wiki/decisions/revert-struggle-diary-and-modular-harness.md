---
title: "Revert of Struggle Diary and Modular Harness"
type: decision
description: "Reverted struggle diary telemetry and modular harness files due to prompt bloat, latency overhead, and RAM eviction on reload"
status: active
tags: [revert, harness, performance, latency, memory, dl-cli]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Revert of Struggle Diary and Modular Harness

## Summary

On 2026-10-24, an experimental implementation of an autonomous **Struggle & Incident Diary** (`tools/dl_diary.py`) and a **Modular Harness-as-Files Architecture** (`harness/`, `tools/dl_harness.py`, `read_skill`) was deployed to Ray. Following deployment, the user experienced noticeable performance degradation. The codebase was restored to the 16:18 backup commit (`a56b2d6b`).

## Root Causes of Performance Degradation

### 1. Prompt Bloat and Prefill Inflation
- The modular harness files added between 550 and 2,400 characters (130 to 600+ tokens) to the system prompt across every single request.
- This directly contradicted the hard-won prompt trim achieved on 2026-10-23 (which pruned system prompt size from 2,598 tokens down to 2,295 tokens).
- On our single GPU (AMD RX 7600 XT, 16 GB VRAM) running a 1-bit quantized 125B MoE (`Qwen3.8-Flash-Next Coder IQ1_M`), every additional hundred tokens in the system prompt increases prefill latency, delays time-to-first-token (TTFT), and consumes context cache budget.

### 2. Slower Agent Execution and Reasoning Indecision
- The additional instructional guidelines and redundant tool guidance caused the model to produce higher token overhead in reasoning blocks before emitting tool calls.
- The `read_skill` tool and extra meta-instructions introduced decision overhead, causing the agent to hesitate and generate extra reasoning steps for simple operations.

### 3. Memory Pressure and Disk Thrashing on Engine Reload
- Concurrently with the new file hooks, the engine reloaded at 18:56 when available system RAM was temporarily constrained (13.6 GiB available).
- Strata's resident memory guard allocated only 9.35 GiB of experts in RAM (instead of the required 20.15 GiB complement), forcing the engine to read the remaining experts from disk during generation.
- This triggered over 74,669 disk blob reads, collapsing decode speed from ~28 tok/s down to 4.1–11.8 tok/s.
- While the RAM allocation was resolved by restarting the server, keeping extra filesystem watchers and telemetry hooks added unnecessary complexity to a setup with tight memory margins.

## Decision: Lean Hardcoded Harness

- **Revert to Clean Baseline**: Restore `tools/dl_cli.py`, `tools/dl_sessiond.py`, and `README.md` to commit `a56b2d6b` (16:18 today).
- **Remove Extraneous Components**: Delete `harness/`, `tools/dl_diary.py`, `tools/dl_harness.py`, `tools/test_dl_diary.py`, and `tools/test_dl_harness.py`.
- **Preserve Core Philosophy**: For this consumer hardware budget (Ryzen 5 3600, 32 GB RAM, 16 GB VRAM), the hardcoded, lean Python harness in `dl_cli.py` with zero extraneous layers provides the highest velocity and lowest latency.

## Sources

1. User, chat, 2026-10-24: "restore to the create a backup first so we can easily restore in case of issues then procede with the plan implementation 4:18 today. the changes degraded the preformance of the model after the restore lint the git repor and wiki add a detailed note in the wiki abotu the revert reasons update readme".
2. Strata server logs (`strata-coder-iq1_m.log`, 2026-10-24 18:56–21:30).
3. Benchmark and prompt trim records (`wiki/artifacts/ray-persona-bench-2026-10-23.md`).
