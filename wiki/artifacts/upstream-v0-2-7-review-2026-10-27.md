---
title: "Upstream Strata 0.2.7 Review and Fix Port (2026-10-27)"
type: artifact
description: "What 0.2.7 brings, what applies to the RX 7600 XT, and the four fixes ported into engine 0.1.44.1+0.2.7-fixes"
status: active
tags: [upstream, v0.2.7, engine, rx7600xt]
created: 2026-10-27
updated: 2026-10-27
last_verified: 2026-10-27
---

# Upstream Strata 0.2.7 Review and Fix Port (2026-10-27)

## Summary

Upstream released 0.2.7 (engine 0.1.52) on 2026-10-27 (367 commits past v0.2.6). Most of it targets hardware or models not used here. Four fixes that match our config were ported by hand into `engine/strata`, now **`0.1.44.1+0.2.7-fixes`**. None of the upstream commits applied cleanly to our tree (our main is not a descendant of upstream; 10 of 10 dry-runs conflicted).

## Ported (2026-10-27)

| Fix | Upstream commit | What changed here | Check |
|---|---|---|---|
| #3602 PLE reader: after a failed read the next ticket waited forever | `ebe3383a` | `src/ngram/ple_reader.cpp` (+ sycl copy); `src/ngram/ple_reader_stress_test.cpp` + CMake target `ple_reader_stress_test` | Upstream stress test **hangs on our old reader** ("a ticket issued after a failed read never returned") and passes on the patched one |
| #3350 checkpoint copy out of memory ended the engine | `f62589fd` | `src/program/generate.cpp` (+ sycl): `checkpoint_failure_is_survivable()`, checkpoint skipped with a stderr line; `STRATA_TEST_COPY_FAIL_AT=N` test hook added by hand to `src/core/conversation_copy.hpp` | Builds; not provoked on the live model |
| #2409 restore on a nearly full card | `8c030148` | Our copy streams are per-thread with no pool (upstream's pool from `3478382e` was not ported), so `copy_stream_ready()` checks only this thread's stream. `restore_fits()` + `kRestoreFirstUseMib` (64) in `include/strata/program/conv_cache.hpp`; guard before park/restore in `generate.cpp`: a card without its copy stream and < 64 MiB free gets no restore (snapshot back to the cache, prompt reread) | `conv_cache_test` PASS (upstream's cases); snapshot/validation/cache tests pass |
| #3796 tool names | `805ebe17` | `serve/frontend.py`: a declared `mcp__a__b` written as `mcp_a_b` is that tool. `serve/server.py`: `strata_rejected_tool_calls` in replies, `tool_calls_unread` total, `strata:tool_calls_unread_total` metric | `serve/test_tool_name_alias.py` (3 tests, trimmed) OK; `test_server` + `test_frontend`: 358/359, the one failure is `WebApp.test_page_and_files` expecting `"web/app.js"` without our `?v=` cache tag (pre-existing) |

- Gotcha (#3796): this tree keeps a **local rule** that a well-formed call of an *undeclared* name stays a call when the request declared tools (D.L. CLI answers a made-up name with its tool list; see `OutputParser._callable`). Upstream's tests that expect such names to stay text were dropped, and the rejected marker only fires for requests that declared no tools.
- Not ported: #1503 (one conversation parked with another's K/V) only happens with `--batch`, which our config does not use.

## Deployment and smoke test

- Backups: `engine/strata.bak-20261027`, `engine/BUILD.json.bak-20261027`. Built with `ninja -C build-hip strata` (gfx1102, Release).
- Smoke test after `systemctl --user restart strata-server` (no benchmark): lazy load + "OK" 44 s; a declared tool `mcp__clock__get_time` returned as a real call (30 tok/s); two interleaved ~8.2K-token conversations, each restored from the conversation cache (8,190 / 8,191 tokens in 123–147 ms) and answered with its own codeword (ALPHA-7 / BRAVO-3) in ~1 s. No errors, no skipped restore or checkpoint in the journal or `strata-coder-iq1_m.log`.

## Not applicable on this PC

Route prior default (NVIDIA ≤ 13 GiB only; our engine has `STRATA_ROUTE_PRIOR` opt-in and the config already uses `STRATA_ROUTE_RESIDENT=0.5`), RX 9000/R9700 (RDNA4), all DeepSeek items (needs 46 GB+ RAM), two-card items (layer-major prefill, pipelined batches, split-serve, `--prefill-pipe`), `--ple-io ram` (28.8 GB table), `--slots 2`, `--kv q4_0`, huge pages, desktop app and Terminal changes, French.

## Open candidates

- Web chat page: scroll-follow fix (#4014, `89a68d88`, `9a0462a0`), saved chats with search/rename/delete and edit/rewind/branch (`chatstore.js`, `history.js`, `chats-ui.js`), KaTeX math, sandboxed HTML/SVG preview, Unload button. Our `serve/web/app.js` keeps only the theme in localStorage.
- Experiments needing a benchmark (ask first): `--mtp-draft-vocab data/draft_vocab_en.bin` (upstream +2.7–3.1% English decode; flag and file already here); `STRATA_KVA=1` faster long prompts (not in our engine; quality risk).

## Sources

1. Upstream release notes: `https://github.com/Niko1221/Strata/releases/tag/v0.2.7` (GitHub API, accessed 2026-10-27).
2. Upstream commits `ebe3383a`, `f62589fd`, `8c030148`, `805ebe17`, `f8ff3420` (tag `v0.2.7`).
3. User, chat, 2026-10-27 (asked to port #3602, #3350, #2409, #3796, build, short smoke test only).
