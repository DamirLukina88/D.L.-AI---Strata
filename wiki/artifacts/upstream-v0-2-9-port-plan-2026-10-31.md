---
title: "Plan: Code-Fence Parser Fix and gfx11 Chunked GDN (2026-10-31)"
type: artifact
description: "Port upstream 209dcadb by hand with its tests; measure STRATA_GDN_CHUNKED=1 on the RX 7600 XT for speed and quality before turning it on"
status: active
tags: [upstream, plan, parser, gdn]
created: 2026-10-31
updated: 2026-10-31
last_verified: 2026-10-31
---

# Plan: Code-Fence Parser Fix and gfx11 Chunked GDN (2026-10-31)

## Summary

Two items from the [v0.2.9 review](upstream-v0-2-9-review-2026-10-31.md). Status: item 1 ported, tested and live-checked 2026-10-31 (commit d9a56bb7 and the record after it); item 2 not started (User, chat, 2026-10-31).

## 1. Parser: tool calls inside code blocks are quotes (upstream 209dcadb, #4702 #4703)

**What changes in `serve/frontend.py` (`OutputParser`):**
- A fence closes only with a fence at least as long as the one that opened it (a ```` block can show ``` inside it).
- A 4-space indented block after a blank line counts as code, so a call written inside it is quoted text, not run.

**Steps:**
1. Read upstream's diff of `serve/frontend.py` (51 lines) and our `OutputParser` around `self.fence, self.line, self.ticks` (line ~1143), and map the new state (`_prev_blank`, `_indented`) onto our version. The 0.2.8 port showed our parser is older than upstream's (our `done` is upstream's `function_done`).
2. Port it by hand, keeping our local rule (a call to an undeclared name stays a call).
3. Bring the tests: `serve/test_parser_markdown_code.py` (new in upstream, 80 lines) as is, and the `serve/test_parser_track.py` changes (20 lines) merged into ours.
4. **Test:**
   - The new tests, then the full `serve/` suite. Before: 878 passed, 2 failures that were already there (`test_keepawake`, `test_server` WebApp cache tags).
   - `serve/test_tool_corpus.py` must stay green, since every repaired-call case runs through the same parser.
   - Add one case of our own, from a real Ray answer: a reply that shows a `run_command` call inside a ```` block must come back as text with no tool call.
5. **Live check:** restart `strata-server`. Ask Ray in the Code tab "show me how a tool call to read_file looks, in a code block": no tool runs. Then "read notes.txt": the call still runs.
6. README, `docs/DETAILS.md` ("What the parser repairs, and what it leaves"), the wiki, then commit and push to origin.

**Result (2026-10-31):** ported by hand; upstream's frontend.py hunks matched our code once moved (our lines ~1092-1260). `serve/test_parser_markdown_code.py` taken as is plus one local case (`run_command` in a ```` block with an inner ``` block); `test_parser_track.py` patch applied cleanly. New tests, `test_parser_track` and `test_tool_corpus`: 16 passed. Full `serve/` suite (pytest via `uv run --with pytest`, no pytest in system Python): 886 passed, 11 skipped, 1 failed, the old `test_server.py::WebApp::test_page_and_files` cache-tag failure; `test_keepawake` passed this run. `docs/DETAILS.md` has a new bullet after "What the parser repairs"; README has no parser section, left alone. `strata-server` restarted. Live check over `/v1/chat/completions` with `read_file` declared (key `STRATA_API_KEY` from `~/.config/dl-ai/secrets.env`, read with the user's yes): "show me how a tool call to read_file looks, in a code block" came back as text in a ```xml block, no tool call (48 s with the lazy model load); "read notes.txt" came back as `read_file` `{"path":"notes.txt"}` (5 s). The quoted answer had no `<tool_call>` line and no closing fence; fed to `OutputParser` offline, the same text with both is returned whole, so that is what the model wrote, not the parser. Done over the API, not in the Code tab UI.

**Risk:** a real call that the model wraps in a fence would now be shown and not run. Upstream accepted that; the corpus test shows whether any of our recorded calls are fenced.

**Time:** about 1-2 h of work, tests about 5 min, no model benchmark.

## 2. `STRATA_GDN_CHUNKED=1` on the RX 7600 XT (gfx1102)

**What it is:** the gated-delta-net recurrence for the prompt read, in chunks on the matrix cores, for prompt chunks of 64+ tokens. It is in our engine already (`src/prefill/kernels.cu`, the gfx11 "Aurora" kernels) and off by default. Upstream qualified it only for gfx12 (R9700: +3.5% at 4K, +5.5% at 16K, KL mean 0.0025 / max 0.038, 55 vs 56 of 61 tasks, 30-min soak). gfx11 was never qualified.

**Our config already sets** `STRATA_GDN_CONVL2=1`, `STRATA_GDN_PP=2`, `STRATA_GDN_HEAD=1` and `STRATA_GDN_NOY=1`, so the test is the chunked switch on top of these.

**Steps, each with a stop rule:**
1. **Kernel parity, no model, about 2 min:** run the gfx11 GDN parity tool in `build-hip` (`gdn_parity` / `hip_gdn_rec_head`, or build `gdn_rec_parity` if it is not there) with the chunked path against the serial one. Stop if it fails on this card.
2. **Speed, about 30-40 min, ask first:** `tools/strata_bench.py` on the current settings, then with `STRATA_GDN_CHUNKED=1` added to the config's `env`. Prompt tok/s at 4K and 16K (3 runs each, medians), plus time to first token on Ray's real prompt (about 19k characters before the first message). Run the two in alternating order (off, on, off, on) to cancel drift from heat and the expert cache. Keep it only if it is faster beyond run-to-run noise.
3. **Quality, about 30-60 min, ask first:** `tools/quant_quality.py run` on the fixed set `data/quant_quality/v1` (code, docs, English, other languages, an agent transcript), once with the switch off as the reference and once on, then `compare`. Pass if the top-1 agreement is at least 99% and mean KL is at most about 0.005, in the range upstream accepted. It starts its own engine, so `strata-server` is stopped during the run (31 GB RAM).
4. **Agent check, about 30 min:** `tools/dl_agent_bench.py --tasks quick` (bugfix, roman, intervals) with the switch on, compared with the last quick run. No task should get worse.
5. **If it passes:** add `STRATA_GDN_CHUNKED=1` to `strata-coder-iq1_m.json` `env`, restart the server, and use it for a day. Document the measured numbers in `docs/DETAILS.md` and the wiki. As a contribution upstream it would be a hardware report for gfx11 under `docs/COMMUNITY_BENCHMARKS.md`, with the same-day comparison and what was not tested.
6. **If it fails:** record the numbers in the wiki and leave it off.

**Total model time:** about 1.5-2.5 h, all of it asked for before it starts (the long-benchmark rule). Ray is slow or unavailable while it runs.

## Order

1 first: it is independent, needs no model time, and is a safety fix. 2 after, at a time when Ray is not needed.

## Sources

1. User, chat, 2026-10-31.
2. `git show 209dcadb`, `bee469c4`, `ac3e0e17` (upstream, fetched 2026-10-31); `strata-coder-iq1_m.json`; `tools/strata_bench.py`, `tools/quant_quality.py` docstrings.
