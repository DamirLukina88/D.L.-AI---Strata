---
title: "Upstream Open PR Review (2026-10-13)"
type: artifact
description: "Which open Niko1221/Strata PRs fit this install (gfx1102, 32 GB RAM, Claude Code); all merge cleanly onto main 51fae4a6"
status: active
tags: [upstream, review, conversation-cache, anthropic-api]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Upstream Open PR Review (2026-10-13)

## Summary

Upstream `main` (`a0116b27`, #2038, 2026-10-12) is fully contained in local `main` (`51fae4a6`); upstream has no new tags past v0.1.43.1. What is left upstream is ~100 open PRs. The ones below fit this install; each was fetched as `refs/upstream-pr/<n>` and `git merge-tree` showed no conflicts against `51fae4a6`.

## Evidence from our own logs (strata-coder-iq1_m.log, journal, to 2026-10-13)

- Conversation cache: one conversation re-parked every turn at ~1.04 GB a time (~1 s per park), 59 "dropped superseded copy" lines; 69 "skip parking (physical RAM admission)" lines, 26 of them with source cgroup.
- Engine hangs: "no progress for 60 s ... reading the prompt (batched): waiting for the GPU (attention, router)" on 2026-10-12/13, exit -6 then restart. No open upstream PR targets this; closest issues are #2267, #2049, #1569.

## Candidates, by fit

| Tier | PR | What | Why for us |
| --- | --- | --- | --- |
| 1 | #2265 | `--conversation-cache-park-gain N` (opt-in) | Stops the per-turn 1 GB re-park seen in our log |
| 1 | #2253 | RAM gate releases the heap, stops useless evictions | Matches the 69 skip-parking lines |
| 1 | #2247 | `--session-state-codec bf16` (opt-in) | Running state 118 MB -> 59 MB per snapshot; 1 GiB cache holds more |
| 1 | #2290 | Anthropic usage reports `cache_creation_input_tokens` | Claude Code over /v1/messages |
| 1 | #2284, #2285 | Tool schema through streamed aliases; late system roles kept | Agent clients (Claude Code, D.L. CLI) |
| 1 | #2170 | Race in long-prompt give-way (TTFT) | Server only, small |
| 2 | #2217 | Active file cache counted reclaimable under cgroup | Our memory guard reads cgroup limits |
| 2 | #2243 | `--drop-file-cache` (opt-in) | Frees page cache after load; only applies when no expert is read from files |
| 2 | #2196 + #2189 | Vision encoder only while pictures; HIP VMM for `--vram-elastic`/`--kv-grow` | We run `--vision cpu`, so the VRAM gain is small; #2189 is a HIP engine change |
| 2 | #2140, #2278 | `thinking_budget_tokens`; `/v1/completions` | Client compatibility |
| 2 | #2161, #2287 | Setup: resume interrupted engine update / downloads | Robustness |
| 3 | #2231 (closed, not merged) | gfx1100 bit-exact speedups, +12% decode on 7900 XTX | Many default-on kernel changes, RDNA3 wave32; worth a bench on gfx1102 only |
| 3 | #2224 | PcieAuto default on gfx1100 | Gated to gfx1100; gfx1102 unmeasured |
| 3 | #2119 | Disk-backed parking | Competes with #1937 and #2098; wait for upstream to pick one |

Skipped: SYCL/Intel, sm_75/sm_61, Windows-only, NUMA, UMWAIT (Intel-only; Ryzen 3600 lacks it), bench reports, i18n.

## Outcome (2026-10-13 evening)

Merged Tier 1 + Tier 2 (13 PRs: #2290 #2284 #2285 #2170 #2140 #2278 #2161 #2287 #2253 #2265 #2247 #2217 #2243) on branch `upstream-prs-2026-10-13`, then into local `main` as `b5e5b3ff` (not pushed). Plan: `~/.claude/plans/create-a-detailed-plan-vivid-yeti.md`.

- Tests: serve 747 passed / 11 skipped (main before: 726 / 11); setup 33 pass, `test_setup_engine_hash.py` fails before and after (known upstream); 9 C++ conversation/state-codec/file-source tests pass (`-DSTRATA_BUILD_CONVERSATION_TESTS=ON`). `expert_layout_test` needs `STRATA_BUILD_TESTS`, not built here.
- End-to-end API checks (scratch `verify.py`): all 10 pass - Anthropic usage adds up (input 1 + cache_creation 61 = 62), late system message accepted, tool `path` "123" stays a string, `/v1/completions` refuses without key and works streamed/non-streamed, `thinking_budget_tokens` limits thinking like `reasoning_budget_tokens`.

Bench, Coder IQ1_M, `tools/strata_bench.py --url` against the service, same day (results in `bench/results/upstream-prs-2026-10-13/<arm>`):

| arm | chat tok/s | 4K tok/s | 16K tok/s | agent TTFT s | agent tok/s | parks | avg park MB | park ms | min MemAvail MiB |
|---|---|---|---|---|---|---|---|---|---|
| base (old binary) | 16.9 | 247.8 | 285.4 | 12.93 | 20.8 | 18 | 290 | 8524 | 2646 |
| new binary | 22.8 | 262.2 | 286.9 | 12.93 | 28.0 | 19 | 307 | 5281 | 2718 |
| + bf16 state | 22.8 | 261.8 | 288.9 | 12.84 | 25.9 | 18 | 149 | 3156 | 1973 |
| + bf16 + park-gain 1024 | - | ~270 | ~286 | 13.05 | 27.0 | 20 | 202 | 4664 | 1779 |
| + bf16 + drop-file-cache | 24.2 | 271.7 | 288.1 | 12.65 | 26.9 | 19 | 179 | 5498 | 2463 |

Decode differences between arms are run-to-run noise (no merged PR touches decode kernels).

- **Enabled:** `--session-state-codec bf16` in `strata-coder-iq1_m.json` and `strata-q2_0.json` (q2_0 not benched; the stored-state layout is the same model geometry). Parked snapshots about half the bytes (16K conversation 600 -> 423 MB).
- **Left off:** `--conversation-cache-park-gain` - a Claude-Code-like test (11 small turns, a side request between turns) parked 21 times with and without it (8.6 GB written both): a resumed conversation consumes its parked copy, so there is rarely an older copy to keep. `--drop-file-cache` - it ran (23.42 GiB advised back) but MemAvailable did not improve, since page cache already counts as available.
- q2_0 on this PC is disk-bound (38 GB of experts mapped, 32 GB RAM): an accidental bench on it gave 4K prompts at 14-24 tok/s and 16K at about 10 min each. Not worth tuning without more RAM.

Gotchas found:
- The packs carry their own `tokenizer/chat_template.jinja`, which the server prefers over `serve/chat_template.jinja`. After a template change (here #2285, late system roles) copy it into both packs, or late system messages fail with "System message must be at the beginning". Done; `.bak-20261013` copies kept.
- `cp` onto `engine/strata` fails ("Text file busy") while the engine runs; deploy with `systemctl --user stop strata-server`, copy, start. `strata-watchdog` has `Requires=strata-server` and stays dead after a separate stop + start: start it too (`restart` brings it back by itself).
- The web app on `http://127.0.0.1:8080` keeps its own browser-stored key, separate from the Cloudflare origin; after the key rotation it must be entered again under Settings, or the Code tab shows "missing or wrong API key".

### Second round: #2231, #2226, #2191 (2026-10-13, late evening)

Test worktree `/mnt/data/Strata-prtest` (branch `test-prs-2231-2226-2191`, build `build-hip-test`); the live checkout and `engine/strata` were not changed. Reference W = live config (WMMA + bf16). Medians, same bench:

| run | 4K tok/s | 16K tok/s | agent TTFT s | agent tok/s | chat tok/s |
|---|---|---|---|---|---|
| W live | 294.6 | 324.9 | 11.46 | 27.4 | 24.1 |
| T1 #2231 defaults | 301.3 | 333.2 | 11.29 | 28.3 | 23.8 |
| T2 + the seven opt-in switches | 298.5 | 315.8 | 11.07 | 30.0 | 23.6 |
| T3 + the five decode switches | 289.6 | 325.6 | 11.39 | 28.9 | 23.7 |

- #2231 defaults: prompt +2.3% / +2.6% (ranges do not overlap), decode flat. The PR's +12% decode (on a 7900 XTX) did not appear on gfx1102. The opt-in switches (`STRATA_WAIT_FUSE`, `MMVQ_IL_PLAIN`, `COMBINE_HITS`, `ROUTE_PUB`, `WAIT_COMBINE`, `PF_LEAN_ISSUE`, `PF_COPY2`) gave no clear decode gain and cost prompt speed. The PR was closed by its author on 2026-10-13 without comment; adopting it means carrying 2.2K lines of kernel changes locally.
- The bit-exactness claim cannot be checked by comparing answers on this config: the same engine gave different temperature-0 answers on a second run, because the routing switches (`STRATA_ROUTE_TAIL_SKIP`, `STRATA_ROUTE_RESIDENT`) depend on what is in the expert cache.
- #2226 (`STRATA_HC_PERSIST`) does not compile for gfx11: it uses `__builtin_amdgcn_s_memrealtime`, which RDNA3 lacks, and it assumes 80 co-resident blocks (the 7600 XT has 16 WGPs). Dropped.
- #2191 (`--prefill-head-alias`) needs `--short-read 0`, cuts the prompt chunk from 8192 to 2048 tokens, waits 622 ms per request to restore the head, and on HIP the engine stopped itself: "the output head was reloaded at another address, so the captured verify graphs would read freed memory". Rejected for this install.

Rollback: backups `engine/strata.bak-0.1.43.1-20261013`, `~/.config/dl-ai/backup-20261013/*.before-upstream-prs`, pack templates `*.bak-20261013`.

## Upstream v0.1.44 (released 2026-10-13)

It contains #2170 (long-prompt give-way) and #2191 / #2196 as opt-ins. None of our other merged PRs are in it. After merging 0.1.44 on top of `main`, ours remain: see [Strata v0.1.44 Merge](strata-v0-1-44-merge.md).

## Related

- [Strata v0.1.44 Merge (2026-10-13)](strata-v0-1-44-merge.md)
- [Upstream PRs Merge Plan (2026-10-13)](upstream-prs-merge-plan-2026-10-13.md)
- [Upstream Fork Review (2026-10-13)](upstream-forks-review-2026-10-13.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)

## Sources

1. `git fetch upstream`, `git ls-remote upstream`, GitHub API `/repos/Niko1221/Strata/pulls` and `/issues`, accessed 2026-10-13.
2. `strata-coder-iq1_m.log`, `journalctl --user -u strata-server`, read 2026-10-13.
3. User, chat, 2026-10-13.
