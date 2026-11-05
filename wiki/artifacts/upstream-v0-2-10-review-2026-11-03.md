---
title: "Upstream Strata v0.2.10 Review and Port Plan (2026-11-03)"
type: artifact
description: "708 commits since 0.2.9: port parser/server fixes first, then HIP #4677 and #4350 engine fixes with an A/B benchmark"
status: active
tags: [upstream, review, plan, v0.2.10]
created: 2026-11-03
updated: 2026-11-03
last_verified: 2026-11-03
---

# Upstream Strata v0.2.10 Review and Port Plan (2026-11-03)

## Summary

`git fetch upstream` on 2026-11-03: tag v0.2.10 (2026-11-02), `upstream/main` at ffa80d73, 708 commits since v0.2.9 (serve 57, src 323, apps 126, strata_control 121). None merged here. Our `main` still branches from 296b59d2 (2026-10-14) and gets upstream fixes ported by hand, as with 0.2.8 and 0.2.9.

## Not for this PC

- **DFlash2, the new default drafter.** Upstream's `strata_control/drafting.py` limits it to the plain Qwen3.8, Gyro and Unsloth families. "Not Swift, Coder or NVFP4": there are no acceptance numbers for those, so they start MTP. We run the Coder IQ1_M. Also, gfx1102 is not one of its tested cards (gfx1151, gfx1201), and our engine has no DFlash2 code (it came upstream with 7f97c35a, in v0.2.3). It stays MTP.
- **The all-cards split engine:** it needs 2 or 4 cards.
- **The 8 GB card walk to 128K context:** our card has 16 GB. Context is limited by system RAM here, not VRAM (see [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md), 2026-10-20).
- **The ISTA-DAS Coder and DeepSeek.** Upstream added a Linux RX 7000 DeepSeek package that includes gfx1102 (c14eb72d), untested there. It would be a 191 GB download, and with less RAM it runs slower (upstream measured 15 tok/s at 24 GB RAM on one R9700). User, 2026-11-03: not now.
- **Mac, Windows (#4733 disk priority, #3431 HIP arena aliases), SYCL, DGX Spark, and the `apps/host` desktop chat fixes.** We use `serve/web`, not `apps/host`.
- **The Anthropic and Responses route fixes (#4663, #4700 tool search; #4838 context-overflow wording).** D.L. CLI, the web app and the Android companion (a WebView around the web app) all use `/v1/chat/completions`.
- **The #4590 penalty window.** Our sampling sets no penalties.
- **#4741 (a BF16 projection in a pack)** applies cleanly, but our pack has no BF16 projection.

## Plan

### Step 0: commit the local phone/music work first

The uncommitted changes in `serve/server.py`, `tools/dl_cli.py`, `tools/dl_sessiond.py`, `tools/phone_mcp.py`, and the new `tools/pc_music_mcp.py` and `tools/test_pc_music.py`, go in one local commit. Every port after that gets its own commit (User, 2026-11-03).

### Step 1: server and parser ports (no rebuild, no model time)

**Result (2026-11-03):** ported #4701 (49b880c0 + 05074109), #4751 (35057071 alias part; `_tool_references` is not in this fork), the server half of 9aea047e, and the two remaining unclosed files of 5c0259e2 (`hip_speed_scores`, `/proc/meminfo`; the others were already closed here). Not ported: a5112326, because this fork has no ready-file publishing. Tests: `serve/test_param_end_options.py` (upstream's, plus one local case: `write_file` streamed one character at a time, which fails on the old parser), `serve/test_tool_prefixes.py` (upstream's cases; the undeclared case is adapted to the local rule that an undeclared call stays a call), and `serve/test_abort_sync.py` (fails with the guard turned off). Full `serve/` suite: 911 passed, 11 skipped, 0 failed; the old cache-tag failure passed too. Live check (`strata-server` restarted 22:21): `write_file` with a file that lists the three closing tags, `reasoning_effort` low, 2 runs (a first one at 3,000 max tokens spent them all thinking). Both times the file came back cut after the line before the tags. The turn was 181 tokens with `finish: stop`, about 30 of them the call, so the Coder IQ1_M itself ends the turn after writing `</tool_call>` (in Qwen's format a turn ends there). The parser did not cut it: the same text with the rest after it is kept whole (the streamed local test). So #4701 helps here only when the model keeps writing after the tags, and this model does not. A file with these tags needs another way, for example writing them escaped or adding them with a shell command. A plain `write_file` call and the other ports work.

None of these applied cleanly with `git apply --check` except the e9b4bf00 tests, so each is ported by hand with its tests.

| Upstream | What it fixes here | Files |
|---|---|---|
| 49b880c0, 05074109, e9b4bf00 (#4701) | A file write whose content lists closing tags on their own lines was cut short, and the rest leaked into the answer. D.L. CLI writes files through tool calls. | `serve/frontend.py`, parser tests |
| 35057071 (#4751) | `tools.write`, `functions.write` and `default_api.write` count as the declared tool `write`. | `serve/frontend.py` + test |
| 9aea047e (server part) | A trailing `DONE` after an `ERR` no longer goes to the next request, which made every later answer arrive one request late. Only the server half is ported; the engine half is in the DeepSeek engine. | `serve/server.py`, `serve/test_abort_sync.py` |
| 5c0259e2 (#4654) | The sampler and HIP probe files get closed, so the ResourceWarning lines stop. | `serve/server.py` |
| a5112326 | A stop that arrives just as the ready file appears exits cleanly. | `serve/server.py` |

**Test:** the new tests, `serve/test_tool_corpus.py` and the full `serve/` suite (`uv run --with pytest`). Before the 0.2.9 port it was 886 passed, with one cache-tag failure that was already there. Then restart `strata-server` and check that a `write_file` call with closing tags in its content writes the whole file.

### Step 2: HIP engine fixes (rebuild plus an A/B benchmark, at a time the user picks)

- **243fdb21 (#4677).** In the single-request speculative path, a request's last verify window committed rows the client never got. The parked snapshot was then refused, and about 6% of the prompt was read again. The fix is HIP-only and on by default (`STRATA_SERVE_STOP_BOUND=0` turns it off). It matches our setup: one slot, MTP `--spec 4`, conversation cache. Expect a higher agent cache-hit rate (68.5% on 2026-10-25).
- **e1b27d54 (#4350).** After a fatal GPU error the engine exits, and the server starts it on the next request, instead of failing every later request. The server part goes with it.
- **5a13c34f (#4671), optional.** The PLE table lock raises the soft memlock limit first. It applies cleanly; we have not seen memlock errors in the last 14 days of logs.
- **#4846 (eb891724, 067b7433, 43543e9b), optional.** When RAM is short at the expert arena, read the experts from the file instead of stalling. Eight hunks conflict. Our config keeps every expert resident on 32 GB RAM, so this guard would only matter in a low-RAM start.

**Steps:** back up `engine/strata`, port, build `build-hip`, run the new `serve_stop_bound_test`, and do a smoke test with the model unloaded. Then a `tools/strata_bench.py` A/B (off, on, off, on), with the server stopped and run as its own `systemd-run --user -p MemorySwapMax=0` unit (see the 2026-10-31 OOM gotcha in the [0.2.9 port plan](upstream-v0-2-9-port-plan-2026-10-31.md)). That takes about 30-40 min of model time, so ask first.

**Step 2 result (2026-11-03):** ported #4677 (243fdb21) and #4350 (e1b27d54, engine and server) by hand; the optional #4671 and #4846 were left out. Committed 63a139f1. `build-hip` built in 87 s; deployed as `engine/strata`, version `0.1.44.1+0.2.10-fixes`. Rollback: `engine/strata.bak-20261103` and `engine/BUILD.json.bak-20261103`. Tests: `serve_stop_bound_test` 2,736 cases passed; `serve/test_fatal_gpu_restart.py` 7 passed. Smoke test: a `read_file` call came back right, and the second turn of a 6.4K-token conversation reused 6,352 of its 6,414 prompt tokens.

A/B (22:51-23:24), the new binary with `STRATA_SERVE_STOP_BOUND=0` (off) against the default (on). `tools/strata_bench.py`, Ray's config with `lazy_load` false, each leg a fresh server as its own `systemd-run --user -p MemorySwapMax=0` unit, `strata-server` stopped; medians:

| | off 1 | on 1 | off 2 | on 2 | on / off |
|---|---:|---:|---:|---:|---:|
| chat decode tok/s | 24.4 | 23.2 | 26.0 | 26.5 | -1.4% |
| chat first token, s | 1.622 | 1.691 | 1.704 | 1.746 | +3.3% |
| 4K prompt tok/s | 305.1 | 295.6 | 300.9 | 306.8 | -0.6% |
| 16K prompt tok/s | 335.8 | 333.1 | 331.5 | 337.7 | +0.5% |
| agent cache hit % | 67.09 | 67.13 | 67.09 | 67.23 | +0.1% |
| agent tokens re-read | 4 | 5 | 3 | 5 | (all tiny) |
| agent turn first token, s | 11.40 | 11.37 | 11.15 | 11.34 | +0.7% |
| agent decode tok/s | 28.9 | 29.8 | 29.5 | 29.9 | +2.2% |

0 errors in all four legs, and no fatal GPU line. Every difference is inside run-to-run noise. The bench's agent turns already re-read only 3-5 tokens, so they never hit the case #4677 fixes (upstream measured it with `--batch 8` on 4 x R9700). It stays on, as upstream's default; it is harmless here. Not measured: the #4350 check (`hipPeekAtLastError` once per decode window) against the old binary, since both legs used the new one. A real GPU fault was not tried.

## Related

- [Upstream Strata v0.2.9 Review (2026-10-31)](upstream-v0-2-9-review-2026-10-31.md)
- [Plan: Code-Fence Parser Fix and gfx11 Chunked GDN (2026-10-31)](upstream-v0-2-9-port-plan-2026-10-31.md)

## Sources

1. `git fetch upstream` 2026-11-03; `git log v0.2.9..upstream/main`; `git apply --check` of each listed commit against the working tree; `git show upstream/main:strata_control/drafting.py`.
2. Release notes: https://github.com/Niko1221/Strata/releases/tag/v0.2.10
3. User, chat, 2026-11-03.
