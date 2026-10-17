---
title: "Expert Offloading and Speculative Decoding"
type: concept
description: "Tiered MoE offloading and speculative drafting mechanism in Strata"
status: active
tags: [architecture, moe, offloading, speculative-decoding, performance]
created: 2026-10-05
updated: 2026-10-09
last_verified: 2026-10-09
---

# Expert Offloading and Speculative Decoding

## Summary

Strata makes 125B parameter mixture-of-experts (MoE) models fit on consumer hardware through tiered offloading across VRAM, system RAM, and SSD, combined with parallel CPU/GPU execution, CPU prefill sharing, and multi-token speculative decoding.

## Key Facts

- The target model contains 24,576 fine-grained experts, of which only 10 are activated per generated token.
- GPU VRAM caches the most frequently activated experts dynamically, alongside dense mixers, attention layers, routers, shared experts, and KV cache.
- System RAM holds all 24,576 experts pinned in memory; the CPU computes un-cached experts concurrently with the GPU using AVX2 or AVX-512 kernels. *(inferred)*
- **CPU Prefill Expert Sharing (`STRATA_PREFILL_CPU_SHARE`):** In v0.1.41+, short prompt chunks (<1,024 tokens) dynamically share infrequently routed experts with the idle CPU decoding pool, reducing prompt latency by 20%–34% on single NVIDIA GPUs.
- Speculative decoding combines an internal Multi-Token Prediction (MTP) layer drafting up to 3 tokens with context prompt lookups drafting up to 5 tokens, yielding 1.6x–1.8x generation speedups without altering output quality.
- Drafter execution features multi-token routing, rejected row KV-skipping, and fused RMSNorm + RoPE for reduced speculative overhead.
- Prefill processes long context in chunks up to 8,192 tokens while streaming downstream layer weights over PCIe.

## Details

### Memory Tiering Strategy

| Hardware Tier | Stored Elements | Access Pattern |
| --- | --- | --- |
| **GPU VRAM** | Attention & DeltaNet mixers, routers, shared experts, output heads, MTP draft layer, adaptive expert cache (~700 experts per extra GB VRAM). | Direct high-bandwidth tensor operations. |
| **System RAM** | Complete expert pool (all 24,576 experts). Low-RAM mode can retain only offloaded experts. | CPU in-place computation simultaneous with GPU kernel execution; prefill expert sharing. |
| **SSD (NVMe)** | 28.8 GB n-gram table. | Read selectively per token through OS page cache. |

### Speculative Drafting

1. **MTP Drafting:** The model's built-in MTP layer generates provisional tokens (typically 2.4 to 3.2 accepted per forward pass). In v0.1.40+, the drafter implements multi-token combine and skips KV allocation for rejected draft tokens.
2. **Prompt Lookup:** Used when outputs echo existing prompt context (e.g. code modifications, verbatim citations), drafting up to 5 tokens and boosting code edit throughput by 6%–11%.

## Related

- Engine: [Strata](../entities/strata.md)
- Models: [Strata Model Variants](../entities/strata-models.md)
- Sizing Decisions: [Model Selection and Hardware Budgeting](../decisions/model-selection-and-hardware-budget.md)
- Releases: [Strata Release Milestones](strata-release-milestones.md)

## Sources

1. `docs/HOW_IT_WORKS.md` — read 2026-10-05.
2. `docs/DETAILS.md` — read 2026-10-09.
3. `README.md` — read 2026-10-09.
