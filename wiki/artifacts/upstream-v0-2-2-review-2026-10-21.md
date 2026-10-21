---
title: "Upstream Strata 0.2.2 Review (2026-10-21)"
type: artifact
description: "Which 0.2.2 changes fit this install (RX 7600 XT, Linux, 32 GB RAM, one NUMA node): the HIP verify-hang fix and a few server fixes; most of the release does not apply"
status: active
tags: [upstream, release, review, gfx1102, engine, speculative, server]
created: 2026-10-21
updated: 2026-10-21
last_verified: 2026-10-21
---

# Upstream Strata 0.2.2 Review (2026-10-21)

## Summary

Upstream released 0.2.2 (tag `v0.2.2`, commit `011c9e6`, engine 0.1.47) on 2026-10-21. This install is `v0.1.44.1-154-gd53a4361`: neither `v0.2.1` nor `v0.2.2` is merged. `v0.2.1..v0.2.2` is 297 commits, 400 files (+37,704 / -1,354). Because 0.2.1 is missing, only one checked upstream commit (`aece46db`, 1-token prompt with `--spec`) applies cleanly; every other candidate needs a hand port. Nothing was merged at first; four fixes were ported the same evening (below).

| 0.2.2 change | Applies here? | Evidence (2026-10-21) |
|---|---|---|
| HIP first-window verify hang: PLE flag raised before the first graph launch (`86d10ed8`, `STRATA_VERIFY_EARLY_PLE_FLAG`) | Yes, candidate | Our `src/core/verify.cpp` has the same zero-doorbell window graph with host flags (26 "doorbell" mentions); the fix defaults on for every HIP build. Seen upstream on gfx1151 (8 of 41 runs hung); no verify hang in our journal since 2026-10-10. About 40 lines; 4 hunks do not apply. Cost upstream: none measured on later windows (47.89 vs 47.78 tok/s). |
| `STRATA_SPEC_WATCH` speculative-loop watchdog (`4c3edf47`) | Optional | Diagnostic only, off by default |
| NaN in a prompt window: retry reads the prompt batched (`894f133b`, #3465) | Yes, small | 15 lines in `generate.cpp`; 0 non-finite lines in our engine log so far |
| Tool-call opener drift `<=NAME>`, `<function:NAME>`, `<NAME>` read as calls; undeclared tool stays text (`70f42407`, #3441/#3075) | Yes, for D.L. CLI | `serve/frontend.py` + tests; changes one behaviour: a request with no tools never gets `tool_calls` |
| Anthropic usage adds up / `cache_creation_input_tokens` (#2289), `thinking_budget_tokens` (#2141), 503 with reason (#2496), phone page width (#2971) | Partly already here | The field names already exist in our `serve/`; the upstream versions differ (6-7 hunks fail), so compare before porting |
| One tok/s definition (`fccfd343`) | Idea only | Our web app and D.L. CLI have their own speed display |
| `ab61f892` padded prefill activation is gfx11 only | Already fine | gfx1102 is gfx11; the change matters for gfx12 stages |
| Gyro (NVIDIA, Intel Arc, Mac), RX 6000 package, Strix Halo, NUMA split, GPU roles, API key optional, models folder, app/Terminal/Docker, fit ladder in setup/launch | No | Other hardware, one NUMA node, own `serve/` app with Cloudflare Access, configs set by hand. Gyro-S is 58.5 GB anyway. |
| `--pool-cores`, worker start-up line | No need | Pool already one worker per physical core (5 + host on a Ryzen 5 3600) |

## Already here or tried (checked 2026-10-21)

- **Merged on 2026-10-13 as the open PRs:** #2290 Anthropic `cache_creation_input_tokens` (`d958087b`) and #2140 `thinking_budget_tokens` (`e3b24adc`). 0.2.2's #2289 / #2141 are the same PRs; nothing more to port.
- **Own version exists:** the phone width (#2971). `c16cfe68` (2026-10-10) gave `.view` `min-width: 0; max-width: 100vw`; upstream also clips the tool row (`overflow: hidden`, name ellipsis), which ours lacks.
- **Own version exists:** a tool call written as text. D.L. CLI (`tools/dl_cli.py`, `TEXT_TOOL_CALL`) spots `<tool_call>` / `<function=` text and asks the model to resend (tests in `tools/test_dl_tool_calls.py`). It does not read `<=NAME>` or `<function:NAME>` as a call, which upstream's `serve/frontend.py` fix does.
- **Older version exists:** non-finite logits. Our engine has #879 (drop the cached state, end the slot); 0.2.2's #3465 batched retry of the prompt is not here.
- **Tried for this PC:** the context ladder (2026-10-20, 65,536 kept, RAM-bound), CPU workers per physical core (already so), idle GPU busy reading (2026-10-14 and 2026-10-21). See [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md).
- **Replaced by our own design:** API key optional. The web app uses the Cloudflare Access login; `/v1` clients keep the key.
- **Not here:** HIP verify-hang fix (`86d10ed8`), `STRATA_SPEC_WATCH`, 503 when the engine cannot start (#2496), one tok/s definition.
- **Gap found:** the web chat footer (`serve/web/app.js`) did not use the engine's decode speed (see the correction below). The Monitor already used `decode_tok_s`.

## Ported and deployed (2026-10-21, evening)

Four changes ported by hand onto `d53a4361`, engine rebuilt in `build-hip` (gfx1102) and installed as `engine/strata` (`BUILD.json` version `0.1.44.1+0.2.2-fixes`). Backups: `engine/strata.bak-0.1.44.1-qsa-20261021`, `engine/BUILD.json.bak-20261021`.

- **HIP verify-hang fix** (`86d10ed8`): `early_ple_flag_mode()` in `src/core/verify.cpp`, `launched_` / `launched_nr_` in `verify.hpp`. The first launch of each window graph raises the PLE flag before the launch (mode 2, the HIP default; `STRATA_VERIFY_EARLY_PLE_FLAG=0` turns it off). Upstream's pipelined/pre-launch path does not exist here, so only `Verifier::run` changed.
- **NaN retry** (`894f133b`, #3465): applied cleanly to `src/program/generate.cpp`.
- **Drifted tool-call openers** (`70f42407`, #3441): `<=NAME>`, `<function:NAME>`, `<NAME>` are read as `<function=NAME>` for a declared tool; one log line counts blocks returned as text. **Deliberate local difference:** upstream's #3075 rule (a call for an undeclared tool stays text) applies here only to a request that declared no tools. With tools declared, an undeclared name still comes back as a call, because our merged PR #2284 tests expect it and D.L. CLI turns typos into the real tool and answers made-up names with its tool list. Tests adapted: `serve/test_tool_call_envelope.py`, `serve/test_server.py` (case "other tools" removed).
- **One answer speed** (`fccfd343`, server part): `answer_speed()` in `serve/server.py` (console done line uses the engine's decode time; no huge rate for a one-token reply) and `serve/test_answer_speed.py`. The web chat footer (`serve/web/app.js`) now shows `timings.predicted_per_second` from the last streamed chunk. Correction to the gap noted above: the old footer divided by the time from the first token of any kind (thinking included), so it was not inflated by thinking; it did include server-side tool rounds and prompt reading between them, so it read low on MCP turns.

Checks:

- serve tests: 854 run; the same 6 failures as on unchanged `HEAD` (structured x4, `WebApp.test_page_and_files`, keep-awake), none new. `tools/test_dl_tool_calls.py` OK.
- Greedy answer check (`temperature 0`, 7 prompts incl. a 4K needle, thinking and a tool call), two runs per engine: every answer correct on both engines. The old engine itself gives different text on a repeat for 3 of 7 prompts (near-tie word choices), so bitwise identity is not a usable gate on this install; the new engine differs at the same kind of near tie.
- Same-day bench (`tools/strata_bench.py`, 3 runs), new vs old engine: chat decode 24.3 vs 23.8, 4K prompt 297.0 vs 296.2, 16K 326.2 vs 326.8 tok/s, agent decode 27.9 vs 26.4, agent first token 11.50 vs 11.45 s. All inside run-to-run spread. Results: `bench/results/v0.2.2-fixes-2026-10-21/{new1,old1}`.
- No hang, no error lines in the journal. A streamed reply's last chunk carries `timings`, and the console done line shows the same rate (21.5 tok/s).

## Sources

1. Upstream release notes 0.2.2, GitHub notification email pasted by the user in chat, 2026-10-21.
2. `git fetch upstream --tags`; `git format-patch | git apply --check` of each commit above onto `d53a4361`, 2026-10-21.
3. `strata-coder-iq1_m.log` and `journalctl --user -u strata-server` since 2026-10-10, 2026-10-21.
4. Earlier review: [Upstream Strata 0.2.0-beta and 0.2.1 Review](upstream-v0-2-releases-review-2026-10-20.md).
