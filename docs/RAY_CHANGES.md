# Ray: upstream syncs and benchmarks

How this fork follows upstream Strata releases, what was ported, and the community benchmark of 2026-11-01.

[← Back to the README](../README.md)

The inference engine is Strata, configured and optimized for AMD RDNA3 (ROCm/HIP). Upstream
Strata releases are continuously evaluated and synced with each release. Upstream 0.2.0-beta and 0.2.1 were
reviewed on 2026-10-20 ([review](../wiki/artifacts/upstream-v0-2-releases-review-2026-10-20.md)). From 0.2.2 and 0.2.3/0.2.3.1,
crucial engine, vision, and spec fixes were ported alongside enabling 8-bit hyper-connection weights (`STRATA_HC_Q8=1`)
after an A/B benchmark ([review](../wiki/artifacts/upstream-v0-2-3-review-2026-10-23.md)). On 2026-10-25, **v0.2.5** and
**v0.2.6** were synchronized: CommonMark soft linebreaks, direct screenshot clipboard paste (`Ctrl+V`), window-level
drag-and-drop, dynamic model load timeout scaling, safe shard removal guards, `require_messages(messages)` OpenAI-spec
validation, 1-token health check speed guards, and stable GPU hardware telemetry IDs
([v0.2.5 walkthrough](../wiki/artifacts/strata-v0-2-5-sync-and-ergonomics-walkthrough.md),
[v0.2.6 & tools walkthrough](../wiki/artifacts/davinci-cst-ipc2152-wargaming-and-v026-sync-walkthrough.md),
[system audit](../wiki/artifacts/full-workstation-audit-and-verification-2026-10-25.md)). On 2026-10-27, four
**v0.2.7** fixes were ported into engine `0.1.44.1+0.2.7-fixes`:
- a failed read of the per-layer table no longer hangs the next request (#3602);
- a checkpoint copy that runs out of memory is skipped instead of ending the engine (#3350);
- no restore is attempted on a card too full to create its copy stream (#2409);
- an MCP tool name written with `__` collapsed to `_` is read as the declared tool (#3796).

Each was checked with tests and a short smoke test; no benchmark was run
([review](../wiki/artifacts/upstream-v0-2-7-review-2026-10-27.md)). On 2026-11-01, an official community benchmark was run with `tools/strata_bench.py --long` against the live 64K context server with Two-Tier Wiki Handoff active ([report](../wiki/artifacts/strata-benchmark-2026-11-01.md)):
- **Chat Speed & Latency**: 24.7 tok/s decode, 1.54 s time-to-first-token (10.1% latency improvement over baseline).
- **Prompt Prefill Throughput**: 308 tok/s at 4K, 337 tok/s at 16K, and 335 tok/s at 32K.
- **Agent Conversation Caching**: 68.5% cache hit rate with only 4 re-read tokens/session (94.4% reduction from 72 tokens), delivering 27.5 tok/s decode across multi-turn sessions.

