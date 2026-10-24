---
title: "Upstream Strata 0.2.4 Review and Hardware Evaluation (2026-10-24)"
type: artifact
description: "Hardware evaluation of Strata 0.2.4 (DeepSeek-V4.1-Flash) on RX 7600 XT (gfx1102), 32 GB RAM, and 274 GB disk; why it cannot run here"
status: active
tags: [upstream, release, review, deepseek, dsv41, hardware, sizing, rx7600xt]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Upstream Strata 0.2.4 Review and Hardware Evaluation (2026-10-24)

## Summary

Upstream published tag `v0.2.4` and hotfix `v0.2.4.1` on 2026-10-24. The release introduces `strata-dsv41` (`src/dsv41`), a dedicated engine port running **DeepSeek-V4.1-Flash** (40 layers, 384 experts, 15,360 total routed experts, and a 111 GB 4-bit Engram n-gram lookup table).

We conducted a complete feasibility evaluation against our machine's hardware specification:
- **GPU**: AMD Radeon RX 7600 XT (16 GB VRAM, RDNA3 `gfx1102`, ROCm 6.x)
- **RAM**: 32 GB DDR4 (31 GiB usable, 2.4 GiB free)
- **Storage**: 274 GB free on NVMe `/mnt/data`

**Evaluation Outcome**: Running DeepSeek-V4.1-Flash on this PC is **not viable**. It hits three insurmountable hardware bottlenecks: GPU architecture incompatibility, severe system RAM deficiency, and storage exhaustion.

## Hardware Comparison Matrix

| Resource / Constraint | Upstream v0.2.4 Minimum | Upstream Recommended | PC Current Specification | Status |
|---|---|---|---|:---:|
| **GPU Architecture** | NVIDIA RTX 30/40/50 OR **AMD RDNA4** (`gfx1200`/`gfx1201`) | 4x Radeon AI PRO R9700 | **AMD Radeon RX 7600 XT (`gfx1102`, RDNA3)** | ❌ Incompatible |
| **System RAM** | **46 GB minimum** | 64 GB+ | **32 GB (31 GiB usable)** | ❌ -14 GB to -32 GB |
| **Disk Storage** | **239 GB** (`IQ1_M 1.75bpw`) | 257 GB–274 GB | **274 GB free** on `/mnt/data` | ⚠️ Leaves ~35 GB (96% full) |
| **Decode Throughput** | 5–8 tok/s (12 GB GPU + 64 GB RAM + fast NVMe) | 31–69 tok/s (4x R9700) | **Estimated < 0.5–1.2 tok/s** (SSD thrashing) | ❌ Impractical |

## Detailed Technical Bottlenecks

### 1. GPU Architecture Incompatibility (No RDNA3 Binary)
Upstream release artifacts provide HIP binaries compiled exclusively for RDNA4 (`strata-dsv41-0.1.49-linux-x86_64-hip-rx9070.tar.gz`, targeting `gfx1200` and `gfx1201`). The engine's matrix-core acceleration kernels (`ds4_tqw.cuh`, `ds4_kernels.cu`) rely on RDNA4 WMMA i-quant prompt tiles (`STRATA_DS4_HIPK`). There is no precompiled binary for RDNA3 (`gfx1102`).

### 2. The 111 GB Engram RAM Exhaustion
DeepSeek-V4.1-Flash requires a 111 GB 4-bit Engram lookup table (`DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf`).
- On a 32 GB RAM system, this table cannot be cached in physical memory.
- Upstream requires $\ge$ 46–64 GB RAM so the active Engram entries and top experts remain cached.
- With 32 GB total RAM, every single generated token causes multiple random 4KB reads directly from the NVMe SSD. Generation speed collapses to under 1 token per second, creating severe disk wear and OS freezing.

### 3. Disk Storage Depletion
The smallest supported set (`ist-das-1.75bpw`, IQ1_M) requires 239 GB (121 GB model + 111 GB Engram + 8 GB DSpark drafter). Our drive has 274 GB free. Downloading and unpacking would leave only ~35 GB free (96% disk capacity), triggering `ENOSPC` failures during normal operations, checkpoints, and transcripts.

## Comparison Against Current Production Setup

| Attribute | Current Deployment (**Qwen3.8 Coder IQ1_M**) | Upstream v0.2.4 (**DeepSeek-V4.1-Flash**) |
|---|---|---|
| **Hardware Fit** | Optimal for 32 GB RAM + 16 GB VRAM | Exceeds RAM and storage capabilities |
| **Decode Speed** | **24.8–27.6 tok/s** (measured) | < 1.0 tok/s (estimated on 32 GB RAM) |
| **Prefill Speed** | **334.1 tok/s** (16K context record) | ~50–100 tok/s |
| **Vision Support** | Multimodal ViT active on RX 7600 XT | Vision requires additional VRAM overhead |
| **Context Window** | 65,536 tokens fully resident | Constrained by disk thrashing |

## Impact on Existing Qwen Setup

In release 0.2.4, the Qwen engine packages (`engine/strata`), web application, and Qwen model configurations are **completely unchanged (byte-for-byte identical to 0.2.3)**. DeepSeek-V4.1 was packaged as an independent engine (`strata-dsv41`). Upgrading the checkout to 0.2.4 offers zero improvements for Qwen3.8 while adding dead weight.

## Conclusion & Recommendation

Maintain the existing **Qwen3.8-Flash-Next Coder IQ1_M** deployment. It remains the fastest, most capable MoE configuration for this specific hardware envelope.

## Sources

1. Upstream release notes: `docs/release-notes-0.2.4.md`, `docs/release-notes-0.2.4.1.md`, and `docs/DEEPSEEK41.md` at git tag `v0.2.4.1`.
2. Host measurements: `rocm-smi` (16 GB VRAM `gfx1102`), `free -h` (31 GiB RAM), `df -h` (274 GB free).
3. Benchmark records: `bench/results/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/`.
