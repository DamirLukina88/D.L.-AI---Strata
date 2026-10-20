---
title: "Upstream Strata 0.2.0-beta and 0.2.1 Review (2026-10-20)"
type: artifact
description: "Which 0.2.0-beta / 0.2.1 changes fit this install (RX 7600 XT, Linux, 32 GB RAM): most do not apply; the file-tier ports are the one lead"
status: active
tags: [upstream, release, review, gfx1102, engine, context, conversation-cache]
created: 2026-10-20
updated: 2026-10-20
last_verified: 2026-10-20
---

# Upstream Strata 0.2.0-beta and 0.2.1 Review (2026-10-20)

## Summary

Upstream released 0.2.0-beta (2026-10-19, engine 0.1.45.3) and 0.2.1 (2026-10-20, engine 0.1.46). This install runs engine 0.1.44.1 plus 148 local commits (`v0.1.44.1-148-g74d597bd`), with some 0.1.45 parts ported on 2026-10-17. The gap to `v0.2.1` is 1,148 commits and 1,591 files (+265,030 / -5,066 lines), mostly the new desktop app, the Terminal and packaging, which this install does not use. Upstream's own notes say RX 7000 (gfx1100-1102) builds "compile; no RX 7000 card ran them". Nothing was merged. Each candidate was checked against this machine:

| Upstream change | Applies here? | Evidence (2026-10-20) |
|---|---|---|
| CPU workers from physical cores (`5ece068f`, 0.2.0) | No, already so | Engine log: 5 pool workers on CPUs 1-5 plus the host thread on 0, on a 6-core Ryzen 5 3600 |
| Fit checks count the MTP draft layer (`671f4573`, 0.2.1) | No | Touches only `setup.py` and the app host; at run time the expert cache is sized after the 876 MiB draft layer has loaded |
| RLIMIT_RTTIME warning for signal-9 deaths (`c6a20b7e`) | No | `/proc/<engine>/limits`: realtime timeout unlimited; 0 signal-9 deaths in 14 days of journal |
| Pictures on the CPU for cards under 24 GB (0.2.0) | Already so | `strata-vision: on the CPU, 6 threads`; it holds about 950 MB of RAM (RSS 969,468 KB). The user wants pictures kept. |
| Linux file tier: zero-copy page-cached experts, I/O prefetch and gate (`82c80ac4`), host-priced prompt chunk (`e77f1dfc`), prefetch for `experts.bin` packs (`ecf2bdcb`) | Only above 65,536 context | At 65,536 every lendable slot keeps its experts in RAM (no SSD reads). Larger windows read 5-33% of them from the pack (see [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)). Upstream tested these on CUDA, and `ecf2bdcb` on an IQ3_XXS pack only. This is the one lead for a larger context; a port needs a HIP rebuild, identity checks and the context ladder again. |
| hipBLASLt tuning tables (`c6aa4223`, `4ed8eb02`) | No | Tables exist for gfx1100, gfx1103, gfx1151, gfx1201, none for gfx1102; on by default only on Strix Halo |
| gfx12 WMMA / fused prompt defaults, HIP queue prime, 780M prompt set, Intel, NVIDIA, Mac, two-GPU batch | No | Other hardware (the queue prime is RX 9000 only; "Windows and RX 7000 cards are not changed") |
| App, Terminal, installers, signed update feed, Docker images, task board, KaTeX, `/loop` | No | This install runs its own `serve/` web app, D.L. CLI and dl-ai-sessiond; ideas only (for example a board for scheduled jobs) |
| `strata bench run` standard-v1 | Optional | Only needed to send a community result in the new protocol |

## Conversation cache (checked the same day, user's question)

Shrinking `--conversation-cache-mib 1024` was considered to give a larger context more RAM. It would not help and would cost a little:

- On Linux the engine does not set the cache's RAM aside at start. The only start-up check that counts it is Windows-only (`src/program/generate.cpp:7346`). The cache takes RAM only while a conversation is parked, and it already yields under pressure (log since 2026-10-10: 212 "skip parking (physical RAM admission ...)", 155 "snapshot exceeds available", 17 "RAM floor after capture").
- The expert RAM split at start followed the context's own needs (20.00 GiB of RAM experts at 98,304, 20.62 GiB at 65,536), not the cache.
- What the cache gives: 41 restores since 2026-10-10 (29 live, 12 from checkpoints), 244,008 prompt tokens not read again (median 5,057, largest 32,812). At this install's measured 4K-32K prompt speed of 294-335 tok/s, that is roughly 12-14 minutes of prompt reading saved *(inferred from those speeds)*; a restore takes 0.1-0.35 s.
- Decision: keep 1024 MiB.

## Sources

1. Upstream release notes 0.2.0-beta (tag `v0.2.0-beta`, commit `3d1fb48`) and 0.2.1 (tag `v0.2.1`, commit `9076725`), GitHub notification emails pasted by the user in chat, 2026-10-20.
2. `git fetch upstream --tags`; `git log` / `git show --stat` of the commits named above, 2026-10-20.
3. `/mnt/data/Strata/strata-coder-iq1_m.log` (engine start-up, CPU pool, vision and conversation-cache lines), `/proc/<engine pid>/limits`, `journalctl --user -u strata-server`, 2026-10-20.
4. User, chat, 2026-10-20: keep pictures on; asked whether the conversation cache could be reduced without side effects.
