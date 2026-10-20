---
title: "D.L. CLI Keeps Its Task: Trim Protection, PLAN.md, Memory Files, Finish Checks"
type: decision
description: "Why the CONTRA run lost its task to trimming (2026-10-19) and the fix: protected user messages, PLAN.md, project_memory, finish checks"
status: active
tags: [dl-cli, context, trimming, plan, memory, agent-quality]
created: 2026-10-19
updated: 2026-10-20
last_verified: 2026-10-20
---

# D.L. CLI Keeps Its Task: Trim Protection, PLAN.md, Memory Files, Finish Checks

## Summary

Gotcha found 2026-10-19: compact_history (tools/dl_cli.py) kept only the first and the latest user-role message, and D.L. CLI's own notes (TEXT_CALL_NOTE, TURN_CAP_NOTE, the trim note) are user-role messages. After one note became the latest, the real instruction was trimmable; the approved plan lived only in an assistant message and EXECUTE_PLAN said 'the plan' without a location. The CONTRA session (6 h, YOLO) ended with three user messages left (create a folder, the trim note, the text-tool-call note), so the model said 'the user hasn't asked anything yet' and stopped after fixing one harness check, with about 2/3 of its 34-step plan undone. Fix (branch dl-memory-fix, worktree /mnt/data/Strata-memfix, in rollout 2026-10-19): protected_user_messages keeps the user's own messages (notes start with '[D.L. CLI', budget 25% of the trim target); /act from Plan mode writes PLAN.md and /planfile attaches one; build_dl_system_prompt adds a project_memory section (AGENTS.md, CLAUDE.md only if different, wiki page list, the plan's Progress), rebuilt only at request start and after a trim because Strata reuses the cached prompt prefix; finish checks at the end of an Act reply: done check (YOLO: sent back until done or a Blocked: line, stops after 3 unchanged send-backs), browser check (headless Chromium via playwright-core, console errors), evidence check, fresh-context reviewer, each off with DL_DONE_CHECK / DL_BROWSER_CHECK / DL_EVIDENCE / DL_REVIEW=0; local_wiki schema lists page_type, slug, description. Tests: tools/test_dl_memory.py (28) reproduces the CONTRA loss on the old code. Benchmark numbers and the loop guard: see Rollout and measurements below. Sources: saved session ~/.local/state/dl-ai/sessions/dl-ai-code.json (backup ~/dl-ai-code-session-2026-10-19.json); User, chat, 2026-10-19.

## Rollout and measurements (2026-10-20)

- Deployed to the main checkout and dl-ai-sessiond on 2026-10-20 02:59 (loop guard 07:20). All 10 D.L. test suites pass, including `tools/test_dl_memory.py` (28 tests). Committed locally as `033a06a2` on 2026-10-20 (not pushed).
- Benchmark `tools/dl_agent_bench.py`, Qwen3.8-Flash-Next Coder IQ1_M on the RX 7600 XT, one run per side:

| Task | before (old code) | after (new code) |
|---|---|---|
| longplan, `DL_CONTEXT_RESERVE=52000` (about 13.5k limit, 15 trims) | 2/3 checks; task and plan trimmed away; 2 nudges, 186 tool calls, 3,387 s | 3/3; PLAN.md kept; 1 nudge, 105 tool calls, 3,008 s |
| tetris | 6/7 (no decisions in PLAN.md), 4,437 s, 1 nudge | 6/6 scored (PLAN.md has the decisions; SRS kicks not scorable, 6 of 8 plan steps done), 9,788 s, 3 nudges |
| bugfix | 2/2, 164 s | 2/2, 266 s (reviewer about 100 s) |
| crc32c | 3/3, 313 s | 3/3, 2,707 s (79k-char looping thinking block, review 9.5 min) |

- Gotcha found in the after run: the IQ1_M model's thinking can go round in circles. One block was 180,333 chars of the same three sentences, repeated about 530 times (17 min). Another was 21 lines repeated 18 times (79,173 chars). Added a loop guard (`thinking_loops`, `LOOP_RULES = ((8000, 30, 8), (24000, 60, 4))`, off with `DL_LOOP_GUARD=0`): it closes the stream, drops the looping thinking and asks for the next action, at most 3 times per request. On the 189 thinking blocks over 3,000 chars saved on 2026-10-20 it flags 4, all real loops; it would have stopped the two worst at 6,000 and 21,000 chars. The reviewer now runs at `reasoning_effort` low (`DL_REVIEW_EFFORT`). The tetris and crc32c after-numbers above were measured before these two changes.
- Larger context window (2026-10-20, user-approved test with abort rules): 98,304, 81,920 and 73,728 all failed at startup and 65,536 stays. See [RX 7600 XT CachyOS Deployment](rx-7600-xt-cachyos-deployment.md) for the numbers. The test first needed the API key, which the user approved in chat.
- 2026-10-20, user's requests: the YOLO auto-continue notice shows the running total ("N tool rounds so far in this request"); the agent is told to tick each Progress line as soon as its own check passes, not when the whole section is done, and Plan mode asks for one line per step and per check (`dl_cli.py`, `dl_sessiond.py`, tests in `test_dl_memory.py`). The Home Assistant MCP is no longer on by default (`"default": "on"` removed from `~/.config/dl-ai/mcp.json`, backup `mcp.json.bak-20261020-ha-default`); its generic trigger words (light, camera, socket, plug, printer) still load it in game code, which is open for the user to decide.
- 2026-10-20, Code tab plan chip and phones:
  - The chip only updates when the daemon sends a `state` event: start of a request, mode change, MCP change. During one long YOLO request it showed 15/99 while PLAN.md was at 27/99; a reload (fresh `hello`) shows the true count. Fix: `Session._plan_changed` sends a state after any tool result that changed PLAN.md's mtime (`tools/dl_sessiond.py`, test in `test_dl_memory.py`). It was written and tested on 2026-10-20 and deploys with the next `dl-ai-sessiond` restart, after the CONTRA run (user's choice).
  - User preference: phones show the same session line as the desktop (mode, YOLO, PLAN, MCP chips, folder). At up to 600 px it used to be `display: none`; now the line takes its own full-width row (`serve/web/app.css`, `.code-terminal-info { display: contents }`). Checked at 375 px and 1024 px.
  - Gotcha: browsers cache `index.html`, so bump the `?v=` on `app.css` / `app.js` in it after a web change (now `20261020-meta2`). To test, load the page with a fresh query string (`/?nocache=N#code`). Static files need no server restart: `serve/server.py` reads them per request.
- 2026-10-20 15:39, gotcha: the CONTRA run stopped at 50/97 with "Stopped after 40 tool rounds" although YOLO was on. A text-written tool call on round 40 of 40 took the "resend it" `continue`, which skipped the YOLO counter reset at the end of the loop body, so the `while turn < max_turns` loop ended. The loop-guard `continue` had the same flaw. Fix: `yolo_rollover()` in `execute_agent_loop` is called on every path that goes to the next round, and each new 40-round stretch also resets the text-call and loop-guard retries (before, they were per request and ran out in long runs). Three tests in `test_dl_memory.py` fail on the old code and pass on the new. Deployed at 15:55 with the plan-chip fix; CONTRA resumed with "continue".

## Related

- [D.L. CLI Task Memory and Finish Checks Plan (2026-10-19)](../artifacts/dl-cli-task-memory-plan-2026-10-19.md) - the approved plan
- [D.L. CLI Agent Quality Plan](../artifacts/dl-cli-agent-quality-plan.md) - items 2, 3, 5, 6 implemented here

## Sources

1. User, chat, 2026-10-19.
2. Benchmark runs `/mnt/data/DL-AI-workspace/bench/20261019-2335-before-memory`, `20261020-0349-after-memory`, `20261020-0107-before-memory-longplan52`, `20261020-0259-after-memory-longplan52` (`report.md`, `results.json`), 2026-10-20.
3. `/mnt/data/Strata/strata-coder-iq1_m.log`, conversation cache lines, 2026-10-20.
