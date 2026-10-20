---
title: "D.L. CLI Keeps Its Task: Trim Protection, PLAN.md, Memory Files, Finish Checks"
type: decision
description: "Why the CONTRA run lost its task to trimming (2026-10-19) and the fix: protected user messages, PLAN.md, project_memory, finish checks"
status: active
tags: [dl-cli, context, trimming, plan, memory, agent-quality]
created: 2026-10-19
updated: 2026-10-21
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
- 2026-10-20 21:20, gotcha: trimming replaces the big arguments of old edit calls with a stand-in (`ELIDED`, `[N chars removed by D.L. CLI ...]`), and the model copied that stand-in into new calls. That happened 33 times in the 13:58-21:20 event window. Most failed ("TargetContent not found", or the syntax check). But 6 put the stand-in into CONTRA's `src/*.part` files, which have no syntax check; twice (17:41, 17:46) a 12-14k test file was overwritten with the one line. The agent found and repaired each with grep. Fix (`tools/dl_cli.py`): `stand_in_error` refuses a write or edit that adds a stand-in (regex `STAND_IN`: both `ELIDED` wordings and the tool-result `[... N chars removed ...]`). A file that already holds one can still be edited, and replacing one with real text is allowed as a repair. A "TargetContent not found" whose target is a stand-in now says so. The `ELIDED` text says it is a stand-in, not content, never to copy. Commands in `run_command` are not checked. Tests: class `StandIn` in `test_dl_memory.py` (36 tests); 3 of 4 fail on the old code. CONTRA was paused for it at 21:38 (user's request, at 80/98 done, harness 95/99 while on V9); it deploys with the next `dl-ai-sessiond` restart.
- 2026-10-20 21:23, gotcha: the agent emptied CONTRA's 33 KB data module `src/04_js_data.js.part` (palette, constants, areas, weapons, strings, `buildArea`). It used a `run_command` Python edit written as `open(q,'w').write(d.replace(anchor, new + d.count(anchor)*0 + anchor, 1))`. Python opens (and truncates) the file before it builds the argument, and building it raised `TypeError`, so the file stayed empty. The result said "exited with code 0" because a later command on the line succeeded; 8 Python tracebacks in the 16:03-21:38 event window were reported that way. `build.sh` then built `index.html` without the part. CONTRA has no git and no snapshots (`/mnt/data` is btrfs, but snapper covers only `/`). The agent judged the file lost and planned to rewrite it with "plausible values" until the harness passed. Recovery: `/tmp/gs.js`, a copy of the page's script that the agent saved at 20:41 (from the 20:40:51 build), holds the part as `gs.js[1:31400]`. The three later edits (20:49, 20:50, 21:10) and the intended 21:23 insertion are in the daemon's event replay with their exact text. Rebuilt and checked on a scratch copy: harness 97/99 (95/99 at 21:06). 52 of 814 `run_command` calls in that window edited with the same `open(p,'w').write(<expression>)` pattern. Also found: the V9.1 check expects 1.71 as the WCAG "spec worked answer" for #778899/#88AADD, but the formula gives 1.533 (the game's `wcagRatio` is right and the check is wrong). The V7.4 check change at 20:25 was a fair fix: it adds the declared co-op wait to its time limit.
- 2026-10-20 22:00-22:15, the user chose to repair, harden and resume:
  - **Restore:** `04_js_data.js.part` is back in CONTRA (33,697 bytes; backup of the broken state in the Claude session's scratchpad). The harness passes 97/99 in the workspace itself.
  - **Checkpoints** (`Checkpoints` in `tools/dl_cli.py`): a git history per workspace in `~/.local/state/dl-ai/checkpoints/<name>-<hash>.git`, committed at request start and after every round that changed files. The workspace's `.gitignore` applies; files over 20 MB, the home folder, `/` and folders over 20,000 files are left out.
  - **Shrink alarm:** before and after each `run_command` / `write_to_file` / `replace_file_content`, the workspace is scanned. A file of at least 1 KB that was emptied, deleted or cut below half (top-level `tmp/` excluded) gets a warning appended to the tool result, with `git --git-dir=... checkout <hash> -- <file>` for the checkpoint before the round, and a "Shrink alarm" notice.
  - **Transcript** (`dl_sessiond.py`): every event, with thinking blocks merged, goes to `~/.local/state/dl-ai/transcripts/<session>/<date>.jsonl` (0600). `/save full` renders the run since `/clear`; tool results are capped at 4,000 chars as on the Code tab.
  - **Switches:** checkpoints and transcript are on only when `DL_CHECKPOINTS=1` / `DL_TRANSCRIPT=1`, which the daemon's and the CLI's `main()` set by default. That way the test suites, which import the modules, never write into the real state folder.
  - **Tests and rollout:** `test_dl_memory.py` has 42 tests (classes `Checkpointing`, `Transcript`); all 12 D.L. suites pass. Deployed with a `dl-ai-sessiond` restart at 22:08. CONTRA resumed at 22:09 with a note: what happened, do not rewrite 04, the V9.1 value is 1.533, edit safely. Its first round created `CONTRA-0eab32175f1d.git`.
  - **22:12, gotcha:** the resumed run stopped again. A debug command printed 105,947 chars, and `tool_run_command` had no output limit. The trimmer never touches the last two messages, so the prompt stayed at 79,813 tokens (numeric debug text is about 1.7 chars per token, not 2.8). Strata refused it, the overflow retry compacted nothing, and the request ended. Fix: `cap_tool_result` cuts every tool result over `TOOL_RESULT_MAX` (30,000 chars, `DL_TOOL_RESULT_MAX`) to 70% head and 30% tail, with a stand-in the guard recognizes. `compact_history` gained a stage 4 that shortens the newest tool results (4,000, then 1,200 chars) when stages 1-3 are not enough. Tests: class `BigOutput` (44 tests; both fail on the old code, the overflow one with the same HTTP 400). Deployed 22:17; CONTRA resumed 22:17, with the context going from 52k to 16k.
  - **22:45, gotcha found by the goal loop's review:** the browser finish check had never run. With `node -e`, the first argument is `process.argv[1]`, but `BROWSER_JS` read `[2]` and `[3]`. It loaded the page URL as the Playwright module, printed nothing, and `browser_errors` returned "browser check failed: list index out of range". The finish check then only said "Browser check skipped". The unit test mocks `browser_errors`, so it passed. Fix: `const [PW, PAGE] = process.argv.slice(-2)`. New test class `RealBrowserCheck` loads a page with an error and a clean one in real headless Chromium (skipped without playwright-core); it fails on the old code (45 tests). CONTRA's 22:25 build loads with 0 console errors. Deploys at the next idle moment, since the check only runs when a request ends.
  - **23:20, the browser check was also blind to CONTRA.** It looked only at files the edit tools changed (`RequestChanges`). CONTRA edits `src/*.part` and builds `index.html` with a script, so the check never chose its page. Its YOLO request had also run for hours without ever reaching the finish checks. Meanwhile, in a real browser the page died on its first frame: `roundRectPath` was called 9 times and never defined, and no harness check drew a frame until V10. Fix:
    - `web_pages` and `changed_pages` find pages by mtime (top level and one folder down), so built pages count.
    - `browser_nudge` runs at each YOLO auto-continue. It loads a page that changed and hands the agent new console errors once (`BROWSER_LIVE_NOTE`), merged into a user note if one is last.
    - Tests: class `BuiltPageBrowserCheck` (47 tests, both fail on the old code).
    - Deployed 23:25 with the argv fix, after an interrupt (the request might never go idle before its end), and resumed with "continue".
  - **User's rules for the goal loop:** 23:20, "You are not allowed to help the ai directly". 23:24, "You are allowed to fix bugs and serious issues and nudge the ai in the right direction that way". So the loop fixes D.L. CLI, which may nudge the AI with real problems, and repairs data loss. It sends no game hints and writes no CONTRA code. Direct help given before 23:20: the 04 restore and two resume notes (the V9.1 value 1.533, safe Python edits, small debug output).
  - **2026-10-21 00:46, the review found the AI's S12 browser audit blind.** `tools/checks/browser-audit.cjs` (puppeteer-core with a real headless Chrome) reported 0 console errors at 390/768/1440 px. It did the same on a probe page that logs `console.error` and throws a ReferenceError, while `browser_errors` (Playwright) caught both. The game itself was clean (0 errors, 60 FPS), so V0.7 and V10.4 passed for the wrong reason. The user approved a note at 00:52, with the finding and the probe page but no fix. The AI started on it right away. The word "browser" in the note loaded the Playwright MCP (a fitting match).
  - **Router gotcha:** the resume note's "at 22:12" loaded the schedule MCP ("matched 'at 22:12: the debug run'"). Clock times in a message trigger it, like the Home Assistant trigger words.
  - **The watch:** the 30-minute Claude watch now reviews the agent's work from the checkpoints and the transcript (test changes, values, regressions, ticks, data loss). Its first review found the AI's V9.1 fix correct (1.71 to 1.53), but the new comment states L(#88AADD)=0.4068 (correct: 0.3920).

## CONTRA run result and analysis (2026-10-21)

- **Result:** the task finished at 01:38 on 2026-10-21. All 98 Progress lines are ticked, with no Blocked line. Verified independently at 01:46-01:50:
  - The harness passes 106/106 on a fresh copy, and `tools/audit.sh` on a copy prints "GATE: clean" (0 console errors, 0 warnings, 0 overflow).
  - Playwright at 390, 768 and 1440 px: 0 console errors, FPS readout 60, status "running", resize works.
  - The delivered `contra.html` is byte-identical to `index.html` (SHA-256 `f8ddabb0…`), and its Drive copy is a real file of 122,492 bytes.
  - Exactly one email went out (01:15 from dl-ai-agent@ to the plan's two addresses), with Drive links because Proton `send_mail` takes no attachments. The Drive folder and its 4 files are set to "anyone with the link can view". Both chat files scan clean for credentials.
- **Progress over the run:** 50/97 when the YOLO bug stopped it at 15:39, then 72 at 18:50, 80 at 20:50, 84 at 22:43, 87 at 23:46, 90 at 00:16 and 98 at 01:16. The harness grew from 25 checks (2026-10-19) to 60, 87, 99 and finally 106. In the transcript window from 22:09 to 01:46: 576 tool calls (424 `run_command`), 25 harness runs, 19 trims, 13 YOLO auto-continues, 140 checkpoints (5.5 MB) and a 1.5 MB transcript. The task survived every trim. The loop guard never fired after 15:56.
- **Mistakes found by the review, and who fixed them:**
  - **The AI fixed these itself:** missing `fitToElement` and `roundRectPath` (the page died on its first frame in a real browser; no harness check drew a frame before V10); `audit.sh` running the harness with `bash`, joining strings with `&` and falling back to 0 errors; invented Drive file IDs after a trim (it recovered by searching).
  - **Data loss repaired by Claude:** the emptied `04_js_data.js.part`, restored from `/tmp/gs.js` plus the event log.
  - **Fixed after a note:** the wrong V9.1 expected value (1.71; correct 1.533), and the blind puppeteer browser audit (note approved by the user at 00:52).
  - **Still in the delivered files** (all minor):
    - the V9.1 comment's luminance values (0.2394/0.4068; correct 0.2383/0.3920);
    - 15 debug and probe scratch files in `contra-tools.tar.gz` (28 entries);
    - V10.3 no longer checks that a shake already running is ignored under reduced motion;
    - the email quotes the archive at 163,781 bytes, while the refreshed Drive copy is 163,797 (disclosed by the AI);
    - `session-chat.md` is the in-context export (41 messages), not the whole run.
- **Interventions, in order:**
  1. The 2026-10-20 restart (`/clear`, `/planfile`, continuation message).
  2. "continue" after the YOLO fix at 15:55.
  3. The pause at 21:38 (the user's request).
  4. Direct help (before the user's 23:20 rule): the 04 restore and resume note 1 at 22:09 (what happened, V9.1 = 1.533, safe Python edits).
  5. Resume note 2 at 22:17 (small debug output).
  6. Interrupt and "continue" at 23:22 for a deploy.
  7. The approved audit note at 00:52.
  8. 21 D.L. CLI fixes deployed during the run, listed above.
- **D.L. CLI fixes this run produced (all on 2026-10-20/21, deployed, uncommitted):** stand-in guard; checkpoints; shrink alarm; transcript and `/save full`; tool-result cap and newest-result trimming; browser check argv fix; built pages found by mtime, plus a live browser check at each YOLO auto-continue; and at 01:52, a reviewer that sees the checkpoint diff, shows its findings as an output block and keeps the current finish-check note through trims (`ReviewSeesEverything`, 49 tests).
- **Lessons:**
  - A long YOLO request needs its checks during the run, not only at its end.
  - A check that cannot fail must be tested against a failing input. That would have caught both browser checks: D.L. CLI's own and the AI's.
  - Tools must see shell-command edits; the checkpoints now give them that view.

## Related

- [CONTRA Goal Loop and Review Tooling (2026-10-20/21)](../artifacts/contra-goal-loop-2026-10-21.md) - the loop's rules, review script, browser check and the notes sent to the AI
- [D.L. CLI Task Memory and Finish Checks Plan (2026-10-19)](../artifacts/dl-cli-task-memory-plan-2026-10-19.md) - the approved plan
- [D.L. CLI Agent Quality Plan](../artifacts/dl-cli-agent-quality-plan.md) - items 2, 3, 5, 6 implemented here

## Sources

1. User, chat, 2026-10-19.
2. Benchmark runs `/mnt/data/DL-AI-workspace/bench/20261019-2335-before-memory`, `20261020-0349-after-memory`, `20261020-0107-before-memory-longplan52`, `20261020-0259-after-memory-longplan52` (`report.md`, `results.json`), 2026-10-20.
3. `/mnt/data/Strata/strata-coder-iq1_m.log`, conversation cache lines, 2026-10-20.
