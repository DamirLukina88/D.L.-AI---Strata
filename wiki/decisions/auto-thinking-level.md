---
title: "Auto Thinking Level (/effort auto)"
type: decision
description: "Default /effort auto: rules pick none/low/med/high per turn, raise on failures, GUI switch in Sampling drawer, replaces manual voice toggle"
status: active
tags: [effort, thinking, dl-sessiond, ray]
created: 2026-10-23
updated: 2026-10-23
last_verified: 2026-10-23
---

# Auto Thinking Level (/effort auto)

## Summary

2026-10-23: Implemented `/effort auto` thinking level selection and mid-turn escalation in `tools/dl_effort.py`, `tools/dl_sessiond.py`, and `tools/dl_cli.py` (`tools/test_dl_effort.py`, `tools/test_dl_sessiond.py`, `tools/test_dl_auto_raise.py`). Made `auto` the default session effort level and added an "Auto" switch option in the Web UI Sampling and Thinking drawer (`#s-thinking`). Removed the legacy manual "Skip thinking for voice prompts" switch because `/effort auto` automatically assigns `none` to spoken greetings, small talk, and home automation commands while allowing complex voice requests to think.

In `/effort auto`, the thinking level is chosen per turn without an extra model call or classifier:
1. **Per-turn rules** (`dl_effort.pick(prompt, voice=False, mode="act", last_reply="")`):
   - `mode == "plan"` -> `high "plan mode"`
   - `@file` reference, fenced code, traceback, or `Error:`/`Exception`/`exit code` -> `high "code or error"`
   - coding or planning verbs (fix, debug, refactor, implement, build, write a script/function/test, optimize, review, migrate, design, plan, why does/doesn't) -> `high "coding task"`
   - follow-up complaint right after an assistant reply ("that's wrong", "didn't work", "still", "why?") -> `high "follow-up on a failed answer"`
   - greeting, thanks or small talk (hi/hello Ray, also Rey/Rae/Wray; how are you; introduce yourself; what can you do), at most 12 words -> `none "small talk"`
   - home command (turn on/off, switch, dim, set, open, close + light/AC/plug/printer/camera), at most 20 words -> `none "home command"`
   - explain/summarize/compare/translate/"what is", no code words, at most 60 words -> `medium "explanation"`
   - question of at most 20 words with no code words -> `low "short question"`
   - anything else -> `high "default"`
   Spoken prompts (`voice=True`) raise word limits slightly (+6 words for small talk, home commands, and questions; +15 words for explanations).
   The server never receives `"auto"`: the daemon always sends a concrete level (`none`, `low`, `medium`, `high`).
2. **Mid-turn escalation** in `execute_agent_loop`:
   When `effort_auto` is set, `seen` tracks tool calls `(fn_name, json.dumps(args, sort_keys=True))`. After each tool result, `dl_effort.raise_reason` checks for:
   - result starting with `"Error"` -> `"tool error"`
   - `[Command exited with code N]` with `N != 0` -> `"command failed"`
   - repeated identical tool call -> `"repeated tool call"`
   Additionally, the loop-guard ("thinking loop"), text-tool-call retry ("tool call sent as text"), and finish-check send-back ("sent back by the finish checks") trigger mid-turn escalation. The first time any failure occurs and only if `effort != "high"`, effort is escalated to `"high"`, `session_context["effort"] = "high"`, and `Auto thinking: raised to high (<reason>)` is emitted. Effort is never lowered mid-turn.
3. **Default Level & GUI Switch:**
   `Session.effort` defaults to `"auto"`. The Sampling drawer in the Web UI (`#drawer`) includes segmented control options: `Auto` (default), `Off`, `Low`, `Medium`, and `High`. Selecting a level applies it to the active CLI session daemon via `/effort <level>`. The Code tab header scaffold displays the active effort badge (`AUTO`).
4. **Why no separate classifier or model call:**
   Strata runs one engine on one GPU, serving one request at a time. A second pre-call to classify difficulty would serialize latency and take one of four conversation-cache slots, risking evicting the session's prompt cache. Re-reading the session's system prompt and tools from cold costs ~9.8 s for 2,295 tokens on this hardware. Furthermore, LiteLLM's benchmark showed keyword/length heuristic scorers alone predict difficulty no better than chance (AUC 0.524 pooled, 0.420 on chat prompts), while objective runtime failure events provide definitive escalation signals.
5. **Status & Measurement:**
   Rule logic, daemon session persistence, and mid-turn escalation are unit-tested without a model (`tools/test_dl_effort.py` [14 tests], `tools/test_dl_sessiond.py` [13 tests], `tools/test_dl_auto_raise.py` [6 tests]), and verified live on `dl-ai-sessiond.service` across the canonical prompts. Systematic empirical evaluation across a response matrix (comparing fixed levels, rules, and escalation across hundreds of voice, chat, and coding prompts) is pending user approval for multi-hour GPU benchmark runs. See [Automatic thinking level selection.md](../../reports/Automatic%20thinking%20level%20selection.md).

## Sources

1. User, chat, 2026-10-23.
2. `reports/Automatic thinking level selection.md` and `research_notes/Automatic thinking level selection/` — written 2026-10-23.
3. `~/.cache/strata/bench/weather_reasoning/20261017-190322-sweep/report.md`, `/mnt/data/DL-AI-workspace/bench/sweep-20261015-1911-quick-low.md` — read 2026-10-23.
