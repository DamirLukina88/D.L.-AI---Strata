---
title: "Strata v0.2.12 Port and Validation Plan (2026-11-07)"
type: artifact
description: "Implementation and validation plan for porting Strata v0.2.12 features and engine safety guards to RX 7600 XT"
status: active
tags: [upstream, plan, v0.2.12, hip, rx7600xt, qwen-coder]
created: 2026-11-07
updated: 2026-11-07
last_verified: 2026-11-07
---

# Strata v0.2.12 Port & Validation Plan for Ray (AMD RX 7600 XT / gfx1102)

## Goal Description

Port high-value upstream **Strata v0.2.12** improvements into Ray's local AI workstation environment (AMD Ryzen 5 3600, 32 GB RAM, AMD Radeon RX 7600 XT 16 GB VRAM `gfx1102`, CachyOS Linux, ROCm 7.2.4, Qwen3.8-Flash-Next Coder IQ1_M).

The port encompasses:
1. **Python Server & Agent Parser Suite (`serve/`):**
   - **MCP Tool Name Suffix Resolution (#5281):** Match namespaced tools (`mcp__assets__get_asset_info`) when the model emits only the final segment (`get_asset_info`), if unique.
   - **Anthropic Unknown Model Fallback (#5312):** Route arbitrary model names (e.g. `claude-5-5-sonnet` from Claude Desktop) directly to the single loaded model on `/v1/messages`.
   - **Anthropic Tool Result Alignment (#4832):** Align asynchronous parallel tool execution results by `tool_use_id` instead of assuming positional order.
   - **Forced `tool_choice: "required"` Fix (#4828):** Emit `<tool_call>\n` rather than prematurely emitting `<function=`, preventing model hallucination.
   - **Tolerant Tool Openers & Syntax Recovery (#5276, #5409):** Parse `<toolcall>` / `<tool-call>` openers and recover `<function=tools action>` / bare `<function=tools>` calls.
   - **Parser Stream Lookback Window Optimization:** Limit regex evaluation to new delta tokens + 256 characters (`_PREFIX_LOOKBACK`), preventing $O(N^2)$ latency overhead on long agent contexts.
   - **Request & Yield Accounting:** Fix yielded prompt token summing and remove double-counted admission milliseconds from token/sec metrics.
2. **C++/HIP Engine Safety & Correctness Guards:**
   - **MMQ Row Table Over-Read Guard (#5108):** Add `include/strata/prefill/mmq_ids_margin.hpp`, enforce tile bound over-read margins in `src/prefill/moe_mmq.cu` and `src/prefill/prefill.cpp` to prevent out-of-bounds page faults during 64K prompt processing with `STRATA_PREFILL_MMQ=1`.
   - **Adaptive Overlap Flag-B Ordering (#5096, #4844):** Add `include/strata/core/flag_order.hpp` and `include/strata/program/adaptive_range.hpp`, ensuring GPU graph execution waits until DMA expert copies have landed when `STRATA_ADAPT_OVERLAP=1`.
3. **Engine Rebuild & Parity Verification:**
   - Recompile `engine/strata` natively for `gfx1102` using ROCm 7.2 / HIP via Ninja.
   - Run native parity suites (`native_expert_parity`, `mmq_ids_margin_test`, `adaptive_range_test`).
4. **4-Leg Interleaved Paired A/B Benchmark:**
   - Benchmark Base (`strata.bak-20261107`) vs Candidate (`0.1.44.1+0.2.12-fixes`) under `MemorySwapMax=0` across 4 legs (Base 1 -> Cand 1 -> Base 2 -> Cand 2) to eliminate thermal and page cache bias.

---

## User Review Required

> [!IMPORTANT]
> - **Binary Rollback Assurance:** The active engine binary `engine/strata` will be preserved to `engine/strata.bak-20261107` prior to replacement.
> - **Memory Constraints:** System swap remains strictly disabled for the engine (`MemorySwapMax=0` under systemd) to prevent zram thrashing on the 32 GB RAM workstation.
> - **Undeclared Tool Policy:** Per user alignment, `undeclared_tool_calls` remains `"text"` (conservative default).

---

## Open Questions

None remaining. All design tree decisions were resolved during the `/grill-me` interview:
- Scope: Full Stack Port (Server + Engine guards + Rebuild + 4-Leg Benchmark).
- Undeclared tool calls: `"text"`.
- Benchmark rigor: 4-leg interleaved A/B benchmark under `MemorySwapMax=0`.

---

## Proposed Changes

```mermaid
flowchart TD
    subgraph Step 1: Safety & Backups
        B1["Backup engine/strata to strata.bak-20261107"]
        B2["Snapshot BUILD.json"]
    end

    subgraph Step 2: Python serve/ Upgrades
        P1["serve/frontend.py: MCP Suffix, Prefix Lookback, Tolerant Openers, Reordering"]
        P2["serve/server.py: Anthropic Model Fallback, Yield/BDONE Timing, Undeclared setting"]
        P3["serve/ tests: Add upstream tool tests"]
    end

    subgraph Step 3: C++/HIP Engine Guards
        E1["include/strata/prefill/mmq_ids_margin.hpp"]
        E2["include/strata/core/flag_order.hpp"]
        E3["include/strata/program/adaptive_range.hpp"]
        E4["src/prefill/moe_mmq.cu & src/prefill/prefill.cpp"]
        E5["src/core/verify.cpp"]
        E6["CMakeLists.txt: Register new tests"]
    end

    subgraph Step 4: Compilation & Verification
        C1["Ninja Build in build-hip/"]
        C2["Run Unit Tests & Parity Tests"]
        C3["Deploy engine/strata (0.1.44.1+0.2.12-fixes)"]
    end

    subgraph Step 5: 4-Leg A/B Benchmark
        BM["tools/strata_bench.py under MemorySwapMax=0 (4 legs)"]
    end

    Step 1 --> Step 2
    Step 2 --> Step 3
    Step 3 --> Step 4
    Step 4 --> Step 5
```

---

### Component 1: Python Server & Agent Parser (`serve/`)

#### `serve/frontend.py`
- Add `_PREFIX_LOOKBACK = 256` and optimize `_prefixed()` and `_opener()` to only scan buffer tails.
- Add namespaced MCP suffix resolution in `OutputParser.init_aliases()` (#5281):
  ```python
  # #5281: a namespaced MCP tool (mcp__assets__get_asset_info) written with its last segment only (get_asset_info)
  last = name.rsplit("__", 1)[-1]
  if last and last != name:
      aliases.setdefault(last, set()).add(name)
  ```
  Only accept bare alias if `len(candidates) == 1`.
- Add `_order_chat_tool_results(messages)` to pair Anthropic tool results by `tool_use_id` (#4832).
- Update `forced_call()` when `tool_choice == "required"` with multiple tools to return `CALL_START + "\n"` (#4828).
- Support `<function=tools action>` and bare `<function=tools>` (#5409).
- Support `<toolcall>` and `<tool-call>` openers (#5276).

#### `serve/server.py`
- In Anthropic `/v1/messages` request handler: if the requested model name is not explicitly registered and exactly one model is loaded, serve the loaded model (#5312).
- Add `undeclared_tool_calls_setting(cfg)` and default to `"text"`.
- Fix request accounting and yielded legs in `_apply_bdone()` and `prefill_leg_stats()`.

#### `serve/test_anthropic_tool_results.py`
- Port upstream test for tool results sent out of order.

#### `serve/test_tool_name_mcp_member.py`
- Port upstream test verifying that `get_asset_info` matches `mcp__assets__get_asset_info` when unique.

---

### Component 2: C++/HIP Engine Guards (`include/` and `src/`)

#### `include/strata/prefill/mmq_ids_margin.hpp`
- Define `kMmqTileColsMax = 128`, `kMmqTileColsStep = 8`.
- Define `mmq_ids_margin_rows(max_rows, J, out)` and `mmq_ids_table_rows(rows, max_rows)` with safe 64-bit bounds checking.

#### `include/strata/core/flag_order.hpp`
- Implement `flag_raise_max()` with atomic compare-exchange.
- Implement `raise_flag_b_ordered()` to enqueue host function callbacks on the copy stream when copies are queued, preventing early flag raises.

#### `include/strata/program/adaptive_range.hpp`
- Implement `AdaptiveCopyRange` struct (`clear`, `next_batch`, `whole_round`, `landed_begin`, `landed_end`, `more`).

#### `src/prefill/moe_mmq.cu`
- Use `kMmqTileColsMax` and `kMmqTileColsStep` from `mmq_ids_margin.hpp` across tile search loops.

#### `src/prefill/prefill.cpp`
- Size `ids_identity` and MMQ row allocations using `mmq_ids_table_rows()`.

#### `src/core/verify.cpp`
- Route Flag-B completion through `Verifier::raise_flag_b_ordered()`.

#### `CMakeLists.txt`
- Register `mmq_ids_margin_test` and `adaptive_range_test`.

---

### Component 3: Build & Deployment

#### `engine/BUILD.json`
- Update version string from `0.1.44.1+0.2.11-fixes` to `0.1.44.1+0.2.12-fixes`.

---

## Verification Plan

### Automated Tests

1. **Serve Unit Test Suite:**
   ```bash
   python3 -m unittest \
     serve.test_tool_corpus \
     serve.test_param_end_options \
     serve.test_web_start_question \
     serve.test_serve_robustness \
     serve.test_anthropic_tool_results \
     serve.test_tool_name_mcp_member
   ```

2. **Native Engine C++ Parity & Unit Tests:**
   ```bash
   ninja -C build-hip strata mmq_ids_margin_test adaptive_range_test native_expert_parity
   ./build-hip/mmq_ids_margin_test
   ./build-hip/adaptive_range_test
   ./build-hip/native_expert_parity
   ```

3. **Live Server Health & Tool Verification:**
   - Restart service: `systemctl --user restart strata-server.service`
   - Health check: `curl -s http://127.0.0.1:8080/health`

### 4-Leg Paired A/B Benchmark Protocol

Execute 4 interleaved legs comparing Base (`strata.bak-20261107`) against Candidate (`0.1.44.1+0.2.12-fixes`) under `MemorySwapMax=0`:
- Leg 1: Base (`strata.bak-20261107`)
- Leg 2: Candidate (`build-hip/strata`)
- Leg 3: Base (`strata.bak-20261107`)
- Leg 4: Candidate (`build-hip/strata`)

Compute paired median comparison across Chat decode, TTFT, 4K/16K prompt prefill tok/s, agent cache hit %, and swap usage.

## Related

- [Upstream Strata v0.2.12 Review and A/B Benchmark (2026-11-07)](upstream-v0-2-12-review-and-benchmark-2026-11-07.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)

## Sources

1. User request and `/grill-me` alignment session — chat, 2026-11-07.
2. Upstream release tag `v0.2.12`: `https://github.com/Niko1221/Strata/releases/tag/v0.2.12`.
3. Artifact `strata_v0212_port_and_validation_plan.md` in conversation brain.
