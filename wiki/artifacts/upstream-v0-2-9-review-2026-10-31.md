---
title: "Upstream Strata v0.2.9 Review (2026-10-31)"
type: artifact
description: "138 commits since 0.2.8: worth porting here are the parser code-fence fix and a trial of the gfx11 chunked GDN prompt path"
status: active
tags: [upstream, review]
created: 2026-10-31
updated: 2026-10-31
last_verified: 2026-10-31
---

# Upstream Strata v0.2.9 Review (2026-10-31)

## Summary

`git fetch upstream` on 2026-10-31: tag v0.2.9 (2026-10-31) at c62d5e3a, 138 commits since v0.2.8, none merged here. About 30 are Mac (Metal), DGX Spark, Intel or gfx1151 (Strix Halo) only, and much of the rest is DeepSeek, NVIDIA (GDN tensor cores, replicas, shared arena) or the desktop app (`apps/host`), which this install does not use.

## Worth it here

- **209dcadb, parser: code fences and indented code blocks.** A fence closes only with one as long as the one that opened it, and a 4-space indented block counts as a quote, so a tool call shown in an answer is not run (#4702, #4703). Ray writes code blocks often. It does not apply cleanly to `serve/frontend.py` (patch fails at line 1143), so it needs a manual port with its tests (`serve/test_parser_markdown_code.py`, `test_parser_track.py`).
- **Try `STRATA_GDN_CHUNKED=1` on the RX 7600 XT (gfx1102).** The engine here already has the gfx11 chunked recurrence for the prompt (`src/prefill/kernels.cu`), off by default. Upstream turned it on only for gfx12 (bee469c4; R9700: +3.5% at 4K, +5.5% at 16K, KL mean 0.0025), and ac3e0e17 lowered the gfx12 start to 64 tokens "as on gfx11". gfx11 was not qualified. It needs a measurement here (prompt speed and quality) before it becomes the default. No build needed.

## Not needed or not here

- 3282c613 (a tool the conversation already called counts as declared): this fork already returns a call to an undeclared name as a call.
- 8f13b8c4 (a line when the card's architecture is not in the build): the engine here is built for gfx1102 only; small value, and the patch does not apply cleanly.
- ab083a69, ea52e55c (chat renders 10 times a second, only the streaming message): `apps/host` React chat, not `serve/web`. The same idea could apply to the web Code tab, which is not measured.
- 4a75fa2b (gateway "Request cancelled" after [DONE]): `apps/host` gateway.
- dd63f88f (warm-up past the KV cache): the Qwen3.6 engine only.
- ad4755c2 (the 1-bit sets are weaker on long, careful work): about upstream's Unsloth DeepSeek downloads, not this Qwen IQ1_M.

## Related

- [Plan: Code-Fence Parser Fix and gfx11 Chunked GDN (2026-10-31)](upstream-v0-2-9-port-plan-2026-10-31.md) - how both items get ported and measured

## Sources

1. `git fetch upstream` 2026-10-31; `git log v0.2.8..upstream/main`, tag v0.2.9 message, `git show --stat` and `git apply --check` of the listed commits.
2. User, chat, 2026-10-31.
