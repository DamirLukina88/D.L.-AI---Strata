---
title: "Upstream Fork Review (2026-10-13)"
type: artifact
description: "Which of Niko1221/Strata's 2,271 forks matter for this install (gfx1102, 32 GB RAM); STRATA_HIP_WMMA and Strata-Cascade are the leads"
status: active
tags: [upstream, forks, amd, gfx1102, performance]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Upstream Fork Review (2026-10-13)

## Summary

Reviewed the forks of Niko1221/Strata on 2026-10-13 for ideas usable on this install (RX 7600 XT gfx1102 16 GB, 32 GB RAM, CachyOS, Coder IQ1_M, Claude Code client).

- GitHub lists 2,334 forks; the API returned 2,271, of which 741 were pushed after creation and 66 have their own description. Most carry fixes that upstream already merged. The user's own public fork is `DamirLukina88/D.L.-AI---Strata`.
- Without `gh` the review used the unauthenticated API (60 calls/hour): 23 calls for the fork list, about 15 for compares and PR status. READMEs were read from raw.githubusercontent.com, which is not rate-limited.

## Leads for this install

1. **`STRATA_HIP_WMMA=1` (already in our tree, off).** It runs the int8-KV prompt attention on RDNA3 matrix cores. It came from xyzzing's fork (`xyzzing/Strata`, gfx1100) as upstream PR #786. That PR was closed on 2026-10-06 because upstream 0.1.40 shipped its own version for gfx1100/1101/1102/1150/1151 (`src/kernels/cuda/qsa_prompt_attn.cu`, `hip_wmma_usable()`). Both of our configs use `--kv int8` and neither sets the flag. Measured on a 7900 XTX: prefill +17.0% and +29.5% (two independent validations), and +22.8% at 128K on the author's rig, with decode flat. The gain grows with prompt length (attention fell from 27.5% to 9.9% of GPU time at 128K). The output differs from the default kernel in its last bits. It has not been measured on gfx1102, so it needs an on/off A/B.
2. **Strata-Cascade (`forestautomation/Strata-Cascade`, on upstream 0.1.43).** It targets exactly 32 GB RAM and a 16 GB card. Experts go to VRAM, a pinned RAM budget and the SSD, with a ring of about 48 prefetched cold reads (`--tiered-experts --host-budget-gib N`, one-card mode `--low-ram tiered`). On Windows with one card it measured 28.2 t/s decode and about 960 t/s prefill at 128K, where upstream's low-RAM mode froze the PC. It addresses our `--resident-budget-gib` stall (355 s of blocking reads from the pack). Caveats:
   - Its Linux path is implemented but was never built or measured.
   - The pinned tier needs a memlock limit above our user manager's 8 MiB, which means sudo (`DefaultLimitMEMLOCK` or `LimitMEMLOCK` on the unit).
   - It is 637 commits ahead with unrelated-history merges, so porting it is a project, not a cherry-pick.
   - On Linux its memory guard only pauses prefetch.
3. **gfx11 WMMA block scorer (`STRATA_SELECT_WMMA`).** Upstream's version is gfx12-only (`qsa_select.cu`, `sel_gfx12_device()`). xyzzing's fork has a gfx11 arm measured at +11.2% end to end at 128K on 0.1.39. It would need a port, and it matters less at our 64K `--max-context`.

## Outcome: `STRATA_HIP_WMMA=1` enabled (2026-10-13 evening)

A/B on gfx1102, same binary (with the 13 merged PRs) and the same config (`--session-state-codec bf16`); the engine logs `STRATA_HIP_WMMA: the prompt attention on matrix cores on (gfx1102)`.

| | WMMA off | WMMA on | change |
|---|---|---|---|
| 4K prompt tok/s | 261.8 | 294.6 | +12.5% |
| 16K prompt tok/s | 288.9 | 324.9 | +12.5% |
| 16K first token (s) | 55.6 | 49.5 | -11% |
| agent turn first token (s) | 12.84 | 11.46 | -11% |
| chat / agent decode tok/s | 22.8 / 25.9 | 24.1 / 27.4 | flat (noise) |

- Quality: five fixed prompts at temperature 0 (code, arithmetic, bugfix, a needle in about 20K tokens, a puzzle). Four answers were byte-identical with WMMA on and off. The arithmetic one differed, but both were wrong (535 on, 541 off, correct 403), so that is the IQ1_M model, not WMMA.
- The agent bench re-read 73 tokens per session with WMMA (4 without): the last-bits difference changes a generated word now and then, so a later turn reuses a little less of the cache. Its first-token time still improved by 11%.
- Set as `"STRATA_HIP_WMMA": "1"` in the `env` of `strata-coder-iq1_m.json` only. `strata-q2_0.json` also uses `--kv int8` but was not measured; q2_0 is disk-bound on this PC anyway.
- The kernel's parity test (`qsa_prompt_attn_parity`) builds only for CUDA, so it was not run.

## Checked, not useful here

- `MistVVK/XeStrata` (183 stars): a SYCL multi-vendor engine. Its RDNA3 WMMA paths are in SYCL, not our HIP build, and it skipped upstream's gfx11 HIP switches.
- `eddoursul/Strata`: an RTX 3090 + 5070 Ti with 160 GB RAM on Windows. `--kv-grow` and `--adapt-decay` are already in our tree; `/v1/choose` and `--vram-pin-gib` are niche.
- `Jumbomuffin777/Strata-Void`: Intel Arc SYCL, task-parallel requests that split one prompt across batch slots, 1,026 commits behind.
- `averyjohnkucan-arch/StrataUnleashed` and `imanu86/Strata-2080Ti`: NVIDIA-specific and far behind upstream.
- `RandoTeam`, `rwkeyes`, `Hardin22`, `jagsan-cyber` (gfx1201, Windows) and `CC-David-CC` (gfx1012): small, behind upstream, or other hardware.

## Sources

1. User, chat, 2026-10-13.
2. GitHub API `repos/Niko1221/Strata/forks`, `compare/main...<fork>`, `pulls/786` and `issues/786/comments`, accessed 2026-10-13.
3. https://github.com/forestautomation/Strata-Cascade (README.md and STRATA-CASCADE.md), accessed 2026-10-13.
4. https://github.com/xyzzing/Strata (README.md and GFX1100.md), accessed 2026-10-13.
5. `strata-coder-iq1_m.json`, `strata-q2_0.json` and `src/kernels/cuda/qsa_prompt_attn.cu` in this checkout.
