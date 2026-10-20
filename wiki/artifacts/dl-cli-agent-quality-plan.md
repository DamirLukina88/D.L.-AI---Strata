---
title: "D.L. CLI Agent Quality Plan (from the TETRIS test)"
type: artifact
description: "Plan to make D.L. CLI's agent finish its work and back its claims: turn cap, evidence check, reviewer, tests, browser check, plan files"
status: active
tags: [plan, cli, agent, verification, testing, benchmark]
created: 2026-10-14
updated: 2026-10-14
last_verified: 2026-10-14
---

# D.L. CLI Agent Quality Plan (from the TETRIS test)

## Summary

On 2026-10-14 the user ran a test project through D.L. CLI: a single-file Tetris in `/mnt/data/DL-AI-workspace/TETRIS` (8 user prompts, about 46 tool calls; export `dl-ai-code-chat-2026-10-14-10-21.md`). Claude audited the result. The model planned and coded well but checked badly. This plan changes the **tool** so the agent is pushed to finish and to back its claims. The user chose every option below in an interview on 2026-10-14.

## Status (2026-10-14)

- **Benchmark built:** `tools/dl_agent_bench.py` (tasks tetris, bugfix, crc32c; drives the live `dl-ai-sessiond`, one `bench-<run>-<task>` session per task) and `tools/test_dl_agent_bench.py` (9 tests, no GPU). The web Code tab takes `?session=NAME` to watch one. "Before" run started 10:46: `/mnt/data/DL-AI-workspace/bench/20261014-1046-before`.
- **Change 1 (turn cap) written, not yet measured:** `DL_MAX_TURNS` (default 40, was a hard-coded 10). When the cap is hit, `turn_cap_wrap_up` makes one last call asking for a status, with the same tools so the prompt cache still hits, and doesn't run any tool call in that reply. It emits the notice "Stopped after N tool rounds"; `/continue` goes on (CLI, daemon, and a web chip). The benchmark counts a cap hit from that notice and reports `cut_off_silently` separately.
- **Baseline ("before", 10:46-11:36, old code with the 10-call cap):** `/mnt/data/DL-AI-workspace/bench/20261014-1046-before/report.md`.
  - tetris 7/9 checks, 38 min. Hit the cap with no reply 3 times in a row on `/act` (3 nudges). The PLAN.md rewrite was blocked in Plan mode again. The clockwise kicks were wrong again: 2->3 and 3->0 are copies of 0->1 and 1->2. Then the **context overflowed** (65,575 tokens against a 65,536 context), so audit, wiki and status all failed instantly.
  - bugfix 2/2, 48 s, 6 calls.
  - crc32c 3/3, 10.5 min, 24 calls, 1 cut-off. It searched with Exa, turned on Fetch, and checked the published vector 0xE3069283.
- **New findings from the baseline**, to add to the change list:
  - (a) **No context management.** The session holds 212 kB: 98 kB reasoning, 67 kB tool arguments (whole file writes), 14 kB tool results. Nothing trims or summarizes, and nothing warns before the limit. Whether old reasoning reaches the prompt depends on the model's chat template *(inferred: likely, given the sizes)*.
  - (b) **Bad tool-call JSON is hidden.** `execute_agent_loop` turns tool-call arguments that aren't valid JSON into `{}`, so the model sees "TargetFile required" instead of "your arguments were not valid JSON (probably cut off)".
  - (c) **The approval guard misfires.** `classify_command` reads `/.exec(html)` inside a JS regex as a path outside the workspace and asks for approval. The bench's own rule had the same flaw and denied it, which blocked the agent's headless test; fixed in the bench (only paths whose first part exists under `/` count).
- **Change 1b (context budget) written:** `fit_context` / `compact_history` / `chat_turn_in_context` in `tools/dl_cli.py`; tests `tools/test_dl_context.py` (6, no GPU).
  - The budget is the context from `/health` minus `DL_CONTEXT_RESERVE` (16,000 tokens kept for the reply). Over it, the history is compacted down to 60% of the budget.
  - The size estimate is exact after each call: Strata's streamed `usage.prompt_tokens` plus the new messages at 2.8 characters per token. On the real overflowed session the character estimate gave 71.4k against Strata's measured 65.6k, so it errs high.
  - Compaction runs in stages: (1) older messages lose their reasoning, whole-file contents in tool calls and the middle of long tool results; (2) the same, keeping only the last 2 messages; (3) the oldest messages are removed in whole units (each tool call kept with its result), with one note that keeps count. On the overflowed session, stage 1 alone went from 71.4k to 19.3k.
  - If Strata still refuses the prompt as too long, the target is scaled by how far off the estimate was, and the call is retried once.
  - Why the reserve matters: with no max_tokens, Strata gives the reply only the context left over, so near the limit a big file write gets cut off (*inferred* cause of finding (b)).
- **"After" run** (turn cap + context budget), started 11:42 after a daemon restart: `/mnt/data/DL-AI-workspace/bench/20261014-1142-after-cap-context`.
- **"After" results** (11:42-13:33; `python3 tools/dl_agent_bench.py compare` on the two runs; both re-scored after two bench fixes: the probe's `location` stub, and "CW" accepted as clockwise):
  - tetris 6/7 checks (before 7/9).
    - Silent cut-offs 3 → 0, context overflows 4 → 0, model errors 4 → 0, unfinished at the end yes → no.
    - SRS kicks right (wrong before). PLAN.md rewritten in Act mode with the decisions (not before).
    - D.L. AI turned Playwright on itself and tested in a browser. Its closing summary stated what it couldn't check.
    - Cost: 98 min against 38, 207 tool calls against 39, the context compacted several times.
    - New failure: rotating an O piece twice throws, because `KICK_O` has 1 row for 4 states. The audit missed it.
  - bugfix 2/2 (78 s). crc32c 3/3 (640 s, no cut-off this time).
  - Approvals: 35 asked; a user would have had to click each one. 21 were Playwright key presses on its own test page; 13 were the regex-as-path misfire (finding c) on `sed -n '/^<script>/,/^<\/script>/p'`.
  - Unknown tools: 3, two typos (`replace_file_code`, `replace_file_ontent`) and one `playwright__*` call after Playwright had turned itself off for being idle.
  - One run per side: SRS right or wrong may be sampling luck; repeat runs are needed before calling it.
- **Batch 2 (2026-10-14 13:40), written and tested; run `20261014-1343-after-batch2`:**
  1. The approval guard ignores a "path" whose top folder doesn't exist under `/` in shell commands (`dl_auditing.classify_command`). Quoted regex like `'/^<\/script>/p'` no longer asks; `/etc`, `~` and other folders still do.
  2. MCP `trust_local_pages` (opt-in per server, set for Playwright in `~/.config/dl-ai/mcp.json`; the old file is kept as `mcp.json.bak-2026-10-14`). "ask" tools don't ask while the server's page is `file://`, localhost, 127.0.0.1, `[::1]` or `*.localhost`. The page is taken from `navigate` and from Playwright's "Page URL:" lines; it's forgotten when the server stops; an unknown page still asks.
  3. Unknown tools: a clear typo (difflib ≥ 0.88, one match, its arguments fit) runs the real tool with a note; anything else gets "Did you mean …" and the tool list. A `server__tool` call after its server went idle restarts the server (`McpRegistry.revive`).
  4. Tool-call arguments that aren't valid JSON go back as an error: nothing runs, and when the reply was cut off by the length limit the message says to write in parts.
  - Tests: `test_dl_tool_calls.py` (new, 5), plus new cases in `test_dl_mcp.py` (5) and `test_dl_auditing.py` (1). All D.L. suites pass.
- Gotcha: the daemon runs the code it loaded at start. Restart it (`systemctl --user restart dl-ai-sessiond`) before an "after" run, but **not while a bench run is going**: the restart drops the bench's sessions.

## What went wrong, and the cause in the tool

| Failure in the TETRIS run | Cause in D.L. CLI |
|---|---|
| The agent stopped twice right after a tool result with no reply. The user's "report the status" and "audit" prompts were really restarts. | `execute_agent_loop` stops after `max_turns=10` model calls and says nothing (`tools/dl_cli.py:1215`). Both cut-off turns had exactly 10 calls. |
| The audit said all 16 SRS kick rows were checked "cell-by-cell, exact match". 3 of the 4 clockwise JLSTZ rows were wrong. | Nothing asks for evidence behind a "verified" claim. The model checked the code against its own memory of the table. |
| `PLAN.md` on disk is still the first draft, but the status report and the wiki say it holds the locked decisions. | Plan mode blocks all writes, including the plan file. Nothing saves the plan or checks it on approval. |
| The false "exact match" and "cosmetic" claims went into the project wiki. | Wiki writes need no source. |
| Playwright was on hand, but the model never opened the game in a browser. | The router turns Playwright on only for words like "click"; nothing asks for a browser check after web edits. |
| It took 3 rounds to fix its own Node test harness, then deleted the harness when asked. | No reusable helper; tests aren't kept by default. |
| It called a tool that doesn't exist (`edit_file`) and lost a round. | The error lists no valid tool names. |

## Changes (user's choices, 2026-10-14)

1. **Turn cap.** Raise `max_turns` (setting `DL_MAX_TURNS`, default about 40). When the cap is hit, show a line ("stopped after N tool rounds — /continue to go on") instead of stopping silently, and ask the model for a one-paragraph status before stopping.
2. **Evidence rule and checker.** Add a system-prompt rule: verify against a test, a tool result or a cited source, never from memory; a worked derivation counts. Before the final answer is shown, the CLI scans it for claim words (verified, tested, passes, matches, cross-checked, confirmed). It sends the answer back once if a claim has no tool result behind it from this task. The check is cheap, and the model has to rewrite the claim or prove it.
3. **Fresh-context reviewer (local).** At the end of each Act task that changed files, a second call to the same local model, with a clean context, sees only the diff, the plan and the final claims, and lists problems. Findings go back to the agent to fix before the answer is shown. The user accepts the extra time ("whatever it takes").
4. **Tests.**
   - No "done" without a test run: if files changed and no test or check command ran after the last edit, the CLI sends the agent back to run one.
   - Remember each project's test command in its wiki, and suggest it on later tasks.
   - Keep harnesses in `tests/` by default; the user can still delete them.
   - A built-in Node helper that loads a single-file HTML page with stubbed browser APIs (DOM, canvas, requestAnimationFrame, keyboard events) and exposes chosen functions, so the agent doesn't rebuild that harness each time.
5. **Browser check after web edits.** When a task changed `.html`, `.js` or `.css` and the agent is about to finish, the CLI turns on Playwright and asks the agent to load the page and read the console errors. A screenshot is optional. This costs about +3,000 prompt tokens (about +4 s, measured in [the MCP plan](dl-cli-on-demand-mcp-plan.md)), only on those turns.
6. **Plan mode may write the plan file and the wiki.** Allow `PLAN.md` (or `plans/`) and wiki pages in Plan mode; all other files stay blocked. On approval, the CLI checks that the plan file was written in this task before switching to Act.
7. **Wiki writes must cite.** Each fact the agent saves cites a source: the user said it, a test result, or a `file:line`. Facts without one are saved marked *(unverified)*.
8. **Unknown tool names.** The error lists the valid names, and common aliases (`edit_file` → `replace_file_content`, `read_file` → `view_file`) map to the real tool.
9. **Visibility.** One line in the terminal and a chip in the web Code tab (for example "review: 2 issues fixed"). The full findings go in a collapsible block and in the `/save` export.

- 2026-10-20: items 2 (evidence check), 3 (fresh-context reviewer), 5 (browser check, run by D.L. CLI itself with playwright-core) and 6 (PLAN.md, written on approval instead of in Plan mode) are implemented and deployed, together with trim protection, a done check and a thinking-loop guard: see [D.L. CLI Keeps Its Task](../decisions/dl-cli-task-memory-and-finish-checks.md). Visibility (item 9) is a notice per check plus a plan chip in the Code tab, not a findings block.

## Scope

`tools/dl_cli.py`, `tools/dl_sessiond.py` and the web Code tab. `tools/antigravity_local.py` is a **symlink** to `dl_cli.py` (checked 2026-10-14), so it gets every change automatically. The older plan pages that call it a "near-copy" are out of date.

## How to measure

A replay benchmark: save the TETRIS prompts, plus 2-3 more small tasks, as a script that drives `dl-ai-sessiond`. Run it before and after the changes and score each run on:
- whether the clockwise SRS kick rows are correct, tested against the offset-table derivation
- whether `PLAN.md` on disk matches the agreed plan
- claims with no evidence behind them
- tool errors, stops at the turn cap, and user nudges needed
- wall time

## Sources

1. User, chat, 2026-10-14 (interview answers above).
2. Audit of `/mnt/data/DL-AI-workspace/TETRIS/index.html` and the chat export, 2026-10-14. A Node script derived the SRS kicks from the official offset tables: rows 1→2, 2→3 and 3→0 are wrong. A 60 s stall locked 3 pieces in one frame, and one auto-repeat key press restarted the game straight from game over.
3. Code read: `tools/dl_cli.py` (`execute_agent_loop`, `build_dl_system_prompt`, `dispatch_dl_tool`), 2026-10-14.

## Thinking-level sweep (2026-10-15)

`python3 tools/dl_agent_bench.py sweep --efforts low,medium,high --email-to <you>`: tasks bugfix, roman and intervals (the "quick" group), 2.5 min per prompt, no nudges, about 21 min in total. D.L. AI emailed each part's result with its own Gmail tool (3 of 3 sent). Comparison: `/mnt/data/DL-AI-workspace/bench/sweep-20261015-1911-quick-low.md`.

| | low | medium | high |
|---|---|---|---|
| Hidden checks passed | 22/25 (roman 5/8) | 25/25 | 25/25 |
| Total time | 433 s | 299 s | 380 s |
| Thinking time | 159 s | 143 s | 220 s |
| Longest thinking block (characters) | 2,518 | 3,875 | 5,004 |
| Repeated sentences | 0 | 0 | 0 |

Measured on qwen3.8-flash-next-coder-iq1_m, RX 7600 XT. One run of three small tasks, so a direction, not a measured difference; low ran first, with a cold cache. On these tasks high thought about 50% longer than medium for the same score, with no sentence loops; low skipped testing on roman and failed it. Suggested default: medium.
