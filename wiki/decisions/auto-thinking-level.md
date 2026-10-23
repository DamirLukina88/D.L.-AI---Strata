---
title: "Auto Thinking Level (/effort auto)"
type: decision
description: "Opt-in /effort auto: rules pick none/low/medium/high per turn, raise to high on failures; measured level costs"
status: active
tags: [effort, thinking, dl-sessiond, ray]
created: 2026-10-23
updated: 2026-10-23
last_verified: 2026-10-23
---

# Auto Thinking Level (/effort auto)

## Summary

2026-10-23: Implemented and tested in `tools/dl_effort.py`, `tools/dl_sessiond.py`, and `tools/dl_cli.py` (`tools/test_dl_effort.py`, `tools/test_dl_sessiond.py`). Opt-in `/effort auto` in `tools/dl_sessiond.py` resolves each turn to a concrete level with rules in `tools/dl_effort.py`: plan mode, code/errors/@file, coding verbs and follow-up complaints get `high`; small talk (incl. Rey/Rae/Wray/Ring) and home/clock commands get `none`; explanations `medium`; short questions `low`; anything else `high`. A turn's own level (voice toggle sends `none`) still wins. Inside a turn, `execute_agent_loop` raises to `high` once after a tool error, malformed JSON arguments, non-zero exit, repeated identical call, loop guard, text-tool-call retry or finish-check send-back; never lowers. The server never sees `auto`, so the default path stays byte-identical. Replayed across 170 historical prompts in `~/.dl_sessions` and `~/.local/state/dl-ai/sessions` (`high`: 164, `none`: 5, `low`: 1, zero downward misclassifications on coding tasks). Why no classifier call: one engine serves one request at a time, and an extra call can evict the session from one of 4 cache slots (cold re-read ~9.8 s); keyword/length scorers alone measured near chance (LiteLLM AUC 0.52). Gotchas: a level is only a prompt sentence (no token cap; reasoning_budget_tokens exists but nothing sends it); changing level is cache-cheap only with effort_position end (set in the user's config, not strata-q2_0.json). Measured (one run per level, Coder IQ1_M, RX 7600 XT): weather email sweep 2026-10-17 none 90/501 s/30 calls, low 90/343 s/16, medium 97/209 s/6, high 97/183 s/5, so lower thinking was slower on agent work; quick coding sweep 2026-10-15 low failed roman, medium and high passed.

## Sources

1. User, chat, 2026-10-23.
2. `reports/Automatic thinking level selection.md` and `research_notes/Automatic thinking level selection/` — written 2026-10-23.
3. `~/.cache/strata/bench/weather_reasoning/20261017-190322-sweep/report.md`, `/mnt/data/DL-AI-workspace/bench/sweep-20261015-1911-quick-low.md` — read 2026-10-23.
