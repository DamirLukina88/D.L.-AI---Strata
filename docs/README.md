# Documentation

[← Back to the README](../README.md)

## Ray (this fork)

| Page | What's in it |
| :--- | :--- |
| [RAY_FEATURES](RAY_FEATURES.md) | What Ray does: face and voice, the coding agent, memory, tools and MCP servers |
| [RAY_SETUP](RAY_SETUP.md) | Installing the fork, the secrets file, the services, every command |
| [RAY_SPEED](RAY_SPEED.md) | Measured speed and the settings behind each step |
| [RAY_CHANGES](RAY_CHANGES.md) | Which upstream releases were reviewed and ported |

## Upstream Strata docs that apply to this PC (AMD RX 7600 XT, Linux, ROCm)

| Page | What's in it |
| :--- | :--- |
| [INSTALL](INSTALL.md), [AI_SETUP](AI_SETUP.md), [TROUBLESHOOTING](TROUBLESHOOTING.md) | Installing and fixing the engine |
| [AMD_HIP](AMD_HIP.md) | The HIP backend: building and validating on Radeon |
| [HOW_IT_WORKS](HOW_IT_WORKS.md), [DETAILS](DETAILS.md), [paper](paper/Strata-Paper.pdf) | How the engine works, every setting and measured number |
| [MODELS](MODELS.md), [MCP_SERVER](MCP_SERVER.md), [COMMUNITY_BENCHMARKS](COMMUNITY_BENCHMARKS.md), [TEST_REQUESTS](TEST_REQUESTS.md) | Models, the engine's MCP server, benchmark rules |
| [EXCHANGE_ROTATION](EXCHANGE_ROTATION.md), [KV_PREFETCH](KV_PREFETCH.md), [PROMPT_CACHE_TAIL](PROMPT_CACHE_TAIL.md), [MESSAGE_BOUNDARY_CACHE](MESSAGE_BOUNDARY_CACHE.md), [LOGIT_BIAS](LOGIT_BIAS.md), [BATCHING](BATCHING.md), [STATE_SNAPSHOT_BF16](STATE_SNAPSHOT_BF16.md) | Engine features that work on any card |
| [IMAGES](IMAGES.md), [LLAMA_SWAP](LLAMA_SWAP.md) | Optional: image generation, running behind llama-swap |

## Upstream docs for hardware or models this PC does not have

Kept because upstream's installer and tools link to them, and because moving them would make every upstream merge
conflict. Skip them unless the hardware changes.

- **Intel and Mac:** [INTEL](INTEL.md), [INTEL_ARC](INTEL_ARC.md), [A770_SPEED_SPEC](A770_SPEED_SPEC.md), [MAC](MAC.md)
- **More than one GPU:** [MULTI_GPU](MULTI_GPU.md), [SECOND_GPU](SECOND_GPU.md), [DISJOINT_EXPERT_CACHE](DISJOINT_EXPERT_CACHE.md)
- **NVIDIA only:** [NVIDIA_V100](NVIDIA_V100.md), [NVFP4](NVFP4.md), [BATCHED_DMA](BATCHED_DMA.md),
  [VRAM_ELASTIC](VRAM_ELASTIC.md), [MMVQ_IL_TABLE](MMVQ_IL_TABLE.md), [OLDER_GPUS](OLDER_GPUS.md)
- **AMD APU (Strix Halo):** [STRIX_HALO](STRIX_HALO.md); **7900 XTX numbers:** [AMD_HIP_PERFORMANCE](AMD_HIP_PERFORMANCE.md)
- **Larger quantizations and models that need much more RAM:** [UNSLOTH_Q4](UNSLOTH_Q4.md),
  [UNSLOTH_Q6](UNSLOTH_Q6.md), [QUANTS](QUANTS.md), [ORCA](ORCA.md), [ORCA_Q4_K_S](ORCA_Q4_K_S.md)
- **Experiments measured on other hardware:** [RESEARCH_RUNS](RESEARCH_RUNS.md), [PREFILL_HEAD_ALIAS](PREFILL_HEAD_ALIAS.md)
