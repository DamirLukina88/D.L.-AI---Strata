# Ray: upstream syncs and benchmarks

How this fork follows upstream Strata releases, what was ported, and the community benchmark of 2026-11-01.

[← Back to the README](../README.md)

The inference engine is Strata, configured and optimized for AMD RDNA3 (ROCm/HIP). This fork last merged upstream
as a whole at v0.1.44.1 (2026-10-15). Later upstream releases are reviewed against this PC (AMD Ryzen 5 3600, 32 GB
RAM, Radeon RX 7600 XT 16 GB `gfx1102`, CachyOS, ROCm) and only the fixes that apply are ported by hand, so the engine
reads `0.1.44.1+0.2.12-fixes`. The reviews live in the shared memory store (project `strata`, pages named
`upstream-v0-2-*-review-*`); they are not part of this repository.

## Releases reviewed and ported

- **0.2.0-beta, 0.2.1 (2026-10-20):** reviewed, nothing merged.
- **0.2.2, 0.2.3 / 0.2.3.1 (2026-10-21 to 10-23):** crucial engine, vision and spec fixes ported, and 8-bit
  hyper-connection weights (`STRATA_HC_Q8=1`) enabled after an A/B benchmark.
- **0.2.5, 0.2.6 (2026-10-25):** CommonMark soft linebreaks, direct screenshot clipboard paste (`Ctrl+V`),
  window-level drag-and-drop, dynamic model load timeout scaling, safe shard removal guards,
  `require_messages(messages)` OpenAI-spec validation, 1-token health check speed guards, and stable GPU hardware
  telemetry IDs.
- **0.2.7 (2026-10-27)**, four fixes, engine `0.1.44.1+0.2.7-fixes`, each checked with tests and a short smoke test
  (no benchmark):
  - a failed read of the per-layer table no longer hangs the next request (#3602);
  - a checkpoint copy that runs out of memory is skipped instead of ending the engine (#3350);
  - no restore is attempted on a card too full to create its copy stream (#2409);
  - an MCP tool name written with `__` collapsed to `_` is read as the declared tool (#3796).
- **0.2.8, 0.2.9 (2026-10-29 to 10-31):** tool-call parser fixes and the parser code-fence fix ported; much of the
  rest is for Mac, DGX Spark, Intel, Strix Halo or the desktop app, which this install does not use.
- **0.2.10 (2026-11-03):** parser and server fixes first, then the HIP #4677 and #4350 engine fixes, with an A/B
  benchmark.
- **0.2.11 (2026-11-05):** server robustness ports and the Q5_0 dot precision fix in the C++/HIP engine, with a 4-leg
  paired A/B benchmark on the RX 7600 XT.
- **0.2.12 (2026-11-07):** the C++/HIP engine guards (MMQ row margin and Flag-B ordering), with a 4-leg A/B benchmark.
  Pull request #5477 (`GET /v1/models/{id}`) was submitted upstream and an AMD benchmark was posted to issue #4677.
- **0.2.13 (2026-11-09):** audited; nothing applies to this install and the release was skipped. Four small optional
  ports are noted.
- **0.2.14 / 0.2.14.1 (2026-11-15):** three server fixes ported: a request that ends early while the engine restarts
  no longer raises, `GGML_NO_BACKTRACE=1` keeps gdb out of a crashing engine or picture reader, and the server binds
  without a host-name lookup. Upstream's 0.1.60 engine (its own prompt kernels) was A/B'd against ours on this PC
  with the Coder IQ1_M: built here it read a 21,087-token prompt in 58.4 s against our 59.1 s and a 245-token prompt
  in 2.42 s against 2.12 s; upstream's prebuilt package was 3-6% slower on long prompts; output speed was the same
  within the run-to-run spread. The engine was not switched; both upstream builds are kept on the data disk for
  comparison with later releases. Also ported: the picture reader's start waits for READY or ERR and logs any other line
  instead of killing the reader on it (`4cce1ee4d`). Upstream's GPU-to-processor reader fallback (`c53e45a35`,
  `78eaaf1b0`) does not apply: this install's picture reader already runs on the processor.
- **0.2.15 (2026-11-16):** mostly fixes for upstream's desktop app, installer and Terminal; the engine stays 0.1.60.
  Ported: a declared boolean tool argument written `True` / `False` is the boolean (#5979). Not ported: the stop
  that refuses new requests (#6055; this server has no drain) and the monitor's MTP line (#5080; this engine does not
  report its drafter, so nothing would change).

## Community benchmark, 2026-11-01

An official community benchmark was run with `tools/strata_bench.py --long` against the live 64K context server:
- **Chat Speed & Latency**: 24.7 tok/s decode, 1.54 s time-to-first-token (10.1% latency improvement over baseline).
- **Prompt Prefill Throughput**: 308 tok/s at 4K, 337 tok/s at 16K, and 335 tok/s at 32K.
- **Agent Conversation Caching**: 68.5% cache hit rate with only 4 re-read tokens/session (94.4% reduction from 72
  tokens), delivering 27.5 tok/s decode across multi-turn sessions.

These numbers were measured with the GPU set to 2800 MHz / 198 W / -50 mV. After GPU crashes on 2026-11-14 the card
runs at 2500 MHz / 150 W / -50 mV, so they need a re-run (see [RAY_SPEED.md](RAY_SPEED.md)).
