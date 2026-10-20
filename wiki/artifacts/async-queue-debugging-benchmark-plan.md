---
title: "Async Queue Debugging Benchmark Plan (not built)"
type: artifact
description: "Planned harder D.L. CLI benchmark (17 Oct): a multi-file async pipeline bug whose root cause is in channel.py; not built as of 2026-10-20"
status: active
tags: [benchmark, plan, dl-cli, reasoning, not-built]
created: 2026-10-20
updated: 2026-10-20
last_verified: 2026-10-20
---

> **Status (2026-10-20): planned, not built.** Antigravity wrote this plan on 2026-10-17 as the harder follow-up to the [Weather Reasoning Benchmark](../decisions/weather-reasoning-benchmark.md), and asked to Proceed; neither `tools/async_queue_bench.py` nor its test exists. The tetris / bugfix / crc32c / longplan tasks of `tools/dl_agent_bench.py` are what is measured today ([D.L. CLI Keeps Its Task](../decisions/dl-cli-task-memory-and-finish-checks.md)).

# Plan (2026-10-17): Async Queue Multi-File Debugging Benchmark (`async_queue_bench.py`)

## Goal Description
Build a challenging, multi-file root-cause debugging benchmark `tools/async_queue_bench.py` specifically designed to test the limits of CLI reasoning levels (**`none`**, **`low`**, **`medium`**, **`high`**).

Unlike the weather task (which could be solved via trial-and-error tool calling even with thinking off), this benchmark creates an asymmetric difficulty cliff:
- The symptom manifests in `test_pipeline.py` and `pipeline/dispatcher.py` as intermittent timeouts and dropped events under heavy backpressure.
- Low-reasoning models will attempt superficial band-aid fixes (e.g., arbitrarily increasing timeouts, ignoring failed acknowledgments, or adding hacky sleeps in the test or dispatcher), which immediately fail the hidden stress suite.
- High-reasoning models must trace the asynchronous dataflow upstream across multiple files to identify the real concurrency bug inside `pipeline/channel.py` (a race condition in `nack` requeue watermark signaling and condition variable notifications).

---

## Architecture of the Challenge

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Async Event Pipeline                            │
│                                                                        │
│   ┌───────────────┐     put()      ┌───────────────────────────────┐   │
│   │   Producers   │ ─────────────> │      pipeline/channel.py      │   │
│   └───────────────┘                │  (BoundedChannel, Watermarks) │   │
│           ▲                        └───────────────────────────────┘   │
│           │ pause / resume backpressure            │                   │
│           └─────────────────────────┐              │ get() / nack()    │
│                                     │              ▼                   │
│   ┌───────────────────────────┐     │      ┌───────────────────────┐   │
│   │ pipeline/retry_policy.py  │ <───┼───── │ pipeline/dispatcher.py│   │
│   │   (Exponential Backoff)   │     │      └───────────────────────┘   │
│   └───────────────────────────┘     │              │                   │
│                                     │              ▼ dispatch()        │
│                                     │      ┌───────────────────────┐   │
│                                     └────  │pipeline/worker_pool.py│   │
│                                            └───────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### The Bug Mechanics:
1. **The Symptom**: Under high backpressure and worker transient failures, `test_pipeline.py` intermittently deadlocks or raises `TaskLossError`.
2. **The Superficial Trap**:
   - `dispatcher.py` or `worker_pool.py` appears to stall because tasks stop arriving. A model without deep reasoning patches `dispatcher.py` by adding `asyncio.sleep()`, skipping failed tasks, or bumping concurrency limits.
3. **The True Root Cause (`pipeline/channel.py`)**:
   - When workers `nack()` failed tasks back into the channel, `_requeue()` updates buffer counts but uses `Condition.notify(1)` instead of `notify_all()`, stranding other waiting consumers when a task is immediately re-buffered.
   - Additionally, when `nack()` pushes the buffer count back above the `resume_threshold` while the producer is paused, the backpressure event states desynchronize, causing producers to permanently sleep on `_resumed.wait()`.

---

## Proposed Changes

### 1. Benchmark Fixtures & Hidden Suite
Create `tools/async_queue_bench/`:
- **`fixtures/`**: The starting buggy codebase placed into each test session's workspace:
  - `pipeline/__init__.py`
  - `pipeline/channel.py` *(contains the subtle watermark & notification bug)*
  - `pipeline/dispatcher.py`
  - `pipeline/worker_pool.py`
  - `pipeline/retry_policy.py`
  - `test_pipeline.py` *(visible basic unit test suite)*
- **`hidden/`**: The verification suite run by the benchmark runner after the agent finishes:
  - `test_backpressure_stress.py`: 500 events across 10 concurrent producers through a small buffer (capacity 20) with 20% simulated transient failures.
  - `test_invariants.py`: Verifies zero lost tasks, strict watermark enforcement, no memory leaks, and anti-cheat checks (verifies `test_pipeline.py` was not modified or neutered).

### 2. Standalone Runner Script
#### [NEW] `tools/async_queue_bench.py`
- Connects to `dl-ai-sessiond` via Unix socket.
- Provisions isolated workspaces (`ws-none`, `ws-low`, `ws-medium`, `ws-high`) copied fresh from `fixtures/`.
- Sends the prompt:
  > *"Users report intermittent stalls and occasional lost events in our async event pipeline under heavy backpressure with retries. Running `python3 test_pipeline.py` occasionally hangs or fails with TaskLossError. Investigate the pipeline, find the root cause of the stall/task loss, fix it, and ensure all unit tests pass without modifying the test suite or weakening backpressure guarantees."*
- Follows the agent turns with configurable timeout (default: **20 minutes**, `--timeout-minutes`) and turn limit (default: **10 turns**, `--max-turns`).
- **100-Point Scorecard**:
  - **Root Cause Fixed in `channel.py` (25 pts)**: Inspects `git diff` to ensure `pipeline/channel.py` was modified and fixed; awards 0 if `dispatcher.py` or tests were hacked.
  - **Visible Tests Pass (25 pts)**: Runs `python3 test_pipeline.py` in the workspace; must pass with exit code 0.
  - **Hidden Concurrency & Backpressure Suite (35 pts)**: Runs the hidden stress tests; must pass with 0 dropped events and 0 deadlocks.
  - **Diff Quality & Invariant Hygiene (15 pts)**: No `sleep()` workarounds, clean diff under 40 lines changed, no modified tests.
- **Telemetry**: Measures wall-clock seconds, thinking time, thinking character volume, and tool calls.
- Outputs Markdown report and ANSI terminal comparison table.

### 3. Verification Suite
#### [NEW] `tools/test_async_queue_bench.py`
- Unit tests verifying:
  - The buggy fixture fails the hidden stress tests out of the box.
  - A reference patch fixing `channel.py` passes 100/100 on the scorecard.
  - Superficial patches in `dispatcher.py` or test deletions score < 50/100.
  - Summary table formatting and scorecard calculations.

---

## Verification Plan

### Automated Tests
1. Run benchmark self-tests:
   ```bash
   python3 tools/test_async_queue_bench.py
   ```
2. Verify CLI options and help:
   ```bash
   python3 tools/async_queue_bench.py --help
   ```

### Manual Verification
1. Run a quick validation test:
   ```bash
   python3 tools/async_queue_bench.py --efforts none --timeout-minutes 2.0 --max-turns 2
   ```
2. Run full 4-level sweep:
   ```bash
   python3 tools/async_queue_bench.py --efforts none,low,medium,high
   ```
3. Observe live in terminal:
   ```bash
   python3 tools/dl_cli.py --attach <session_name>
   ```

## Sources

1. Antigravity conversation `9bf3cff9-62d2-4481-9e7c-62dc887771cd`, artifact `async_queue_bench_plan.md`, 2026-10-17 (copied 2026-10-20).
2. User, chat, 2026-10-17: "suggest a harder benchmark that would test the capability of the reasoning".
