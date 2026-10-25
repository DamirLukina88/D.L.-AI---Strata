---
title: "RX 7600 XT CachyOS Deployment"
type: decision
description: "Deployment configuration for the RX 7600 XT on CachyOS, and how to start and stop it (strata.sh)"
status: active
tags: [deployment, hardware, cachyos, amd, gfx1102, coder]
created: 2026-10-05
updated: 2026-10-21
last_verified: 2026-10-09
---

# RX 7600 XT CachyOS Deployment

## Summary

Strata was successfully deployed on CachyOS Linux equipped with an AMD Ryzen 5 3600 CPU, 32 GB of system RAM, and an AMD Radeon RX 7600 XT GPU (16 GB VRAM, `gfx1102`). The installation resides on `/mnt/data/Strata` with model data on `/mnt/data/Strata-data`, serving Qwen3.8-Flash-Next Coder (`IQ1_M`).
- 2026-10-13: Measured memory budget of the coder-iq1_m config (v0.1.43.1, model loaded). VRAM (16.0 GiB card): the expert cache is sized at load so that `--vram-reserve-mib 2560` stays free; the engine took ~13.5 GiB (expert cache 7.12 GiB / 3722 slots, dense + projection weights ~3.4 GiB, MTP draft 0.86 GiB, Q5_K head 0.5 GiB, draft head 0.2 GiB) and logged 2.47 GiB free; during use the card sat at 14.9 / 16.0 GiB including the desktop. RAM: engine RSS 22.3 GiB = 19.61 GiB pageable resident experts (STRATA_RESIDENT_PIN=0) + conversation cache up to 2 GiB (`--conversation-cache-mib 2048`, 4 slots) + ~0.7 GiB other; memory guard floor 2560 MiB; system had 3.6 GiB available and 3 GiB of swap in use. Levers: lower `--vram-reserve-mib` (more cache, less headroom for long prompts), `--conversation-cache-mib`, STRATA_RESIDENT_PIN.
- 2026-10-13: The user had desktop freezes from too little free memory (3.6 GiB RAM available, swap in use, card at 14.9/16 GiB). Margins raised: `--resident-experts` replaced by `--resident-budget-gib 15` (hottest 15 of 17.3 GiB of non-GPU experts in RAM, the rest read from the pack on demand), `--conversation-cache-mib` 2048 -> 1024, `--vram-reserve-mib` 2560 -> 3584 (coder and q2_0 configs), and `MemoryHigh=20G` on strata-server.service (above it the engine is reclaimed/swapped, the desktop is not; the memory guard now reports source: cgroup, limit 20.0 GiB). Result with the model loaded: server cgroup 17.5 GiB, MemAvailable 9.9 GiB, VRAM 13.9/16.0 GiB (3.5 GiB free at load; expert cache 3198 slots / 6.12 GiB). Backups of the previous configs and unit: ~/.config/dl-ai/backup-20261013/*.before-margin.*
- 2026-10-13 (final, supersedes the margin bullet above): Root cause of the freezes and slowdowns: with `STRATA_RESIDENT_PIN=0` the 19.6 GiB of resident experts are ordinary pageable memory, and CachyOS's `vm.swappiness=150` pushed 8-10 GiB of them into zram even with ~10 GiB RAM free; the engine then stalled on swapped experts (GPU waits up to 14 s, three SIGABRT core dumps). Fix: `MemorySwapMax=0` on strata-server.service (the engine never swaps; the kernel drops file cache or swaps other apps). Pinning (STRATA_RESIDENT_PIN=1) is not possible without root: the user manager's memlock hard limit is 8 MiB.
- Tried and rejected the same day: `MemoryHigh=20G/22G` (the cgroup counts the file cache of expert reads, so the engine thrashed against the ceiling: 128k/94k throttle events, a 468 s stall) and `--resident-budget-gib 15` (frees ~5 GiB but the engine stalled 355 s reading experts from the pack mid-prompt and 16K prompts fell to ~242 tok/s).
- Final config: `--resident-experts` (all in RAM), `--vram-reserve-mib 3584`, `--conversation-cache-mib 1024`, `MemorySwapMax=0`. Bench: chat 17.9 tok/s (peak 30.2), chat TTFT 1.87 s, 4K 272.5 tok/s, 16K 291.1 tok/s (best recorded), agent decode 20.2 tok/s, agent TTFT 12.5 s, 0 failures, 0 MiB engine swap; MemAvailable minimum during the bench 2.8 GiB, engine cgroup peak 25.4 GiB (incl. file cache). If the desktop still runs short: more RAM is the real fix; system-level options need sudo (DefaultLimitMEMLOCK for pinning, lower vm.swappiness).

- 2026-10-13 (evening): engine rebuilt with 13 upstream open PRs merged (see [Upstream Open PR Review (2026-10-13)](../artifacts/upstream-open-prs-review-2026-10-13.md)). Both configs gained `--session-state-codec bf16` (parked conversations at about half the bytes, no throughput change); `--conversation-cache-park-gain` and `--drop-file-cache` were benched and left off. Same-day bench with the final config: 4K 261.8, 16K 288.9 tok/s, agent TTFT 12.84 s.

- 2026-10-13 (evening): `STRATA_HIP_WMMA=1` added to the coder config's `env`: prompt reading +12.5% (4K 294.6, 16K 324.9 tok/s), agent first token 11.46 s, decode flat, answers unchanged in a temperature-0 check. Details: [Upstream Fork Review (2026-10-13)](../artifacts/upstream-forks-review-2026-10-13.md).
- 2026-10-13: Prompt-read hangs (`no progress for 60 s ... reading the prompt`, engine abort, exit -6) analysed from every stall report since 2026-10-10.
  - **Coder IQ1_M:** all 6 hangs (10-10 to 10-13 13:59) had 4.4-14.8 GiB of the engine in swap. The host was idle, the CPU expert workers asleep and no thread in disk wait, while a GPU step waited on swapped-out memory. There have been none since `MemorySwapMax=0` (14:02): about 2.5 h of benches, 0 hangs, engine VmSwap 0 kB. This is solved; keep `MemorySwapMax=0`.
  - **q2_0:** 4 hangs with almost no swap (0-226 MiB) but 6.7-9.9 million major page faults: its 38 GB of experts are mapped from the SSD on 32 GB RAM. One prompt layer sat 98-220 s with the host idle, no disk wait and the GPU done within 2 ms, after the file-tier grace (`STRATA_WATCHDOG_IO_S`, 600 s, only while reads continue) ran out. That looks like a real stall in the disk-bound path, not just slowness. No fix here: q2_0 needs about 48-64 GB RAM on this PC. The closest upstream reports are issues #2267 and #1569 (exit -6 on AMD).
  - The watchdog itself (`src/program/generate.cpp`, the issue #29 thread) worked as designed: grace while the file tier is read, abort after 10 s without reads.

- 2026-10-13 (late): Engine 0.1.44 deployed (main `9d614675`). Both configs gained `"STRATA_COMMIT_BATCH": "0"` in `env`: 0.1.44's batched commit cost ~3% prompt speed on gfx1102. Final bench: 4K 291.8, 16K 327.4 tok/s, agent first token 11.49 s, agent decode 28.5 tok/s. Do not run `./setup.sh` / `update.sh` here (they rebuild the HIP engine with their own flags). Details: [Strata v0.1.44 Merge](../artifacts/strata-v0-1-44-merge.md).

- 2026-10-15: Engine 0.1.44.1 deployed (main `84059f5e`), merged with no conflicts; `STRATA_COMMIT_BATCH=0` kept. Details: [Strata v0.1.44 Merge](../artifacts/strata-v0-1-44-merge.md).

- 2026-10-16: Measured benchmark suite on v0.1.44.1 (`79e27070`). Chat decode 24.0 tok/s, chat TTFT 1.71 s (-9.5%), 4K prompt 302.3 tok/s (+2.4%), 16K prompt record 332.1 tok/s (+0.3%), agent turn TTFT 11.27 s (-2.0%), cache hit 68.5%. Details: [Strata v0.1.44.1 Benchmark Report (2026-10-16)](../artifacts/strata-benchmark-2026-10-16.md).

- 2026-10-13 (night): Coding-agent settings for Coder IQ1_M.
  - Shared Chat settings (which the CLI follows): effort high (the template's xhigh, the level the Coder card's SWE-bench 75.6 / LiveCodeBench 86.3 were measured at), temperature 0.6, top_p 0.95, top_k 20, max tokens auto, no seed, no penalties.
  - `strata-coder-iq1_m.json` gained a `"sampling"` fallback with the same values (so a request with no fields never runs greedy, which Qwen advises against with thinking), `"reasoning_close_retry": true` (#1053, a turn that ends inside its thinking gets its answer) and `"tool_call_recovery": true`.
  - Backup: `~/.config/dl-ai/backup-20261013/strata-coder-iq1_m.json.before-agent-settings`.
  - The experimental speed projection's effect on coding quality is unmeasured.

- 2026-10-17: Upstream v0.1.45 evaluation on RX 7600 XT (`gfx1102`):
  - **rocBLAS Tuning vs RDNA3 WMMA:** Upstream commit `57c95d5f` (`tune_rocblas`) applies exclusively to older RDNA2 cards (`gfx103x`) lacking `hipBLASLt`. On our RDNA3 `gfx1102`, prompt GEMMs natively run on hardware **WMMA matrix cores** (`wmma_gemm.cu` and `STRATA_HIP_WMMA=1`) and `hipBLASLt`, delivering +12.8% to +16.6% faster prefill over non-tensor fallback. See [Component 1 WMMA Hardware Validation Report](../artifacts/v0-1-45-component-1-wmma-hardware-validation-report.md) and [Upstream v0.1.45 Evaluation Plan](../artifacts/upstream-v0-1-45-evaluation-and-benchmark-plan.md).
  - **Evaluation Targets:** Evaluating HIP Tiled QSA Scorer (`STRATA_SELECT_SIMT=1`), automatic thinking budget protection (`#984`), and Prompt Tokenizer prefix caching (`#567`).
  - **Component 2 Ported & Verified:** Upstream commit `4f21be87` ported the FP32 tiled QSA scorer to HIP. On `gfx1102`, `STRATA_SELECT_SIMT=1` activates tile geometry `32/64/32/4`, delivering 3.38x to 5.87x microsecond speedups in block scoring across 4K–131K contexts with 100% selection parity and passing the FP64 accuracy gate. See [Component 2 FP32 Tiled QSA Scorer Report](../artifacts/v0-1-45-component-2-simt-qsa-scorer-report.md).
  - **Component 3 Ported & Verified:** Upstream commits `d0e990ba` and `194c2688` implemented automatic thinking budget protection (`#984`), reserving &ge;25% of `max_tokens` (floor 512) for the answer when no budget is specified, and mapping Anthropic `thinking.budget_tokens`. Verified via 38 unit tests (100% pass) and live dual-API calls. See [Component 3 Thinking Budget Protection Report](../artifacts/v0-1-45-component-3-thinking-budget-protection-report.md).
  - **Local-Only Policy:** All pre-evaluation snapshots saved to `/mnt/data/Strata-data/local_backups/v145_eval/`; zero git commits, branches, or tags created.
  - **Piper TTS & STT Voice Features:** 20 US Piper neural voices integrated via Speech Dispatcher and gated for STT-only auto-speak. Details: [Desktop Piper Voice Switching and STT-Only Auto-Speak Gating](desktop-piper-voice-switching-and-stt-auto-speak.md).
- 2026-10-20: **`--max-context` stays at 65,536.** The user approved testing a larger window with abort rules: VRAM free at load under 1,024 MiB, MemAvailable under 1,536 MiB during the tests, any engine error or warning, or decode more than 3% slower, each meaning revert. Every larger size loaded in about 42 s with 3,498 MiB of VRAM free, but the engine warned that part of the prompt path's experts no longer fit in RAM (`FileExpertSource: WARNING: N of ~1732 lendable slots will read their experts from the pack during a long prompt; expect a slower prompt read on 50K+ token prompts (one measurement: 18% uncovered cost 26%)`, the others "read from the file when lent: not enough RAM for them"):

  | `--max-context` | Lendable slots read from the pack | MemAvailable after load |
  |---|---|---|
  | 65,536 | 0 of 1,733 (all kept in RAM) | — |
  | 73,728 | 79 of 1,732 (5%) | 4,284 MiB |
  | 81,920 | 190 of 1,731 (11%) | 4,279 MiB |
  | 98,304 | 570 of 1,732 (33%) | 4,763 MiB |

  So **system RAM, not VRAM, limits the context** on this 32 GB PC: the larger KV cache takes RAM from the resident experts, and long prompts would then read experts from the SSD. Same-day 65,536 baseline (`tools/strata_bench.py --long`): chat decode 24.6, agent decode 27.7 tok/s, prompt 4K 293.9 / 16K 334.5 / 32K 334.5 tok/s; a 60k needle was found (61,038 tokens, 180 s). Lowest MemAvailable during that baseline was 1,444 MiB, below the test's own 1,536 MiB floor, so a RAM floor for future tests should be relative to the baseline. Gotcha: with `lazy_load: true` the engine says "ready" right away and loads the model only on the first request, so a test script must send one before it waits for `"loaded": true` in `/health`. Config backup: `strata-coder-iq1_m.json.bak-20261020-ctx65536` (identical to the restored config). Shrinking the conversation cache would not free start-up RAM on Linux; the upstream 0.2.x file-tier changes are the only lead for a larger window: [Upstream Strata 0.2.0-beta and 0.2.1 Review](../artifacts/upstream-v0-2-releases-review-2026-10-20.md).

- 2026-10-21: Engine `0.1.44.1+0.2.2-fixes` deployed: four fixes from upstream 0.2.2 ported by hand (HIP first-window verify hang, NaN retry, drifted tool-call openers, one answer-speed definition). Same speed as before (same-day A/B), answers correct. Rollback: `engine/strata.bak-0.1.44.1-qsa-20261021`. Details: [Upstream Strata 0.2.2 Review](../artifacts/upstream-v0-2-2-review-2026-10-21.md).
- 2026-10-23: Engine `0.1.44.1+0.2.3-fixes` and `strata-vision` deployed (6 upstream 0.2.3/0.2.2 fixes ported; rollback: `engine/strata.bak-20261023`, `engine/strata-vision.bak-20261023`). Same-day A/B benchmark (`tools/strata_bench.py --runs 3` + 7-prompt greedy check): `"STRATA_HC_Q8": "1"` added to `strata-coder-iq1_m.json` `env` after measuring faster across the board (cold `code` decode 29.8 -> 32.3 tok/s [+8.4%], short chat 23.9 -> 24.2 tok/s [peak 30.9], 4K prefill 298.6 -> 302.8 tok/s, 16K prefill 331.0 -> 334.4 tok/s, agent decode 24.8 -> 25.9 tok/s [+4.4%], agent TTFT 11.76 -> 11.26 s, total bench time 475 -> 461 s, greedy answers unchanged). `STRATA_SPEC_ADAPT_EVERY=2` (`STRATA_SPEC_ADAPT_WARM=200`) was tested and left off because doubling H2D expert swap frequency during the first 200 verify rounds cost 7%–17% cold decode speed on PCIe 4.0 x8. Details: [Upstream Strata 0.2.3 Review (2026-10-23)](../artifacts/upstream-v0-2-3-review-2026-10-23.md).
- 2026-10-25: **Strata v0.2.5 Web Ergonomics and Server Reliability Sync**. Safety backup created at `~/.config/dl-ai/backup-20261025/` and git tag `backup/before-v025-sync-20261025`. Implemented CommonMark soft breaks (`#3818`), screenshot clipboard pasting (`Ctrl+V`, `#3748`), window drag & drop / PDF support (`#3838`), user bubble pre-wrap & copy feedback (`#3720`, `#3731`), decimal input helpers (`#3736`), dynamic model load timeout scaling up to 1800s (`#3949`, `#3459`), clean model shard deletion with `made_by_strata` (`#3716`), and ROCm `STRATA_PREFILL_WARM=1`. Verified via automated tests and live server health check. Details: [Strata v0.2.5 Sync Walkthrough](../artifacts/strata-v0-2-5-sync-and-ergonomics-walkthrough.md).
- 2026-10-25: Post-v0.2.5 sync performance benchmark (`tools/strata_bench.py`, 479 s, 0 failures): Chat decode 25.20 tok/s (+1.6%, peak 31.10), 4K prompt 302.20 tok/s, 16K prompt 323.50 tok/s, agent decode 27.30 tok/s (peak 34.60), agent cache hit 68.46%. Details: [Strata Performance Benchmark Report (2026-10-25)](../artifacts/strata-benchmark-2026-10-25-v025-sync.md).

## Key Facts

- `gfx1102` (Navi 33) was enabled in `setup.py` under `AMD_ARCHS` and compiled natively via ROCm 7.2.4 (`/opt/rocm/lib`).
- The 16 GB VRAM holds 3,736 expert cache slots directly on device, configured with a 2,560 MiB VRAM reserve to ensure rock-solid desktop environment and GUI stability.
- System RAM holds 19.69 GiB of complementary pageable experts without disk swapping penalties.
- Speculative decoding with `mtp-q2_0.gguf` achieved an 88% draft acceptance rate during initial verification (the first request: 74 of 84 drafts).
- 2026-10-09: across all 14 requests in `strata-coder-iq1_m.log` (to 2026-10-05), 2,517 of 3,450 drafts were accepted (73%); decode ran at about 19-26 tok/s.
- Server listens on `0.0.0.0:8080` with bearer token authentication (`api_key`).
- **CachyOS Auto-Start & Watchdog Auto-Recovery:** Configured via systemd user units (`strata-server.service`, `strata-watchdog.service`, `cloudflared.service`) with `loginctl enable-linger damirl`. `strata-server.service` uses `Restart=always` (restarts in 5s if crashed). `strata-watchdog.service` runs [`tools/strata-watchdog.sh`](file:///mnt/data/Strata/tools/strata-watchdog.sh), probing `http://127.0.0.1:8080/health` every 30s; if the server hangs or becomes unresponsive for >10s across 3 consecutive checks, it automatically triggers `systemctl --user restart strata-server` to self-heal.
- 2026-10-09: the install runs **engine 0.1.39**. The local `main` (`6f32ec0`) shares **no history** with `origin/main` (git: unrelated histories), but has the same files as upstream commit `a1641e9` (2026-10-04). Upstream v0.1.41 (`fb58e0d`, fetched 2026-10-08) is 707 commits past that (1,871 files changed), so the 0.1.40-0.1.41 features in [Strata Release Milestones](../concepts/strata-release-milestones.md) are not available here yet. A fast-forward merge fails; updating means moving `main` to `origin/main`, then `./setup.sh` (recompiles the HIP engine). An earlier note here said "1,552 commits behind": that counted all of upstream's commits and was wrong.
- 2026-10-14: **"GPU use 100%" while Strata is idle doesn't mean work.** At 14:10, eight minutes after the last request (log: `done: 2932 tokens … 14:03:30`), `rocm-smi`/`gpu_busy_percent` read 100%. At the same time the engine's threads were at 0% CPU (`top -H -p <pid>`), no client was connected to :8080, and the card drew 59 W (it can draw about 190 W). LACT (`lactd`) holds the card at `power_dpm_force_performance_level=manual` with the `3D_FULL_SCREEN` profile (sclk 2,337 MHz), which explains the idle draw. The 100% busy reading is *(inferred)* the strata process keeping its GPU queues open, not compute. To check real load, look at the power draw and the `[strata]` journal lines, not the busy %. `ps %CPU` is the average over the process's life (it showed 285% while idle).
- 2026-10-21: the same check, done in full. At 01:42 the user saw "up to 50% GPU usage" after the CONTRA run ended (last `[strata] done:` 01:38:53). `gpu_busy_percent` averaged 21-41%, with peaks of 100%. Real work was zero: the card drew 21-37 W (cap 150 W), the engine used 0% CPU, its log was unchanged and its two :8080 connections were idle. Only the engine holds KFD compute queues (7, in `/sys/class/kfd/kfd/proc/<pid>`); HIP work goes through KFD, so drm `fdinfo` engine times do not show it. LACT still holds `manual` at 1811 MHz instead of 255 MHz idle. Unloading the model or an automatic LACT profile would bring the meter to 0.
- 2026-10-15: `strata-watchdog.service` lost `Requires=strata-server.service`: with it, a stop and start of the server (20:00) left the watchdog dead. The watchdog now skips the Strata check while the server is stopped on purpose, and also watches Proton Mail Bridge (see [D.L. CLI On-Demand MCP Loading Plan](../artifacts/dl-cli-on-demand-mcp-plan.md)).
- 2026-10-09: the uncommitted local changes are saved on the local branch `local/2026-10-05-changes` (commit `9867069`); v0.1.41 already supports gfx1102, so only the MCP tools need re-applying. They were: gfx1102 added to `setup.py` (`ROCM_INDEXES`, `AMD_ARCHS`, `AMD_NAMES`, `AMD_CARDS`) and the `strata_coder_generate` / `strata_coder_review` tools in `tools/strata_mcp.py`; `strata.sh` is untracked.

## Details

### Context

The host machine features a high-capacity second NVMe SSD on `/mnt/data` (460 GB available) while the root filesystem had 69 GB free. Relocating the installation to `/mnt/data/Strata` while creating a desktop symlink at `~/Desktop/Strata` provided ample capacity for the 59 GB of model shards and build trees.

### Options Considered

1. **Root drive installation (`/home`):** With 69 GB free, downloading 59 GB of model data would leave insufficient headroom for cache buffers and OS operations.
2. **Standard Qwen Full Model:** Demands 48–64 GB system RAM, causing thrashing on 32 GB systems.
3. **Coder IQ1_M:** Trimmed to 256 experts, fitting cleanly into the 32 GB RAM budget.

### Why This Selection

- **Partition:** `/mnt/data/Strata` (NVMe storage with 460 GB margin).
- **Model:** Qwen3.8-Flash-Next Coder (`IQ1_M`) with CPU vision enabled (`--vision cpu`).
- **Security:** LAN exposure on `0.0.0.0` secured with a 48-character secret key.

### Running the server

`/mnt/data/Strata/strata.sh` (created 2026-10-05 at the user's request) starts and stops this install. It wraps `run-coder-iq1_m.sh`, which `setup.py` writes.

| Command | What it does |
| --- | --- |
| `./strata.sh start` | Starts the server in the background (output in `strata-server.out`, pid in `strata-server.pid`) and waits up to 300 s until `http://127.0.0.1:8080/health` reports `"loaded": true`. |
| `./strata.sh stop` | Sends SIGTERM to the server, forces it after 30 s, and ends any leftover `engine/strata` or `strata-vision` process. |
| `./strata.sh restart` / `status` / `logs` | Stop then start; running or not, plus `http://127.0.0.1:8080/health`; follow `strata-server.out`. |

- Measured on 2026-10-05: ready **60 s** after `start`; on `stop` the engine and the image encoder exit with the server, so the GPU's VRAM and the RAM are freed.
- `RUN_SCRIPT`, `PORT` and `START_TIMEOUT` can be overridden from the environment, e.g. for another installed model.
- `http://127.0.0.1:8080/health` answers without the API key, so the script needs no secret.
- The run script passes `--open`, so a start also opens the browser.
- `strata.sh`, `strata-server.pid` and `strata-server.out` are not in `.gitignore`; they show as untracked files in git.

## Related

- Lifecycle: [Lazy Loading and GUI Force Restart](lazy-loading-and-gui-force-restart.md)
- Optimization: [Strata v0.1.43 Performance Switches and Memory Hygiene](strata-v0-1-43-performance-and-memory-optimizations.md)
- Engine: [Strata](../entities/strata.md)
- Models: [Strata Model Variants](../entities/strata-models.md)
- Sizing Decisions: [Model Selection and Hardware Budgeting](model-selection-and-hardware-budget.md)
- Upgrade Plan: [RAM Upgrade Plan: Qwen Context & Quantization vs DeepSeek](../artifacts/ram-upgrade-plan-qwen-context-vs-deepseek.md)
- Knowledge Suites: [Knowledge MCP Suites and DeepSeek Hybrid Escalation Walkthrough](../artifacts/knowledge-mcp-and-deepseek-escalation-walkthrough.md)
- Git: [Local-Only Repository](../preferences/local-only-repository.md)
- Evaluation: [Component 4: Prompt Tokenizer Prefix Caching Validation & Benchmark Report](../artifacts/v0-1-45-component-4-tokenizer-prefix-caching-report.md)
- Observability: [Component 5: Web Monitor & Observability Updates Validation Report](../artifacts/v0-1-45-component-5-web-monitor-observability-report.md)
- Complete v0.1.45 Report: [Strata v0.1.45 Complete Upstream Evaluation & Benchmark Report](../artifacts/v0-1-45-optimizations-and-tuning-report.md)

## Sources

1. User interview and deployment session — chat, 2026-10-05.
2. `strata-coder-iq1_m.log` — read 2026-10-05, re-read 2026-10-09.
7. `/opt/rocm/.info/version` (7.2.4) — read 2026-10-09.
3. `strata-coder-iq1_m.json` — read 2026-10-05.
4. `/mnt/data/Strata/strata.sh` — written and tested (start, status, stop) 2026-10-05.
5. User, chat, 2026-10-05 — asked for a start/stop script.
6. `git status`, `git rev-list --count HEAD..origin/main` — run 2026-10-09.
- [Strata AMD Deployment Plan](../artifacts/strata-deployment-plan.md)
1. strata-coder-iq1_m.log, /proc/<pid>/status and rocm-smi, read 2026-10-13.
