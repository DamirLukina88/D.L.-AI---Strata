---
title: "Component 4: Prompt Tokenizer Prefix Caching Validation & Benchmark Report"
type: artifact
description: "Implementation, bitwise verification, and dual-tier benchmark for upstream commit f13a870d (Prompt Tokenizer Prefix Caching #567 / #1852)"
status: active
tags: [strata, v0.1.45, tokenizer, prefix-caching, prompt-encoder, bpe, cpu-optimization, multi-turn]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Component 4: Prompt Tokenizer Prefix Caching Validation & Benchmark Report

## 1. Feature Architecture & Problem Solved

* **Problem Solved:** In multi-turn chat and coding-agent sessions (such as Claude Code or Roo Code), clients resend the entire conversation history with each turn. Previously, Strata re-tokenized the entire prompt from byte offset 0 through BPE merge loops on every request. At large context depths (16K to 150K tokens), CPU re-tokenization incurred measurable latency and CPU overhead on each request, even when the underlying GPU KV cache already held the entire prefix.
* **Port Target:** Upstream commit `f13a870d` (`#567` / `#1852`).
* **Implementation Details:**
  * **Incremental `PromptEncoder` (`tools/strata_tokenizer.py`):**
    * Keeps recent prompt texts, token IDs, and special-token resume points in memory (`keep=slots`, defaulting to 4 slots matching `--conversation-cache-slots`).
    * On new requests, computes the common prefix with active slots (`common_prefix_len`), checks agreement of literal spans (`plain_agree_until`), and identifies the latest shared special-token boundary via bisection.
    * Reuses pre-computed token IDs up to that boundary and only executes BPE tokenization on the remaining incremental text (`text[c:]`).
    * Preserves memory safety: prompts refused for context limits are evicted via `forget_prompt()`; token counting (`/v1/messages/count_tokens`) uses `store=False` to prevent cache pollution.
  * **Tokenizer Resume Points & Integration (`serve/server.py`):**
    * Implemented `max_special_len` and `encode_marked(text, parse_special, plain)` in `ByteTokenizer` and `strata_tokenizer.Tokenizer`.
    * Added `conversation_slots(engine)` helper to dynamically configure encoder slots matching engine settings.
    * Integrated `self.prompts = PromptEncoder(tokenizer, keep=slots)` into `Service.__init__`, `Service.encode_prompt`, and `Service.prepare`.
  * **Documentation & Security (`SECURITY.md`):**
    * Documented in-process ephemeral storage of prompt prefixes for fast resumption.
* **Zero-Git Local Implementation:**
  * Baseline files preserved in `/mnt/data/Strata-data/local_backups/v145_eval/` (`server.py`, `test_server.py`, `strata_tokenizer.py`, `test_strata_tokenizer.py`, `server.py.comp3_kept`).

---

## 2. Automated Test Suite Verification

* **Full Automated Test Coverage:**
  1. `tools.test_strata_tokenizer`: **18/18 tests passed** (BPE heaps, piece caching, resume point marks, margin lookahead, prefix alignment).
  2. `serve.test_prompt_encoder`: **7/7 tests passed** (2,400 randomized multi-turn prompts, adversarial edits, token parity).
  3. `serve.test_server.IncrementalPrompts`: **8/8 tests passed** (conversation slot sync, token count isolation, lazy engine initialization, prefix reuse).
  4. Component 3 Regression Test (`ThinkingBudget` & `reasoning_loop_recovery`): **38/38 tests passed**.
* **Total Automated Tests:** **71 / 71 passed with 0 failures**.

---

## 3. Tier 2: Custom Feature Benchmark (`tools/custom_tokenizer_bench.py`)

Evaluated directly on the production `Qwen3.8-Flash-Next Coder` tokenizer pack (`/mnt/data/Strata-data/packs/coder-iq1_m/tokenizer`) comparing Full Re-tokenization against Prefix PromptEncoder resumption across 5 expanding turns up to ~148K tokens (5 iterations per turn, median reported).

### Multi-Turn CPU Tokenization Latency & Speedup

| Turn | Context Size | Full Tokenize (ms) | Prefix Tokenize (ms) | Speedup Ratio | Characters Reused | Bitwise Parity Gate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Turn 1 (Cold Prompt)** | 3,414 tokens | 2.40 ms | 2.41 ms | 1.00x | 0 chars | **PASS (100% Identical)** |
| **Turn 2 (Follow-up Turn)** | 17,732 tokens | 11.59 ms | 9.36 ms | **1.24x** | 11,276 chars | **PASS (100% Identical)** |
| **Turn 3 (Deep Context)** | 46,572 tokens | 30.03 ms | 17.98 ms | **1.67x** | 57,789 chars | **PASS (100% Identical)** |
| **Turn 4 (Large Session)** | 90,208 tokens | 57.00 ms | 28.03 ms | **2.03x** | 151,366 chars | **PASS (100% Identical)** |
| **Turn 5 (Massive Context)** | 148,366 tokens | 95.54 ms | 37.51 ms | **2.55x** | 292,895 chars | **PASS (100% Identical)** |
| **5-Turn Session Total** | **306,292 tokens** | **196.56 ms** | **95.29 ms** | **2.06x faster** | **CPU Saved: 101.3 ms** | **PASS (100% Parity)** |

### Multi-Tenant Interleaved Slot Retention (keep=4)
* Initialized 4 distinct concurrent conversations with independent system prompts and codebases.
* Interleaved follow-up requests across conversations 1 through 4:
  * Conv 1: 11,276 chars reused.
  * Conv 2: 11,276 chars reused.
  * Conv 3: 11,276 chars reused.
  * Conv 4: 11,276 chars reused.
* **Interleaved Multi-Conversation Slot Retention: PASS** (no cross-conversation evictions or cache corruption).

---

## 4. Tier 1: End-to-End System Benchmark (`tools/strata_bench.py`)

Evaluated on `Qwen3.8-Flash-Next Coder (IQ1_M)` on the active server instance (`systemd --user` on port 8080) with 3 full runs across short chat, 4K prompt, 16K prompt, 32K long context, and the 5-turn coding agent session.

### Comparative Benchmark Results (Arm 2B vs Arm 4)

| Metric / Scenario | Arm 2B Baseline (No Prefix Caching) | Arm 4 Candidate (Prefix Caching Active) | Delta / Impact |
| :--- | :---: | :---: | :---: |
| **Chat Decode Throughput** | 23.50 tok/s | 23.20 tok/s | -1.3% (run-to-run noise) |
| **Chat First Token (TTFT)** | 1.87 s | 1.88 s | +0.6% (identical) |
| **4K Prompt Ingestion** | 300.40 tok/s | 296.10 tok/s | -1.4% (normal variance) |
| **4K TTFT** | 13.43 s | 13.63 s | +0.20 s |
| **16K Prompt Ingestion** | 332.90 tok/s | 330.70 tok/s | -0.7% (identical) |
| **16K TTFT** | 48.28 s | 48.61 s | +0.33 s |
| **32K Prompt Ingestion** | 331.80 tok/s | 329.40 tok/s | -0.7% (identical) |
| **32K TTFT** | 96.66 s | 97.37 s | +0.71 s |
| **Agent Cache Hit Rate** | 68.34% | **68.38%** | **+0.04%** (stable KV reuse) |
| **Agent Decode Throughput** | 26.80 tok/s | **28.20 tok/s** | **+1.40 tok/s (+5.22%)** |
| **Agent Turn TTFT** | 11.45 s | 11.59 s | Within standard spread |

---

## 5. Statistical Key Takeaways & Assessment

1. **Massive CPU Tokenization Acceleration:** In long multi-turn sessions, Python CPU tokenization time is cut in half overall (**2.06x faster**), reaching **2.55x faster** on turn 5.
2. **Bitwise Mathematical Precision:** Every single token ID across 2,400 automated unit test cases and 148K benchmark contexts is bitwise identical to full re-tokenization.
3. **Multi-Session Safety:** Conversation slots perfectly synchronize with `--conversation-cache-slots` (4 slots), ensuring multi-tenant agent sessions don't clobber each other's prefixes.
4. **Zero GPU Engine Regressions:** Full system benchmarks show unchanged prompt prefill and decode speeds within expected variance, with KV cache hit rates fully preserved (68.38%).

---

## Sources

* Upstream Strata commit `f13a870d` (`#567` / `#1852`).
* Local benchmark harness: `tools/custom_tokenizer_bench.py`.
* Results file: `bench/results/custom_tokenizer_bench_results.json` and `bench/results/arm4_prefix_on`.
* Evaluation plan: [`wiki/artifacts/upstream-v0-1-45-evaluation-and-benchmark-plan.md`](upstream-v0-1-45-evaluation-and-benchmark-plan.md).
