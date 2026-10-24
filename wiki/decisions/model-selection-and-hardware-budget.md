---
title: "Model Selection and Hardware Budgeting"
type: decision
description: "Hardware requirements and sizing heuristics for Strata deployments"
status: active
tags: [hardware, vram, ram, sizing, deployment]
created: 2026-10-05
updated: 2026-10-09
last_verified: 2026-10-09
---

# Model Selection and Hardware Budgeting

## Summary

Deciding which model variant and quantization size to deploy in Strata is dictated primarily by available system RAM, while GPU VRAM determines KV cache headroom and expert cache capacity.

## Key Facts

- Minimum GPU VRAM requirement is 12 GB. Consumer cards with 16 GB to 24 GB VRAM substantially improve token generation rates because each additional gigabyte holds ~700 experts in the GPU expert cache.
- System RAM determines the upper limit on un-pruned model execution: 32 GB takes the Coder IQ1_M with a 12-16 GB card, but with a 24 GB card Q2_0 and IQ2_XS also run in the low-RAM mode (setup picks it; per `docs/MODELS.md` the better pick for general use); 48 GB enables Q2_0 and IQ2_XS; 64 GB supports IQ2_XS and IQ3_XXS; 96 GB+ supports IQ3_S. *(inferred)*
- NVMe SSD storage is strongly recommended for holding the 28.8 GB n-gram table and model weights (35 GB–111 GB depending on model).

## Details

### Context

Standard server-scale deployments of 125B MoE models require enterprise GPUs with hundreds of gigabytes of VRAM. Consumer PCs have heterogeneous resources (e.g. 12–16 GB GPU VRAM and 32–64 GB system RAM). A decision matrix ensures stability and prevents out-of-memory kernel termination.

### Options Considered

1. **Full Expert Models (IQ2_XS / IQ3_S) on 32 GB RAM:** Exceeds physical RAM capacity without severe NVMe paging penalties, causing system freezing.
2. **Coder (IQ1_M) on 32 GB RAM:** Retains 256 active experts; shard 1 requires 29.6 GB, fitting cleanly into 32 GB system RAM while running comfortably on 12–16 GB VRAM GPUs.
3. **Unsloth 4-bit (UD-IQ4_XS):** Demands 80 GB+ RAM, AMD Strix Halo unified memory, or high-speed NVMe disk streaming; produces lower throughput (7–8.5 tokens/s) on restricted memory.

### Why This Selection

- **32 GB RAM:** Deploy **Coder (IQ1_M)**; with a 24 GB card, **Q2_0** or **IQ2_XS** in the low-RAM mode (corrected 2026-10-09).
- **48 GB RAM:** Deploy **IQ2_XS** (or Q2_0 for maximum generation speed).
- **64 GB RAM:** Deploy **IQ2_XS** (recommended default) or **IQ3_S**.
- **96 GB+ RAM / Strix Halo Unified:** Deploy **IQ3_S** or **UD-IQ4_XS**.

## Related

- Models: [Strata Model Variants](../entities/strata-models.md)
- Engine: [Strata](../entities/strata.md)
- Deployment: [RX 7600 XT CachyOS Deployment](rx-7600-xt-cachyos-deployment.md)
- Artifact: [Uncensored Model Evaluation and Refusal-Direction Projection](../artifacts/uncensored-model-evaluation-and-refusal-projection-plan.md)
- Artifact: [Upstream Strata 0.2.4 Review and Hardware Evaluation](../artifacts/upstream-v0-2-4-review-2026-10-24.md)

## Sources

1. `docs/AI_SETUP.md` — read 2026-10-09.
2. `docs/MODELS.md` — read 2026-10-09 ("Pick by RAM" table and low-RAM mode).
3. `README.md` — read 2026-10-09.
