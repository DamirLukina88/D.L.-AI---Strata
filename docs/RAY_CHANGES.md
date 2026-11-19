# Ray: upstream syncs and benchmarks

How this fork follows upstream Strata releases, what was ported, and the community benchmark of 2026-11-01.

[← Back to the README](../README.md)

The inference engine is Strata, configured and optimized for AMD RDNA3 (ROCm/HIP). This fork last merged upstream
as a whole at v0.1.44.1 (2026-10-15). Later upstream releases are reviewed against this PC (AMD Ryzen 5 3600, 32 GB
RAM, Radeon RX 7600 XT 16 GB `gfx1102`, CachyOS, ROCm) and only the fixes that apply are ported by hand, so the engine
reads `0.1.44.1+0.2.12-fixes`. The reviews live in the shared memory store (project `strata`, pages named
`upstream-v0-2-*-review-*`); they are not part of this repository.

## Releases reviewed and ported

- **0.2.0-beta, 0.2.1 (2026-10-20):** reviewed, nothing merged.
- **0.2.2, 0.2.3 / 0.2.3.1 (2026-10-21 to 10-23):** crucial engine, vision and spec fixes ported, and 8-bit
  hyper-connection weights (`STRATA_HC_Q8=1`) enabled after an A/B benchmark.
- **0.2.5, 0.2.6 (2026-10-25):** CommonMark soft linebreaks, direct screenshot clipboard paste (`Ctrl+V`),
  window-level drag-and-drop, dynamic model load timeout scaling, safe shard removal guards,
  `require_messages(messages)` OpenAI-spec validation, 1-token health check speed guards, and stable GPU hardware
  telemetry IDs.
- **0.2.7 (2026-10-27)**, four fixes, engine `0.1.44.1+0.2.7-fixes`, each checked with tests and a short smoke test
  (no benchmark):
  - a failed read of the per-layer table no longer hangs the next request (#3602);
  - a checkpoint copy that runs out of memory is skipped instead of ending the engine (#3350);
  - no restore is attempted on a card too full to create its copy stream (#2409);
  - an MCP tool name written with `__` collapsed to `_` is read as the declared tool (#3796).
- **0.2.8, 0.2.9 (2026-10-29 to 10-31):** tool-call parser fixes and the parser code-fence fix ported; much of the
  rest is for Mac, DGX Spark, Intel, Strix Halo or the desktop app, which this install does not use.
- **0.2.10 (2026-11-03):** parser and server fixes first, then the HIP #4677 and #4350 engine fixes, with an A/B
  benchmark.
- **0.2.11 (2026-11-05):** server robustness ports and the Q5_0 dot precision fix in the C++/HIP engine, with a 4-leg
  paired A/B benchmark on the RX 7600 XT.
- **0.2.12 (2026-11-07):** the C++/HIP engine guards (MMQ row margin and Flag-B ordering), with a 4-leg A/B benchmark.
  Pull request #5477 (`GET /v1/models/{id}`) was submitted upstream and an AMD benchmark was posted to issue #4677.
- **0.2.13 (2026-11-09):** audited; nothing applies to this install and the release was skipped. Four small optional
  ports are noted.
- **0.2.14 / 0.2.14.1 (2026-11-15):** three server fixes ported: a request that ends early while the engine restarts
  no longer raises, `GGML_NO_BACKTRACE=1` keeps gdb out of a crashing engine or picture reader, and the server binds
  without a host-name lookup. Upstream's 0.1.60 engine (its own prompt kernels) was A/B'd against ours on this PC
  with the Coder IQ1_M: built here it read a 21,087-token prompt in 58.4 s against our 59.1 s and a 245-token prompt
  in 2.42 s against 2.12 s; upstream's prebuilt package was 3-6% slower on long prompts; output speed was the same
  within the run-to-run spread. The engine was not switched; both upstream builds are kept on the data disk for
  comparison with later releases. Also ported: the picture reader's start waits for READY or ERR and logs any other line
  instead of killing the reader on it (`4cce1ee4d`). Upstream's GPU-to-processor reader fallback (`c53e45a35`,
  `78eaaf1b0`) does not apply: this install's picture reader already runs on the processor.
- **0.2.15 (2026-11-16):** mostly fixes for upstream's desktop app, installer and Terminal; upstream's engine stays 0.1.60 (ours is unchanged).
  Ported: a declared boolean tool argument written `True` / `False` is the boolean (#5979). Not ported: the stop
  that refuses new requests (#6055; this server has no drain) and the monitor's MTP line (#5080; this engine does not
  report its drafter, so nothing would change).
- **0.2.16 (2026-11-17), parser part, ported 2026-11-18:** upstream moved its tree into `app/`, `engine/` and
  `terminal/`, so nothing cherry-picks. `serve/frontend.py`'s output parser (from `# --- output parser` to the end) is
  upstream's v0.2.16 copy, with this fork's one change kept (a tool given in the OpenAI `{"function": {...}}` shape is
  read by its name). That brings the tool-call recovery series (#6032 R1-R6), Claude's `<invoke>` dialect (#5969), types
  through `anyOf` / `oneOf` (#2371), a non-string parameter written twice counts once (#5493), linear streamed arguments
  and string values over 4 KB (#4686). In `serve/service.py`: a rejected undeclared call names the closest declared
  tool (#5904), a reply that ends in tool-call markup that is no call is written again once (`e05e6e0cc`,
  `"tool_markup_retry"`), and a reply cut inside a call carries `strata_unread_tool_markup` (`483778931`). Upstream's
  tests came with it (`serve/test_parser_*.py`, `test_tool_call_invoke.py`, `test_tool_markup_retry.py`,
  `test_tool_call_cutoff.py`); `test_tool_call_unclosed.py` is upstream's newer copy (prose after a call without its
  `</tool_call>` no longer confirms the call).
- **0.2.16, server part, ported 2026-11-18:** every socket operation of a request handler is bounded at 120 s
  (`STRATA_PEER_STALL_S`, 0 = unbounded), so a client that connects and sends nothing, or stops reading, no longer holds
  a handler or the engine's turn (#4759; the fork's own long waits, `/v1/ray/chat` and the event proxy, wait on the
  session daemon's socket, not the client's, and the proxy pings every 15 s). A stream's role chunk goes out with its
  first data, not before the prompt is read (#4758). `response_format` is allowed with tools on chat completions; from
  the first call on, the stream goes out unchecked (#4756). `max_tokens` / `max_completion_tokens` must be a whole number
  (`true`, `2.5` and other strings are a 400; `4096.0` and `"1024"` are taken), and `max_output_tokens` on
  `/v1/responses` takes `4096.0` and, as upstream's earlier #4036, -1 and 0 for no cap (#4037). `/v1/responses` honours
  `tool_choice` `"required"` and a named function (#4835). `POST /load` answers an engine that dies, sticks or is still
  starting with a 503 instead of closing the connection (`5205fc8bb`). Upstream's tests came with each
  (`test_connection_deadline.py`, `test_first_chunk.py`, `test_token_limit.py`, `test_load_answers.py`, and additions to
  `test_structured.py` and `test_responses.py`).
- **0.2.16, last two, ported 2026-11-18:** a tool call that max tokens cut short is replayed from a client's history
  with the parameters it already has, not as one parameter called `arguments` that teaches the model to write such
  calls (`0c99fcf85`; chat, Messages and Responses histories; `serve/test_cut_arguments.py`). `MALLOC_ARENA_MAX=2` on
  Linux for the server's own process (`mallopt`, as it is started by hand) and for the engine it starts, unless the
  variable is already set (`aeecf0f5d`, `serve/childenv.py`, `serve/test_childenv_arenas.py`). Upstream measured the
  server only (2-hour soak: RSS 312 MiB and +4.5 %/h by default, 252 MiB and +0.69 %/h with it; engine RSS the same
  band). Engine speed on this PC (2026-11-19, live server, coder IQ1_M, `tools/strata_bench.py --clients 4 --long`, one
  run each, 96 first, then 2): `MALLOC_ARENA_MAX=96` (glibc's limit for 12 threads) against 2: chat decode 27.4 / 28.6
  tok/s, prompt 4K 325.8 / 329.8, 16K 359.2 / 360.2, 32K 356.3 / 358.1 tok/s, agent decode 31.9 / 31.8, 4 clients 20.9 /
  20.7 tok/s. No difference beyond the run-to-run spread, so the cap stays. The server's memory was not measured here.
- **Audit, 2026-11-18:** the HIP ctest here failed `hip_q2_zero` (128 of 1024 Q2_0 half values +0 instead of -0 on
  this RX 7600 XT, gfx1102, ROCm 7.2.4): the signed-zero guard in `dq_q2_0` covered only gfx1012 on HIP < 7, gfx1151
  and gfx1200 / gfx1201. Upstream's `719b733e0` (#1540, in v0.1.45 and later), which keeps it on every HIP target, is
  ported.

## Community benchmark, 2026-11-01

An official community benchmark was run with `tools/strata_bench.py --long` against the live 64K context server:
- **Chat Speed & Latency**: 24.7 tok/s decode, 1.54 s time-to-first-token (10.1% latency improvement over baseline).
- **Prompt Prefill Throughput**: 308 tok/s at 4K, 337 tok/s at 16K, and 335 tok/s at 32K.
- **Agent Conversation Caching**: 68.5% cache hit rate with only 4 re-read tokens/session (94.4% reduction from 72
  tokens), delivering 27.5 tok/s decode across multi-turn sessions.

These numbers were measured with the GPU set to 2800 MHz / 198 W / -50 mV. After GPU crashes on 2026-11-14 the card
runs at 2500 MHz / 150 W / -50 mV. Re-run at that setting on 2026-11-16 (two runs): chat decode 22.6 and 25.9 tok/s,
32K prompt 339.8 and 362.3 tok/s, agent decode 28.9 and 33.5 tok/s, cache hit 67.3% (table in
[RAY_SPEED.md](RAY_SPEED.md)).

## Ray's tool choice, 2026-11-16

`tools/ray_toolchoice_bench.py` sends Ray 27 fixed prompts three times each: 15 that need no MCP server (arithmetic, a
definition, a conversion) and 12 that need one (weather, a page to open, a translation, the smart home).

- Before any change: every prompt that needs a server reached a right one (36 of 36 runs); of the prompts that need
  none, one turned on a server in all 3 runs (a trigger of the user's own catalog matched "in 45 minutes" in a speed
  question).
- The `mcp` tool now lists each server with a few words (about 5.4k characters down to about 2.1k; `mcp` action
  `list` has the whole descriptions). After it: 36 of 36 again, and the median time to the first text fell from 4.6 s
  to 3.1 s on the prompts without a server and from 39.8 s to 34.8 s on those with one.
- A model that asks for a server that acts outside or starts slowly (the browser, mail, the smart home) for a request
  with no link to it is told to answer directly or to give a reason. A live check on 2026-11-15 had seen "17 times
  23" turn on the browser; that did not happen again in 16 tries, so the cause is not known and the rule is a guard.

## Upstream pull request candidates

Fixes made here to code that came from upstream, kept small so a later port still finds upstream's version. Each one
could go upstream as its own pull request.

- `serve/test_server.py`: two classes were both named `VisionTempFiles`, so the first one's test (a refused request
  leaves no combined image file) never ran. Renamed to `VisionRequestFiles`; it then failed because the file had moved
  to `/dev/shm` with #874, so the test now looks there as well. Same in upstream v0.2.15.
- `tools/test_setup_golden.py`: the name lookarounds were `(?<![w.-])`, a literal `w` where `\w` was meant (same in
  upstream v0.2.9 to v0.2.15). No current baseline value changes with `\w`; a value such as `libstrata_x` would.
- Not changed here (Windows only, cannot be run on this PC): `tools/hip/build_windows.bat` configures only when
  `build.ninja` is missing, so on an existing build folder the `tests` argument, a new `STRATA_HIP_ARCHS` or a new
  ROCm root is ignored and the zip can be packaged for the old architectures. Always running the configure step
  would fix it.
- `src/program/generate.cpp` (same in upstream v0.2.15), three fixes in the serve loop, found by reading and built
  for HIP here; they matter only to a client that writes the engine's stdin protocol itself (serve/service.py never
  sends such requests), or to a damaged control-vector file:
  - the prompt + max_new check ran after a GENI request's image positions were written, into a table of
    max_context + 64 cells, so a longer GENI prompt wrote past it; and `n + max_new + 8` overflowed for a huge
    max_new. The check comes first now, written without the sum.
  - `--cvec` read each `direction.<layer>` tensor without checking its offset against the file.
  - a STOP read between the stdin thread queueing a GEN line and the main loop popping it was cleared as stale; the
    reader now clears it as it queues a GEN / GENI line (a BGEN is still cleared by the main loop, as before).
- `src/qwen35/q36_engine.cu` and `src/prefill/gemm.cu` (Qwen3.6 and the opt-in `STRATA_DENSE_MMQ=1`, neither used on
  this PC; built for HIP, not run): the MMQ row tables lacked upstream #5108's over-read margin (prefill.cpp has it);
  `--hybrid-rows` below 8 sent a hybrid layer's 2-8 token batch to `k_group` over the slot-sized blob array; an
  all-NaN logits row picked token id 0x7fffffff, which then indexed the embedding table.
