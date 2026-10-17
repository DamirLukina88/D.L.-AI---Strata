---
title: "Upstream PRs Merge Plan (2026-10-13)"
type: artifact
description: "Approved step plan for merging 13 open upstream PRs: backups, merge order, tests, bench-then-enable flag sweep, rollback"
status: active
tags: [upstream, plan, benchmark]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Upstream PRs Merge Plan (2026-10-13)

## Summary

The plan the user approved on 2026-10-13 for merging 13 open upstream PRs (Tier 1 + Tier 2). It was carried out the same evening; the results, bench tables and what was enabled are in [Upstream Open PR Review (2026-10-13)](upstream-open-prs-review-2026-10-13.md). Two deviations from the plan: run D (park-gain 4096) was replaced by a targeted small-turn test, and `STRATA_HIP_WMMA=1` was added afterwards from the fork review.

## Plan as approved

### Context

Upstream `main` (`a0116b27`) is already fully in our `main` (`51fae4a6`). The remaining upstream improvements are open PRs. Our own logs show two problems that some of them fix:

- The conversation cache saves the same conversation again every turn: about 1.04 GB and about 1 s per save, and the older copy was dropped 59 times.
- It skipped saving 69 times because the RAM check refused (26 of those via the cgroup).

Other PRs improve Claude Code / agent compatibility over `/v1/messages`, plus memory accounting and setup robustness. Scope chosen by the user: **Tier 1 + Tier 2**. Rollout chosen by the user: **bench first, then turn on only the opt-in flags that hold up**.

The 13 PRs are already fetched as `refs/upstream-pr/<n>`. Every PR merges onto `main` with no conflicts, and every pair among the 13 merges with no conflicts (`git merge-tree`). The repo is local-only and is never pushed (wiki preference).

| Group | PR | Files | Default behaviour |
|---|---|---|---|
| Serve (Python) | #2290 Anthropic `cache_creation_input_tokens` | serve/server.py | changes `/v1/messages` usage fields |
| | #2284 tool schemas through streamed aliases | serve/frontend.py, responses.py | bug fix |
| | #2285 late system/developer roles kept | frontend.py, responses.py, **chat_template.jinja** | changes the rendered prompt |
| | #2170 give-way race on long prompt reads | server.py | bug fix |
| | #2140 `thinking_budget_tokens` honoured | server.py | bug fix |
| | #2278 legacy `/v1/completions` | server.py, frontend.py | new endpoint |
| Engine (C++/HIP) | #2265 `--conversation-cache-park-gain N` | generate.cpp, conversation_cache.hpp | opt-in, default 0 = unchanged |
| | #2253 RAM gate releases heap, stops useless evictions | conversation_cache/memory, generate.cpp | default on (fix) |
| | #2247 `--session-state-codec bf16` | conversation_* / state_codec, CMakeLists.txt, sycl/ | opt-in, default fp32 |
| | #2217 active file cache counted reclaimable under cgroup | expert_source.cpp | default on (fix) |
| | #2243 `--drop-file-cache` | expert_source.cpp, generate.cpp | opt-in |
| Setup | #2161 interrupted engine update retried | setup.py | fix |
| | #2287 resume downloads without Content-Length | setup.py | fix |

### Risk found during review: the pack's template copy

The server loads `<pack>/tokenizer/chat_template.jinja` before `serve/chat_template.jinja` (`serve/server.py:3452`). Both packs (`/mnt/data/Strata-data/packs/coder-iq1_m`, `.../q2_0`) carry a byte-identical copy of today's `serve/chat_template.jinja`. #2285 only edits the `serve/` copy. After #2285 the adapters pass late system messages through as `system`, so the old pack template would hit `raise_exception('System message must be at the beginning.')`. **Fix:** after merging, copy the new `serve/chat_template.jinja` over both pack copies, keeping `.bak-20261013` backups. Then confirm the three files are identical.

### Steps

#### 0. Safety copies and same-day baseline (before any change)
1. Back up:
   - `engine/strata` → `engine/strata.bak-0.1.43.1-20261013`
   - `strata-coder-iq1_m.json` and `strata-q2_0.json` → `~/.config/dl-ai/backup-20261013/*.before-upstream-prs`
   - both pack templates → `.bak-20261013`
2. Check that `engine/strata` is the binary in service. It differs from the newer `build-hip/strata` (built 10-13 10:58). Note which one runs (`/proc/<pid>/exe` of the engine), so that rollback restores the right file.
3. Baseline bench on today's binary and config. Use `./bench.sh` with `STRATA_KEY` set: the key now lives in `~/.config/dl-ai/secrets.env`, so either the user runs it or the user approves sourcing that file. Record:
   - chat tok/s and TTFT, 4K and 16K prompt tok/s, agent decode and TTFT
   - from the log: count of parks, `dropped ... superseded`, `skip parking`
   - min `MemAvailable` (sampled with `free -m` every 5 s during the bench) and the engine cgroup's `memory.peak`
4. Baseline tests on `main` so failures that already exist are known: `.venv/bin/python -m pytest serve -q`, plus `python tools/test_setup_*.py`. Install pytest into `.venv` if it's missing.

#### 1. Branch and merge
- `git switch -c upstream-prs-2026-10-13` from `main`.
- Merge in this order with `git merge --no-ff refs/upstream-pr/<n> -m "merge upstream PR #<n>: <title>"`. Each message ends with the Co-Authored-By line.
  - serve: #2290, #2284, #2285, #2170, #2140, #2278
  - setup: #2161, #2287
  - engine: #2253, #2265, #2247, #2217, #2243
- Each PR branch is based 52 to 85 commits behind our `main`, but those base commits are already in `main`, so each merge brings only the PR's own commits. After the merges, `git diff main --stat` should list only the files in the table above.
- Copy the template to both packs, as described under "Risk" above.

#### 2. Tests (no GPU needed)
- `.venv/bin/python -m pytest serve -q`. Compare to the step 0 baseline. The PRs' new tests should pass: test_native_tool_parser, test_tool_call_unclosed, test_request_accounting and the additions in test_server / test_parallel / test_responses.
- `python tools/test_setup_stale_stamp.py`, `python tools/test_setup_download_length.py`, plus the existing `tools/test_setup_*.py`.
- C++: `cmake --build build-hip -j$(nproc)`, then `ctest --test-dir build-hip -R "conversation|state_codec|session_save|expert_source|expert_layout|file_expert"`.
  - #2247 adds `state_codec.cpp` and its tests to `CMakeLists.txt`. If ninja doesn't pick them up, re-run `cmake build-hip`.
  - The cache already has `GPU_TARGETS=gfx1102`, Release.
- Also build the vision target if it's affected (it shouldn't be). Run `git diff main -- sycl/` only to confirm #2247's SYCL edits are compile-only; we don't build SYCL.

#### 3. Deploy the new binary with today's config (regression check)
- Copy `build-hip/strata` → `engine/strata`, then `systemctl --user restart strata-server`.
- Bench with the same command as step 0. Default-on changes (#2253, #2217, the serve fixes) must not regress throughput by more than noise (about ±5% from earlier same-day runs). Expect fewer `skip parking` lines.
- Run the serve checks from "Verification" below.

#### 4. Flag sweep (one change at a time, same bench each time)
Engine args go into `"args"` of `strata-coder-iq1_m.json`. Restart between runs.

| Run | Added args | What to watch |
|---|---|---|
| A | (none: step 3 result) | reference |
| B | `--session-state-codec bf16` | parked `bytes=` per park (expect lower; running state 118 → 59 MB per snapshot), agent bench output sane, tok/s unchanged |
| C | B + `--conversation-cache-park-gain 1024` | parks and superseded drops per agent run, agent TTFT on a switched conversation |
| D | B + `--conversation-cache-park-gain 4096` | same as C. Worst case is re-reading 4096 tokens at about 270 tok/s ≈ 15 s if the slot was lost |
| E | best of B–D + `--drop-file-cache` | engine log must say the drop ran (it refuses if any expert is read from files; we use `--resident-experts`); min MemAvailable, page cache after load |

Rule: keep a flag only if it doesn't lower any bench row by more than noise and improves its own target metric. bf16 storage is lossy, unlike the other flags. Keep it only if the agent run's answers and tool calls stay correct; the PR says the kernels still compute in FP32.

#### 5. Enable the winners
- Add the kept args to both `strata-coder-iq1_m.json` and `strata-q2_0.json`, then restart.
- Leave everything else in the config unchanged.

#### 6. Finish
- Merge the branch into `main` locally (`git merge --no-ff`). Do not push.
- Update the wiki:
  - [upstream-open-prs-review-2026-10-13.md](upstream-open-prs-review-2026-10-13.md): what was merged and the bench table
  - [rx-7600-xt-cachyos-deployment.md](../decisions/rx-7600-xt-cachyos-deployment.md): a dated bullet with the new flags and why
  - a gotcha note: pack template copies must follow `serve/chat_template.jinja`

### Verification (end to end)
- `/v1/messages`, streamed, through Claude Code against the local server: `message_delta` usage shows `cache_read_input_tokens`, `cache_creation_input_tokens`, and `input_tokens` ≥ 1, and the three add up to the prompt length.
- A request with a late `system` message (curl, Chat Completions and Messages) is accepted, and the engine log or debug template output shows `<|im_start|>system` at that position.
- A tool call with a string parameter that looks numeric (e.g. `path: "123"`) comes back as a string when streamed.
- `curl /v1/completions` with the API key header, both `stream:false` and `stream:true`, returns usage. Check that the route needs the key, like the other `/v1` routes (our auth fix 27f6feb8: keys are accepted only in headers).
- `thinking_budget_tokens` on a chat request limits thinking the same way `reasoning_budget_tokens` does.
- The web app (Cloudflare Access login) still loads and chats, the Code tab session still attaches, and `strata-watchdog` stays green for 30 min.
- Log counts (parks, superseded drops, skip parking) compared to the step 0 baseline over the same agent bench.

### Rollback
`git switch main`, restore `engine/strata.bak-0.1.43.1-20261013`, both config backups and both pack template `.bak` files, then `systemctl --user restart strata-server`.

### Out of scope
- #2231 (gfx1100 kernels, closed upstream), #2224 (PcieAuto, gfx1100 only), #2119 (disk parking, competing designs), #2196 and #2189 (VMM / vision elastic).
- The "no progress for 60 s" prompt-read hangs (exit -6): no upstream fix yet; track separately.

## Related

- [Upstream Open PR Review (2026-10-13)](upstream-open-prs-review-2026-10-13.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)

## Sources

1. Claude Code session plan file `~/.claude/plans/create-a-detailed-plan-vivid-yeti.md`, 2026-10-13.
2. User, chat, 2026-10-13 (approved the plan).
