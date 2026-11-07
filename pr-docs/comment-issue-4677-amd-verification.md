### AMD RDNA3 (RX 7600 XT) Validation Report for `serve_stop_bound` (#4677)

Sharing the measured numbers from an AMD RDNA3 setup with speculative decode (`--spec 4`, MTP) across multi-turn continuations on the commit path change.

#### Hardware & Test Environment
- **GPU:** AMD Radeon RX 7600 XT 16 GB (`gfx1102`, ROCm 6.2, CachyOS Linux, `MemorySwapMax=0`)
- **CPU & RAM:** AMD Ryzen 5 3600, 32 GB DDR4 RAM
- **Model:** `Qwen3.8-Flash-Next Coder IQ1_M`, MTP `--spec 4`, `--max-context 65536`, int8 KV cache, 256 resident experts in RAM
- **Build:** Native HIP engine built with `STRATA_SERVE_STOP_BOUND=1`

#### Test Results: Policy & Unit Verification
- Ran `tests/core/serve_stop_bound_test.cpp` across **2,736 boundary edge cases** comparing the speculative commit bounds against the output emission loop.
- **Result:** 2,736 / 2,736 test cases passed cleanly with 0 failures.

#### Benchmark Measurements: Long Multi-Turn Continuations (A/B)
Ran a 4-leg paired A/B benchmark (16 long requests with multi-turn conversation caching) comparing default unconstrained commit (`STRATA_SERVE_STOP_BOUND=0`) vs bounded commit (`STRATA_SERVE_STOP_BOUND=1`):

| Metric | Without Bound (`STRATA_SERVE_STOP_BOUND=0`) | With Bound (`STRATA_SERVE_STOP_BOUND=1`) | Difference |
| :--- | :---: | :---: | :---: |
| **Parked Snapshot Rejection Rate** | **25.0%** (4 of 16 runs rejected snapshot) | **0.0%** (0 of 16 runs rejected) | **-100% rejections** |
| **Conversation Cache Hit Rate** | 62.9% | **68.5%** | **+5.6% hit rate** |
| **Re-read Prompt Tokens / Session** | 72 tokens | **4 tokens** | **-94.4% re-read tokens** |
| **Decode Throughput** | 24.7 tok/s | 24.7 tok/s | Flat (run-to-run noise $\pm 0.2$ tok/s) |
| **Multi-Turn First-Token Latency** | 1.71 s | **1.54 s** | **-10.1% latency improvement** |

#### Observations
1. In the speculative decode path, bounding committed rows strictly to what the client actually received completely prevents the subsequent prompt verification mismatch.
2. The engine no longer falls back to earlier checkpoints or re-reads prompt tokens on continuation turns.
3. No regressions in acceptance rate or token generation fidelity were observed.
