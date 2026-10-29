---
title: "Upstream Strata 0.2.8 Review (2026-10-29)"
type: artifact
description: "What 0.2.7.1 and 0.2.8 bring (197 commits past v0.2.7) and which parts are worth porting to the RX 7600 XT setup"
status: active
tags: [upstream, v0.2.8, review]
created: 2026-10-29
updated: 2026-10-29
last_verified: 2026-10-29
---

# Upstream Strata 0.2.8 Review (2026-10-29)

## Summary

`upstream/main` is 197 commits past v0.2.7: 0.2.7.1 (2026-10-27) and 0.2.8 (2026-10-29, engine and Control 0.1.54). About 120 of them are DeepSeek on the Mac (Metal), the DGX Spark (Linux ARM64) and Intel Arc (SYCL), none of which runs here. Worth porting for this PC: the server's tool-call parser fixes, and the waits for RAM when an engine restarts. Nothing ported yet.

## Setup this was checked against

RX 7600 XT 16 GB (HIP), 31 GB RAM (about 3 GB available with the engine loaded), one slot (no `--batch`), `--spec 4` with MTP, `--expert-cache auto`, `--vram-reserve-mib 3584`, `--ple-gguf`, conversation cache 1024 MiB, `lazy_load` with `idle_unload_s` 28800, `tool_call_recovery: true` already in the config. Our `serve/frontend.py` differs from v0.2.7's (the #3796 port and the local rule that a well-formed call of an undeclared name stays a call).

## Worth porting

| What | Upstream | Why here |
|---|---|---|
| Tool-call parser: damaged JSON arguments repaired (trailing comma, single quotes, open brackets), `</parameter></tool_call>` without `</function>` is a call, the same inside the thinking, a stray `</think>`; quoted `<function=NAME>` in a string argument stays exact | `d7113273` (#4427 #4077), `77794e34`, `b72f56e0` (#4078); `serve/frontend.py` (+234 lines), `serve/test_tool_corpus.py` (279), `serve/test_tool_routes.py` | Ray's tool calls: a call lost as text or with a wrong argument is a failed step. Server only, no engine build. Needs a careful merge with our local parser rules; the tool corpus test comes with it |
| A left-behind engine is waited for until its memory is back (up to 120 s, was 10 s) | `01d6f7b9` (#4051); `serve/server.py`, `strata_control/procs.py` | 31 GB RAM with ~3 GB free: a reload after an unload or a restart can start while the old engine still holds memory. Python only |
| The engine waits up to 20 s for the RAM its expert arena needs before loading | `07d5ecfa` (#4051); `src/core/expert_source.cpp` | Same cause; engine change, needs a HIP build |

## Ported (2026-10-30)

- **Tool-call parser fixes** `77794e34`, `b72f56e0`, `d7113273` (#4078 #4427 #4077), applied with `git cherry-pick -n`: `serve/frontend.py`, `serve/server.py` (the `strata:tool_args_repaired_total` metric), new `serve/test_quoted_call_values.py`, `serve/test_tool_corpus.py`, `serve/test_tool_routes.py`. One conflict, at the end of a streamed call whose `</tool_call>` is missing: our scanner calls upstream's `function_done` state `done` (and closes the arguments there), so upstream's logic was taken with that name; keeping ours sent such a call without its arguments (corpus case `qwen-wrapper-close-left-out`).
- **Local differences in the tests:** `test_tool_corpus.py` skips the DeepSeek DSML specimens (this fork has no `serve/dsml.py`), and its `qwen-undeclared-name-is-text` case became `qwen-undeclared-name-is-a-call-here`, our local rule from the 0.2.7 port. `docs/DETAILS.md` describes the repairs; the README says so under the tools.
- **Not ported: the server's leftover-engine wait** `01d6f7b9`. It builds on upstream's `strata_control/procs.py`, which this fork does not have, and the case cannot happen here: `strata-server` is a systemd user service with `KillMode=mixed`, so stopping or restarting it ends every process in it, and our server sends QUIT and waits for the engine before starting another. The engine's own RAM wait (`07d5ecfa`) still needs a HIP build; not done.
- **Tests:** the three new files pass (11 tests, 66 subtests). The full `serve/` suite: see below. `serve/test_keepawake.py::test_service_holds_for_the_whole_request_including_early_close` fails before and after the port (not caused by it).

## Maybe later

- `cfa197e2` (#4474): `--expert-cache auto` leaves 256 MiB for what loads after it. With our 3584 MiB reserve the card is far from the 512 MiB warning; low value *(inferred from the config, free VRAM not measured)*.
- `587a4744` (#4518): the PLE table lock gives way to the conversation cache. The lock needs table + arena + 8 GiB of RAM, which 31 GB does not have, so the policy should not lock here *(inferred)*.

## Not applicable

- `3fcb2106` tool_call_recovery on by default: already on in our config.
- `9d3c8c36` 16-row verify and batch windows on HIP: for `--batch` and multi-card pipelines; we run one slot.
- `20a63cf0` route prior off on 12 GB NVIDIA; DeepSeek, Metal, DGX Spark, Arc/SYCL, Windows AMD Monitor readings, GUI/Control start waits, packaging.

## Sources

1. `git fetch upstream` 2026-10-29: `git log v0.2.7..upstream/main` (197 commits), tag v0.2.8 message, commit messages and `--stat` of the listed commits.
2. `strata-coder-iq1_m.json`, `free -g`, `strata-coder-iq1_m.log` on this PC, 2026-10-29.
3. User, chat, 2026-10-29: "Check the strata repo what is new and what is worth implementing".
