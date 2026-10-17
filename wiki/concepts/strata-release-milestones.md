---
title: "Strata Release Milestones"
type: concept
description: "Key features and milestones across Strata releases up to v0.1.41"
status: active
tags: [releases, changelog, history, milestones]
created: 2026-10-05
updated: 2026-10-09
last_verified: 2026-10-09
---

# Strata Release Milestones

## Summary

Overview of major technical milestones achieved throughout Strata releases up to v0.1.41, including platform expansions, API additions, performance gains, and security hardenings.

## Key Facts

- **v0.1.41:** Added CPU prefill expert sharing (`STRATA_PREFILL_CPU_SHARE=auto`, 20%–34% prefill latency reduction on prompt chunks under 1,024 tokens on single NVIDIA GPUs); introduced opt-in switches for pinned stage buffers (`STRATA_STAGE_PIN=1`), chunked DeltaNet recurrence (`STRATA_GDN_CHUNKED`), Foresight swap slots (`STRATA_FS_SLOTS`), and residency-biased routing (`STRATA_ROUTE_RESIDENT`); hardened server concurrency with default HTTP listen backlog of 256.
- **v0.1.40 & v0.1.40.1–v0.1.40.4:** Added AMD Ryzen AI Max (Strix Halo, `gfx1151`) native support with unified memory sizing and shared-expert stream fork (`STRATA_SH_STREAM=1`); integrated multi-token router and catch-up optimizations in MTP drafter; expanded Intel Arc (SYCL) detection (B70, A750); added Prometheus/Grafana monitoring assets; prevented false tool call triggers inside markdown code blocks (`#1058`); resolved Pascal `sm_61` decode regression (`#1469`).
- **v0.1.39:** Added support for OpenAI Responses API (compatible with OpenAI Codex CLI), parallel batching decode, and experimental support for legacy GPUs.
- **v0.1.38:** Hardened security by restricting unauthenticated servers to localhost to protect against DNS rebinding and cross-site attacks; introduced tensor core KV cache quantization (`q4_0`).
- **v0.1.37:** Added engine watchdog to detect and recover from frozen inference processes without hanging the HTTP server; resolved AMD desktop VRAM budgeting on Windows.
- **v0.1.34–v0.1.36:** Introduced Windows AMD (HIP) support without manual compilation; released built-in Model Context Protocol (MCP) server; improved Q2_0 prompt evaluation speeds.
- **v0.1.30–v0.1.32:** Introduced support for Unsloth 4-bit models with NVMe streaming; optimized multi-GPU layer splitting and RDNA4 decode routines.

## Details

### Evolution Highlights

1. **Hardware & Backend Expansion:** Initial CUDA release expanded to Linux ROCm (HIP), Windows bundled HIP runtime, SYCL (Intel Arc B70/A750), AMD Strix Halo APU (`gfx1151`), and experimental Pascal/Volta paths.
2. **Protocol Compatibility & Telemetry:** Progressed from basic OpenAI `v1/chat/completions` to native Anthropic `v1/messages`, Model Context Protocol (MCP) tools, OpenAI Responses API, and Prometheus `/metrics` scraping with Grafana dashboards.
3. **Execution & Offloading Innovations:** From static CPU expert pools to adaptive GPU expert caching, speculative MTP drafting with prompt lookup, CPU prefill expert sharing, and session state persistence.
4. **Security Standards:** Enforced mandatory API keys for non-localhost network bindings, strictly blocking public access defaults to protect user machines.

## Related

- Engine: [Strata](../entities/strata.md)
- Models: [Strata Model Variants](../entities/strata-models.md)
- Architecture: [Expert Offloading and Speculation](expert-offloading-and-speculation.md)
- [Upstream v0.1.42 Fixes Integration Plan](../artifacts/upstream-v0-1-42-fixes-plan.md)

## Sources

1. GitHub Releases & commit history (`origin/main`, tags `v0.1.40` through `v0.1.41`) — verified 2026-10-09.
2. `docs/DETAILS.md` — read 2026-10-09.
3. `README.md` — read 2026-10-09.
