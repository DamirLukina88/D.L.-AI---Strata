---
title: "Strata Model Variants"
type: entity
description: "Model quantizations, specialized variants, and memory footprints supported by Strata"
status: active
tags: [models, quantization, qwen, variants]
created: 2026-10-05
updated: 2026-10-09
last_verified: 2026-10-09
---

# Strata Model Variants

## Summary

Strata primarily serves Qwen3.8-Flash-Next across several specialized quantizations and pruned derivatives, optimizing trade-offs between parameter retention, reasoning speed, and host memory requirements.

## Key Facts

- **Coder (IQ1_M):** Removes half of the 512 total experts (256 experts retained). Shard 1 is 29.6 GB, enabling full execution on 32 GB RAM systems. Achieves 91% of full model SWE-bench Verified score. Shows degraded performance on non-English/CJK text. *(inferred)*
- **Swift 1.5:** Fine-tuned variant designed for reduced reasoning latency (shorter internal chain-of-thought) while retaining answer accuracy.
- **Qwen Quantizations (Q2_0, IQ2_XS, IQ3_XXS, IQ3_S):** Retain all experts. Q2_0 provides the fastest prefill and generation; IQ2_XS is the recommended balance for 48 GB–64 GB RAM; IQ3_S offers highest fidelity.
- **Unsloth 4-bit (UD-IQ4_XS, UD-Q4_K_XL):** UD-IQ4_XS is a regular choice (recommended for 96 GB+ RAM systems or AMD Strix Halo unified memory); UD-Q4_K_XL remains experimental (111 GB download) and streams non-cached experts directly from NVMe SSD on hosts under 80 GB RAM.

## Details

### Model Sizing Summary

| Variant | Precision / Size | Shard 1 Download | Recommended Host RAM | Primary Use Case |
| --- | --- | --- | --- | --- |
| **Coder** | IQ1_M | ~29.6 GB | 32 GB | Code generation, agent tasks |
| **Q2_0** | 2-bit standard | ~55 GB | 48 GB | Maximum throughput |
| **IQ2_XS** | 2-bit importance matrix | ~58 GB | 48 GB – 64 GB | General conversational & reasoning |
| **IQ3_S** | 3-bit importance matrix | ~70 GB | 64 GB – 96 GB | Complex multi-step reasoning |
| **Unsloth UD-IQ4_XS** | ~4-bit | ~94 GB | 96 GB+ (or Strix Halo unified / NVMe SSD) | High accuracy |
| **Unsloth UD-Q4_K_XL** | 4-bit dynamic | ~111 GB | 96 GB+ (or NVMe SSD offload) | Experimental maximum fidelity |

## Related

- Engine: [Strata](strata.md)
- Architecture: [Expert Offloading and Speculation](../concepts/expert-offloading-and-speculation.md)
- Decisions: [Model Selection and Hardware Budgeting](../decisions/model-selection-and-hardware-budget.md)
- Releases: [Strata Release Milestones](../concepts/strata-release-milestones.md)

## Sources

1. `docs/MODELS.md` — read 2026-10-09.
2. `README.md` — read 2026-10-09.
3. `docs/DETAILS.md` — read 2026-10-09.
4. `docs/STRIX_HALO.md` on `origin/main` (v0.1.41; not in the local checkout, which is at 0.1.39) — read 2026-10-09.
