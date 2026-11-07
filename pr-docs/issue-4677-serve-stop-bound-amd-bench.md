## Title
[Engine] Bounded speculative decode commit prevents parked snapshot rejection (AMD validation)
Issue: Resolves #4677

## Summary
Validates and provides benchmarks for the bounded speculative row commit policy (`serve_stop_bound`). In speculative decoding (`--spec N`), when the stop token was accepted mid-window, excess rows beyond the emitted output tokens were committed to the KV cache. The subsequent request turn detected a state mismatch against the emitted response, rejecting the parked conversation snapshot and forcing an expensive fallback to an earlier checkpoint (re-reading ~6% of the prompt).

Bounding committed rows strictly to what was emitted ensures the parked snapshot matches what the client received, eliminating snapshot rejections on multi-turn continuations.

## What changed
- `src/program/generate.cpp`:
  - Implemented `serve_stop_bound` bounding the accepted rows committed to the active sequence.
  - Added opt-out flag `STRATA_SERVE_STOP_BOUND=0` (enabled by default).
- `tests/core/serve_stop_bound_test.cpp`:
  - Added test suite evaluating 2,736 boundary edge cases comparing speculative commit bounds against the output loop.
- `CMakeLists.txt`:
  - Added executable target `serve_stop_bound_test`.

## Hardware Validation & Benchmark Results
- **Hardware Tested**: AMD Radeon RX 7600 XT 16 GB (`gfx1102`), AMD Ryzen 5 3600, 32 GB system RAM, CachyOS Linux (ROCm 6.2).
- **Model**: `Qwen3.8-Flash-Next Coder IQ1_M`, `--spec 4`, `--max-context 65536`.
- **Measured Results**:
  - **Snapshot rejection rate**: Dropped from ~25% (4 of 16 multi-turn requests rejecting snapshots) to **0% (0 rejections across 16 runs)**.
  - **Conversation cache hit rate**: Improved from 62.9% to **68.5%**, reducing re-read tokens per session by 94.4% (from 72 tokens down to 4 tokens).
  - **Throughput impact**: Decode throughput was completely neutral (24.7 tok/s before vs 24.7 tok/s after), while multi-turn agent response latency improved by 10.1%.
- **Test execution**:
  ```bash
  ninja -C build-hip serve_stop_bound_test
  ./build-hip/serve_stop_bound_test
  # Result: 2,736 cases passed cleanly.
  ```
- **Backend status**: Native HIP (`gfx1102`) compiled and validated. CPU policy logic is architecture-independent. CUDA and SYCL follow the same commit structure.
