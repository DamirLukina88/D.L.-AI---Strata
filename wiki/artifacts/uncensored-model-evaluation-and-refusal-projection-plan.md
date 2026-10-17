---
title: "Uncensored Model Evaluation and Refusal-Direction Projection"
type: artifact
description: "Hardware evaluation of community uncensored MoE models on 32 GB RAM / 16 GB VRAM and configuration of Strata native refusal-direction projection"
status: active
tags: [uncensored, abliterated, control-vector, hardware, ram, vram, strata]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Uncensored Model Evaluation and Refusal-Direction Projection

## Summary

Evaluated community-provided uncensored/abliterated Qwen3.8-Flash-Next derivatives (such as `jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata` and `orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF`) against host hardware constraints (AMD Ryzen 5 3600, 32 GB system RAM, AMD Radeon RX 7600 XT with 16 GB VRAM). Implemented Strata's built-in dynamic refusal-direction projection (`--cvec-mode project`) across layers 4–44 on both deployed models (`Q2_0` and `Coder IQ1_M`) to achieve uncensored/unrefused inference within memory limits.

## Context & Hardware Evaluation

### 1. Community Uncensored Models vs. Host Budget
- **Models Inspected:**
  - `jimmy31chen/RVN-Qwen3.8-Flash-Next-Abliterated-Uncensored-IQ3_S-Strata` (83 GiB merged single-file GGUF + pack)
  - `orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF` (IQ3_XXS, 85.2 GiB)
- **Host Hardware:**
  - 32 GB physical DDR4 RAM
  - 16 GB GDDR6 VRAM (RX 7600 XT, `gfx1102`)
  - 273 GB free NVMe storage (`/mnt/data`)
- **Evaluation Finding:**
  - Unpruned community 125B MoE models retain all 512 experts. The Strata expert arena alone requires ~49.8–50 GiB resident memory in system RAM, demanding 64 GB to 128 GB of host RAM and 30–32 GB VRAM.
  - Attempting to run `IQ3_S` or `IQ3_XXS` on a 32 GB system causes immediate out-of-memory kernel termination (OOM kill) or severe swap thrashing.
  - No 256-expert pruned `IQ1_M` community abliterated GGUFs currently exist.

### 2. Strata Native Refusal-Direction Projection
Strata ships with an engine-native control vector designed specifically for Qwen3.8-Flash-Next:
- **Vector:** `data/experimental-speed-projection/Qwen3.8-Flash-Next-experimental-speed-projection.gguf` (480 KB).
- **Mechanism:** Computes \(h \leftarrow h - (h \cdot v) v\) across layers 4–44 per-layer on the residual stream, mathematically subtracting the refusal direction vector.
- **Resource Footprint:** 480 KB disk/memory overhead; ~0.2–0.4% compute cost per token; fully operable on both `Q2_0` and `Coder IQ1_M`.

## Implementation

Applied the following flags to `"args"` in `/mnt/data/Strata/strata-q2_0.json` and `/mnt/data/Strata/strata-coder-iq1_m.json`:

```json
"--control-vector-scaled",
"/mnt/data/Strata/data/experimental-speed-projection/Qwen3.8-Flash-Next-experimental-speed-projection.gguf:1.0",
"--control-vector-layer-range",
"4",
"44",
"--cvec-mode",
"project",
"--cvec-dir",
"per-layer"
```

Restarted `strata-server.service` under systemd user units to activate the steered projection.

## Related

- Sizing Decisions: [Model Selection and Hardware Budgeting](../decisions/model-selection-and-hardware-budget.md)
- Deployment: [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)
- Models: [Strata Model Variants](../entities/strata-models.md)

## Sources

1. `data/experimental-speed-projection/README.md` — Strata repository.
2. `docs/DETAILS.md` ("Experimental speed projection") — Strata documentation.
3. User session — 2026-10-11.
