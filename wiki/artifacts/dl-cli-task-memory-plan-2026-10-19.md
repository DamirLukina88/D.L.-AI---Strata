---
title: "D.L. CLI Task Memory and Finish Checks Plan (2026-10-19)"
type: artifact
description: "Approved plan after the CONTRA run lost its task: trim protection, PLAN.md on approval, memory files in the prompt, done check, wiki schema"
status: active
tags: [plan, dl-cli, context, trimming, memory, agent-quality]
created: 2026-10-20
updated: 2026-10-20
last_verified: 2026-10-20
---

# Plan (2026-10-19): make D.L. AI keep its task and use its memory files

## Context

On 2026-10-19 the D.L. AI (dl-ai-sessiond running the D.L. CLI agent loop, Qwen3.8-Flash-Next Coder, 66k context)
stopped CONTRA after 6 h with about 2/3 of its own approved plan undone. The cause is in the code, not the model:

- **Trimming lost the task.** `compact_history` (`tools/dl_cli.py:1551`) keeps the system prompt, the *first*
  user-role message and the *latest* user-role message. D.L. CLI adds its own user-role notes, like
  `TEXT_CALL_NOTE` (`dl_cli.py:1734`), `TURN_CAP_NOTE` (`:1662`) and the trim note `DROPPED` (`:1466`). Once one of
  them is the "latest", the real instruction can be trimmed. The saved session ended with 3 user messages:
  "create a folder called CONTRA", the trim note and the text-tool-call note. Both `/act` (`EXECUTE_PLAN`,
  `tools/dl_sessiond.py:50`) and the plan were gone.
- **The plan existed only as an assistant message**, so it could be trimmed, and `EXECUTE_PLAN` says "the plan"
  without saying where it is. Item 6 of `wiki/artifacts/dl-cli-agent-quality-plan.md` (2026-10-14) asked for a
  plan file, but no `PLAN.md` handling exists in `dl_cli.py` or `dl_sessiond.py`.
- **AGENTS.md / CLAUDE.md are never loaded.** `build_dl_system_prompt` (`dl_cli.py:599`) mentions only the wiki,
  and the only code that names those files is the diff checker in `dl_auditing.py:470`.
- **Nothing checks that the work is done.** A reply with no tool calls ends the turn (`dl_cli.py:1741`).
- **The `local_wiki` schema** (`dl_cli.py:303`) is missing `page_type`, `slug` and `description`, so the first
  `new_page` call fails.

Goal: the task and plan survive any amount of trimming; AGENTS.md (with CLAUDE.md as its copy), PLAN.md and
the wiki are its memory; in YOLO it keeps working until the plan is done or it records why it is blocked.

User's choices (2026-10-19): all four groups below. AGENTS.md is the source and CLAUDE.md a copy. In YOLO it
keeps going until done (no fixed cap). Roll out after the CONTRA run, with a before/after benchmark.

## Design constraint: keep the prompt prefix stable

Strata reuses the cached prompt prefix between requests (`serve/server.py`, `cached_tokens`), and
`wiki/decisions/claude-code-cli-integration.md` shows how much the project relies on prefix hits. So the
memory section must **not** be rebuilt on every model call. It is rebuilt only (a) at the start of each user
turn and (b) right after a compaction, which breaks the prefix anyway, and only when a file's content changed
(hash check). Mid-turn edits to AGENTS.md therefore take effect at the next trim or turn.

## Changes

### 1. Trim protection (`tools/dl_cli.py`, `compact_history`)
- Add `is_cli_note(m)`: a user-role message whose content starts with `"[D.L. CLI"`. All notes already start
  that way, and real messages start with `[Now: …]` from `with_now`.
- Real user messages (all user-role messages except notes) are never removed. They are short, and `_shrink`
  already leaves user text alone. `first`/`last_user` come from real messages only.
- Notes stay removable, except the single `DROPPED` note that is kept today.
- Tests in `tools/test_dl_context.py`: a long session where a `TEXT_CALL_NOTE` arrives after the instruction
  (today's failure) → the instruction survives; several real user messages all survive; tool-call/result
  pairing still holds (the existing tests keep passing).

### 2. PLAN.md on approval (`tools/dl_sessiond.py`, `tools/dl_cli.py`)
- On plan approval (`Session.answer`, `dl_sessiond.py:199`, before `submit("/act")`; CLI path
  `dl_cli.py:2367-2373`), write the last assistant message with text to `<workspace>/PLAN.md`. If a PLAN.md
  already exists, it is moved to `PLAN.<date>.md` first. Set the session's `plan_file` (saved in the session
  JSON and cleared by `/clear`).
- `EXECUTE_PLAN` becomes: "Execute the approved plan in PLAN.md. Keep its `## Progress` checklist current:
  tick `- [x]` when a step's checks pass; if you cannot go on, add a `Blocked:` line saying why."
- Plan-mode system prompt (`dl_cli.py:615-645`): "Your final message is saved as PLAN.md. Make it complete on
  its own and end it with a `## Progress` checklist, one `- [ ]` line per step."
- New `/planfile <path>|off` command (daemon + CLI) to attach an existing plan, for example CONTRA's PLAN.md
  made by hand today. It is listed in `/help`.

### 3. Memory files in the prompt (`build_dl_system_prompt`, `dl_cli.py:599`)
- Add a `<project_memory>` section built by a new `project_memory(workspace, plan_file)`:
  - `AGENTS.md` (capped at 8 KB, with a note when it was cut). `CLAUDE.md` is added only when its content
    differs from AGENTS.md and is not just an import of it, so a matching copy is not loaded twice.
  - The wiki index: page titles and one-line hooks from `wiki/index.md` (capped at 3 KB).
  - The `## Progress` section of the active plan file (capped at 3 KB) and its path.
  - A rule: "These files are your memory. Put conventions in AGENTS.md (then copy it to CLAUDE.md), progress
    in PLAN.md, decisions in the wiki. Re-read them after a trim."
- Rebuild timing: per the constraint above. Add a cached `(hashes) → text` in the session so an unchanged
  section yields a byte-identical prompt.
- `DROPPED` (`dl_cli.py:1466`) names the files: "…removed. Your task and progress are in PLAN.md (Progress
  below), rules in AGENTS.md, decisions in wiki/. Re-read what you need now." It also carries the current
  Progress section, since a trim is exactly when the model loses it.

### 4. Done check and wiki fix
- At "no tool calls, turn is complete" (`dl_cli.py:1741`): if the mode is act, a `plan_file` is set and its
  Progress section has open `- [ ]` lines with no `Blocked:` line:
  - **YOLO:** append a note "[D.L. CLI] PLAN.md has N open steps: <first 3>. Continue with the next one, or
    add a `Blocked:` line saying why you cannot." and continue the loop, with no cap, as chosen. One safeguard
    (strike it at approval if you don't want it): if 3 send-backs in a row change nothing in the workspace
    (same PLAN.md, no file edits), stop and tell the user it is stuck. Interrupt keeps working as today.
  - **Not YOLO:** a notice "N plan steps still open; /continue to go on".
  - When nothing is open: a notice "Plan complete", and `plan_file` is cleared.
- `local_wiki` schema (`dl_cli.py:303`): add `page_type` (enum from wiki.py), `slug` and `description`, and
  mark them required in the description for `new_page`.
- Tests: `tools/test_dl_yolo_continue.py` style. A fake server whose model answers with no tool calls → it is
  sent back while steps are open, stops at `Blocked:`, stops after 3 send-backs with no change, ends when all
  steps are ticked. A schema test that `new_page` lists the fields `tool_local_wiki` requires.

## Rollout

1. **Wait for CONTRA.** Start only when dl-ai-code is idle (`state` → `busy: false`) and its run has finished
   or been given up. The bench would compete for the GPU and the restart would end the run.
2. **Before benchmark** on the current code: `python tools/dl_agent_bench.py run --label before-memory`
   (tetris, bugfix, crc32c, about 1 h). Its tetris task already scores "PLAN.md holds the decisions".
3. **Implement** 1-4 on a local branch (the repository is local-only; commits are safety copies).
4. **Tests:** `python tools/test_dl_context.py`, `test_dl_sessiond.py`, `test_dl_yolo_continue.py`,
   `test_dl_tool_calls.py`, `test_dl_session_tools.py`, `test_dl_agent_bench.py`, `py_compile` on the changed files.
5. **Restart** `systemctl --user restart dl-ai-sessiond` (the bench refuses to run on a daemon older than the code).
6. **After benchmark:** `run --label after-memory`, then `compare` the two run dirs. Also add a `longplan` bench
   task: a fixed 10-step PLAN.md with small independent steps (each adds a function and its test) whose
   session is forced to trim several times. Its score is steps done, checks passing, "Blocked" lines, and
   whether the instruction is still in the saved session. Run it before and after too; the "before" run uses
   the old code, so add the task first and run it in step 2.
7. **Record:** a decision page in the Strata wiki (trim protection, PLAN.md, memory section, done check, with
   the measured numbers) and mark item 6 of `dl-cli-agent-quality-plan.md` done.

## Verification
- All listed tests pass. The new tests fail on the old code (the TEXT_CALL_NOTE case reproduces today's loss).
- Bench compare: no task worse; `longplan` finishes more steps after than before, and the instruction is
  present in the saved session after every trim.
- A manual check with a small plan in a scratch workspace: approve a plan, check that PLAN.md is written; edit
  AGENTS.md; force a trim (`/compact` if present, else a long task) and check that the memory section and
  Progress appear; check that a final answer with open steps is sent back.
- Prompt stability: two consecutive model calls with no file changes send a byte-identical system prompt
  (unit test on `build_dl_system_prompt` plus the session cache).

## Not in this plan
The other quality-plan items (evidence checker, reviewer, browser check after web edits), a larger context
window, and anything in the engine or the web Code tab beyond showing the new notices it already renders.

## Outcome

Implemented and deployed 2026-10-20, with the user-requested additions (evidence check, fresh-context reviewer, browser check, plan chip, thinking-loop guard, per-line ticking). Measurements and what changed against this plan: [D.L. CLI Keeps Its Task](../decisions/dl-cli-task-memory-and-finish-checks.md). The larger context window was tested and rejected: [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md).

## Sources

1. Claude Code plan file `~/.claude/plans/structured-cuddling-wolf.md`, approved by the user in chat, 2026-10-19.
