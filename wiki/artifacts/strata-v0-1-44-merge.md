---
title: "Strata v0.1.44 Merge (2026-10-13)"
type: artifact
description: "Upstream v0.1.44 (2026-10-13) and v0.1.44.1 (2026-10-15) merged into main with our PRs kept; STRATA_COMMIT_BATCH=0 on gfx1102"
status: active
tags: [upstream, merge, benchmark, v0-1-44]
created: 2026-10-13
updated: 2026-10-15
last_verified: 2026-10-15
---

# Strata v0.1.44 Merge (2026-10-13)

## Summary

Upstream released v0.1.44 on 2026-10-13: 271 commits on top of v0.1.43.1. It was merged on branch `upstream-0.1.44` (`ca3f37e8`) and then into local `main` as `9d614675`. The engine was rebuilt for gfx1102 and deployed the same night. The user declined Qwen3.6-35B-A3B, the Unsloth/NVFP4 files and image generation, and q2_0 stays.

- What we took for this PC:
  - a literal `<tool_call>` / `<tool_response>` in a message is text (#2026)
  - a picture in a long conversation keeps the cache (#2228)
  - a ROCm set-up crash at start is retried (`STRATA_START_RETRIES`)
  - #2170, #2191 and #2196 now come from upstream (the last two as opt-ins we do not use)
- Our 13 merged PRs from the [open PR review](upstream-open-prs-review-2026-10-13.md) are mostly not in 0.1.44. Merging on top of `main` kept them, including `--session-state-codec bf16`, which the live configs use.
- **Gotcha: `STRATA_COMMIT_BATCH` (on by default in 0.1.44, upstream commit `6f3e3810`) costs about 3% on prompt reading on gfx1102.** Both local configs set `STRATA_COMMIT_BATCH=0`.

## Conflict resolutions

- `README.de/es/fr/ja/pt-BR/zh-CN.md`: kept deleted. `README.md`: ours.
- `serve/web/app.js`, `index.html`, `app.css`: ours. Upstream's only web change was the image-generation Images tab; image generation stays off (no config enables it).
- `serve/frontend.py`: took `env_to_user` (#2175, opt-in via the config's `"env_to_user"`) and dropped upstream's `_late_system_to_user`, which #2285's system-role rendering replaced. Both adapters `return _env_to_user(messages), tools, kwargs`.
- `src/program/generate.cpp`: help text with upstream's `--adapt-async` wording followed by `--drop-file-cache`.
- `serve/chat_template.jinja` did not change in 0.1.44, so the pack copies stay valid.

## Tests

- serve: 788 passed, 11 skipped (747 before the merge).
- setup: 38 pass. `test_setup_engine_hash.py` failed before the merge. `test_setup_golden.py` fails 8 Unsloth UD-Q4_K_XL golden cases on upstream's own untouched 0.1.44 tree too, so it is an upstream issue.
- C++: the 9 conversation / state-codec / session-save / file-source tests pass.
- API checks: all 11 pass, including a new one for #2026: a message quoting `<tool_call>` and `</tool_response>` is repeated as text and the answer continues.
- q2_0 loads on the new engine (bf16 state) and answers.

## Bench

Coder IQ1_M, live config (bf16 + `STRATA_HIP_WMMA=1`), same session, medians:

| run | 4K tok/s | 16K tok/s | agent TTFT s | agent tok/s | chat tok/s |
|---|---|---|---|---|---|
| previous binary `b5e5b3ff` | 296.9 (292.9-299.3) | 327.6 | 11.42 | 28.0 | 23.9 |
| 0.1.44 default | 285.6 (285.3-286.2) | 317.1 | 11.75 | 27.5 | 23.6 |
| 0.1.44 + `STRATA_COMMIT_BATCH=0` (deployed) | 291.8 | 327.4 | 11.49 | 28.5 | 23.9 |

- No hangs in any run.
- One 0.1.44 load sized its RAM copy at 20.56 GiB (against 20.62) and logged "28 of 1733 lendable slots will read their experts from the pack during a long prompt". The next load covered all 1733. It depends on free RAM at start (4 GiB headroom kept; it only matters on 50K+ prompts).

## Deployment notes

- `engine/BUILD.json` `"version"` set to `0.1.44`. Do not run `./setup.sh` or `update.sh` on this box: on Linux HIP they rebuild the engine with setup's own flags into `engine/`.
- Backups: `engine/strata.bak-b5e5b3ff-20261014`, `~/.config/dl-ai/backup-20261013/*.before-0.1.44`.

## v0.1.44.1 hotfix (2026-10-15)

- Upstream's v0.1.44.1 (`296b59d2`, 2026-10-14): 11 commits, 24 files. Merged with no conflicts on branch `upstream-0.1.44.1` (`a00d6d40`), then into `main` as `84059f5e`. Backup branch: `backup/main-before-0.1.44.1`.
- What it brings here: a crashed engine start is no longer retried as a GPU runtime start, and the start error says how the process ended (#2324); the config's `reasoning_effort` reaches the Responses API too; a setup re-run keeps the installed size. The Metal, CUDA 12.1 and no-AVX fixes do not apply to this PC.
- Tests: serve 806 passed, 11 skipped (788 before); setup 39 of 41 pass (the same two as before fail: `test_setup_golden.py`, `test_setup_engine_hash.py`); the 9 C++ conversation / session-save / state-codec tests pass.
- Engine rebuilt in `build-hip` (gfx1102), copied to `engine/strata`; `engine/BUILD.json` version `0.1.44.1`, src `f483892f3c8f1e01`. `STRATA_COMMIT_BATCH=0` stays in the config. Backups: `engine/strata.bak-0.1.44-*-20261015`, `engine/BUILD.json.bak-0.1.44`.
- Check: after the restart the model loaded on the first request and answered correctly. Its engine changes are a load-time F16-to-F32 widening in `q36_engine.cu` (written for CUDA 12.1, also built here) and the CPU nvfp4 files; none is in the decode or prompt path *(inferred from the diff)*.
- Bench (`tools/strata_bench.py`, 3 runs, live server, same config) against the deployed 0.1.44 run, medians: 4K 295.2 tok/s (291.8 before, +1.2%), 16K 331.1 (327.4, +1.1%), chat decode 23.9 (23.9), chat first token 1.89 s (2.01), agent first token 11.50 s (11.49), agent decode 26.8 tok/s (28.5, -6.0%; range 22.8-32.2 over 15 turns, so inside the run-to-run spread *(inferred)*). No hangs. Results: `bench/results/upstream-0.1.44.1-2026-10-15/v0441`.

## Related

- [Upstream Open PR Review (2026-10-13)](upstream-open-prs-review-2026-10-13.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)
- [GitHub Fork and Public Sanitization Architecture](../decisions/github-fork-and-sanitization.md)

## Sources

1. https://github.com/Niko1221/Strata/releases/tag/v0.1.44, accessed 2026-10-13.
2. Bench runs in `bench/results/upstream-prs-2026-10-13/{ref043,v044,v044cb0}` and the engine log `strata-coder-iq1_m.log`, 2026-10-13.
3. User, chat, 2026-10-13 (scope: merge only, no Qwen3.6, keep q2_0).
