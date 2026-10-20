---
title: "CONTRA Goal Loop and Review Tooling (2026-10-20/21)"
type: artifact
description: "The 30-minute Claude loop that reviewed and fixed around the D.L. AI's CONTRA run: rules, review script, browser check, notes sent"
status: active
tags: [dl-cli, contra, review, agent-quality]
created: 2026-10-21
updated: 2026-10-21
last_verified: 2026-10-21
---

# CONTRA Goal Loop and Review Tooling (2026-10-20/21)

## Summary

From 2026-10-20 around 22:15 until the run ended on 2026-10-21 at 01:38, a recurring Claude Code job (every 30 minutes, at :13 and :43) watched the D.L. AI's CONTRA session `dl-ai-code`. Each run reviewed what the AI had changed since the last check and fixed D.L. CLI bugs as they appeared. The result, the mistakes found and the D.L. CLI fixes are in [D.L. CLI Keeps Its Task](../decisions/dl-cli-task-memory-and-finish-checks.md#contra-run-result-and-analysis-2026-10-21). This page keeps the loop's rules, its two tools (they lived in the Claude session's scratchpad, which is temporary) and the exact notes sent to the AI.

## The user's rules for the loop

- 2026-10-20 22:15: "/goal keep on iterating and implementing fixes automatically with 30 min checks until contra finishes the game successfully without mistakes"; "the watch should additionally analyze what the D.L. AI did, so we can catch mistakes and bugs early". Approved with "I approve" after the permission check blocked two attempts to create the job.
- 23:20: "You are not allowed to help the ai directly." 23:24: "You are allowed to fix bugs and serious issues and nudge the ai in the right direction that way."
- In practice:
  - **Allowed:**
    - D.L. CLI fixes, with a test that fails on the old code and all 12 `tools/test_dl_*.py` suites passing;
    - deploys while the session is idle, or an interrupt between tool calls when a fix had to be live before the request ended, then a plain "continue";
    - restoring lost files from the checkpoints;
    - reporting the AI's own mistakes to the user.
  - **Not allowed:** game hints, values or code; engine or model config; git commit or push.
  - **Exception:** one note with game knowledge was sent with the user's explicit approval (00:52, the blind browser audit).

## Each check

1. `watch_review.py` (below) prints a digest since its bookmark:
   - session state, plan progress, YOLO rounds, trims and flagged notices;
   - Python tracebacks reported as exit 0, stand-in refusals and failed edits;
   - harness results with newly failing checks;
   - the checkpoint diff, with test files in full and PLAN.md ticks.
2. A human-style review:
   - tests deleted, weakened or bent to the code;
   - numbers recomputed (the WCAG ratio, for example);
   - regressions, and ticks without a passing run after the last edit;
   - data loss and obvious bugs in the changed game code.
3. `pw_contra.js` (below) loads the page in Playwright at 390, 768 and 1440 px, reads the console errors, the FPS readout and the status line, and resizes. It found that the page died on its first frame (`roundRectPath` never defined) while the harness was green.
4. To test a check, run it on a page that must fail. `bad.html` (`console.error('boom'); undefinedThing();`) showed that the AI's puppeteer audit reported 0 errors on a broken page.

## Notes sent to the D.L. AI

Resume note 1 (2026-10-20 22:09, direct help, before the user's 23:20 rule):

```text
CONTRA was paused at 21:38 for a repair. What happened and what changed:

1. At 21:23 your Python edit `open(q,'w').write(d.replace(anchor, new + d.count(anchor)*0 + anchor, 1))` emptied src/04_js_data.js.part: Python opens (and empties) the file before it builds the argument, and building it raised a TypeError. The line still reported exit code 0 because a later command on it succeeded, and build.sh then rebuilt index.html without the part.

2. The file has been restored exactly, so do not rewrite it. It is the 20:40 version (from your /tmp/gs.js) plus your edits of 20:49 (text role, HI_CONTRAST, theme()), 20:50 (lum, wcagRatio) and 21:10 (toHexColour), plus the change you were making at 21:23: the `let REDUCED_MOTION_FORCED = null; let HIGH_CONTRAST_FORCED = null;` block now sits in 04 just before the "WCAG 2.x relative-luminance ratio" comment (they are no longer in 08). index.html is rebuilt; the harness passes 97 of 99, with V9.1 and V9.4 failing.

3. V9.1's expected value is wrong, not the formula. WCAG 2.x gives 1.533 for #778899 on #88AADD (black on white = 21 is right); the 1.71 in src/h18.mjs.part does not come from the spec. Correct the check's expected value to 1.53 and keep wcagRatio as it is.

4. New D.L. CLI safeguards: every round that changes files is saved as a checkpoint (a git history kept outside the workspace); a call that empties, deletes or halves a file now says so in its result, with the command that restores it; an edit that would copy a "[N chars removed by D.L. CLI ...]" stand-in into a file is refused.

5. For Python edits, build the new text first and write the file last (or use replace_file_content), and read Stderr even when the exit code is 0.

Then continue with the open steps in PLAN.md, starting with V9.1 and V9.4.
```

Resume note 2 (22:17):

```text
Your last request ended at 22:12: the debug run of tools/harness (the DBG lines) printed 105,947 characters, which did not fit the context, so the engine refused the request. D.L. CLI now cuts any tool result over 30,000 characters to its start and end. Keep debug output small: print only the lines you need, or redirect it to a file in tmp/ and read that with grep, sed -n or tail.

Continue with the open steps in PLAN.md (V9.4 next).
```

Plain `continue` at 23:25, after an interrupt for a deploy. The audit finding (2026-10-21 00:52, approved by the user: "1"):

```text
A finding from the review, approved by the user: tools/checks/browser-audit.cjs cannot detect errors. Neither console errors nor uncaught exceptions are counted.

Proof: /tmp/claude-1000/-home-damirl--claude-spares-spare-f1HZ8o/49e5d379-0624-4bff-b05e-08877e8bc42c/scratchpad/audit-probe/bad.html is a page that calls console.error('boom') and then an undefined function. Your audit, run the way audit.sh runs it, reports 0 console errors at all three widths for it (its output: /tmp/claude-1000/-home-damirl--claude-spares-spare-f1HZ8o/49e5d379-0624-4bff-b05e-08877e8bc42c/scratchpad/audit-probe/out.json). A Playwright check of the same page reports both errors. So the 0 in tools/browser-audit.json is not evidence for V0.7 or V10.4 yet.

Then continue with the open steps in PLAN.md.
```

## Tool: watch_review.py

```python
"""CONTRA watch: what the D.L. AI did since the last check, for a human-style review.  Read-only: it reads the
session state, the daemon's transcript and the workspace checkpoints (git log/diff), and writes only its own state
file next to this script.

    python3 watch_review.py            # digest since the last run, then remember where it stopped
    python3 watch_review.py --peek     # the same without moving the bookmark
"""
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/data/Strata/tools")
import dl_cli as cli  # noqa: E402  (only for Checkpoints(...).git_dir)

SESSION = "dl-ai-code"
WS = Path("/mnt/data/DL-AI-workspace/CONTRA")
STATE = Path(__file__).with_name("watch_state.json")
TRANSCRIPTS = Path.home() / ".local/state/dl-ai/transcripts" / SESSION
HARNESS = re.compile(r"CONTRA harness: (\d+) PASS / (\d+) FAIL / (\d+) MISSING of (\d+) checks")
FAIL_LINE = re.compile(r"^(FAIL|MISSING)\s+(\S+)\s+(.*)$", re.M)
TEST_FILE = re.compile(r"^(src/h\d+\.mjs\.part|tools/harness/|tools/checks/|tools/audit)")


def state_now() -> dict:
    s = socket.socket(socket.AF_UNIX)
    s.connect("/run/user/1000/dl-ai/sessiond.sock")
    s.settimeout(5)
    s.sendall(json.dumps({"op": "state", "session": SESSION}).encode() + b"\n")
    buf = b""
    while b"\n" not in buf:
        buf += s.recv(1 << 20)
    s.close()
    return json.loads(buf.split(b"\n")[0])


def git(*args: str) -> str:
    gd = cli.Checkpoints(WS).git_dir
    r = subprocess.run(["git", f"--git-dir={gd}", f"--work-tree={WS}", *args], capture_output=True, text=True,
                       cwd=WS, timeout=60)
    return r.stdout


def events_since(ts: float) -> list[dict]:
    out = []
    for p in sorted(TRANSCRIPTS.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if (ev.get("ts") or 0) > ts:
                out.append(ev)
    return out


def hm(ts) -> str:
    return time.strftime("%H:%M", time.localtime(ts or 0))


def main() -> None:
    peek = "--peek" in sys.argv
    prev = json.loads(STATE.read_text()) if STATE.is_file() else {}
    st = state_now()
    plan = st.get("plan") or {}
    since = prev.get("ts", time.time() - 1800)
    evs = events_since(since)
    print(f"# CONTRA review {time.strftime('%H:%M')} (since {hm(since)}; {len(evs)} events)")
    done_prev = prev.get("plan_done")
    print(f"busy={st.get('busy')} plan {plan.get('done')} done / {plan.get('open')} open, blocked={plan.get('blocked')}"
          + (f" (was {done_prev} done)" if done_prev is not None else ""))

    # --- rounds, notices, harness, masked failures, tool errors
    notices = [e for e in evs if e.get("type") == "notice"]
    rounds = [int(m.group(1)) for e in notices for m in [re.search(r"(\d+) tool rounds so far", e.get("text", ""))] if m]
    if rounds:
        print(f"YOLO rounds: {rounds[-1]}")
    trims = sum(1 for e in notices if e.get("text", "").startswith("Context "))
    flagged = [e for e in notices if re.search(r"Shrink alarm|Loop guard|Checkpoints are off|stopped|Blocked|"
                                                r"review|browser|evidence|plan steps|Interrupted", e.get("text", ""), re.I)]
    print(f"trims: {trims}; flagged notices: {len(flagged)}")
    for e in flagged[-8:]:
        print(f"  {hm(e.get('ts'))} {e.get('text', '')[:220]}")
    results = [e for e in evs if e.get("type") == "tool_result"]
    calls = {e.get("id"): e for e in evs if e.get("type") == "tool_call"}
    masked = [e for e in results if "Traceback (most recent call last)" in e.get("text", "")
              and "exited with code 0" in e.get("text", "")]
    guard = [e for e in results if "stand_in_guard" in e.get("text", "") or "[D.L. CLI] Warning:" in e.get("text", "")]
    notfound = sum(1 for e in results if "TargetContent not found" in e.get("text", ""))
    syntax = sum(1 for e in results if "syntax_guard" in e.get("text", ""))
    print(f"tool calls: {len(calls)}; tracebacks shown as exit 0: {len(masked)}; guard/alarm hits: {len(guard)}; "
          f"edit misses: {notfound}; syntax blocks: {syntax}")
    for e in (masked + guard)[-5:]:
        c = calls.get(e.get("id")) or {}
        cmd = json.dumps(c.get("args") or {})[:160]
        print(f"  {hm(e.get('ts'))} {e.get('name')} {cmd}\n     -> {e.get('text', '')[-200:].strip()!r}")

    runs = []
    for e in results:
        m = HARNESS.search(e.get("text", ""))
        if m:
            fails = {fm.group(2): fm.group(3)[:150] for fm in FAIL_LINE.finditer(e.get("text", ""))}
            runs.append((e.get("ts"), m.group(0), fails))
    if runs:
        print(f"harness runs: {len(runs)}; last {hm(runs[-1][0])}: {runs[-1][1]}")
        prev_fails = set(prev.get("fails") or [])
        now_fails = set(runs[-1][2])
        prev_total = prev.get("total")
        total = int(HARNESS.search(runs[-1][1]).group(4))
        new = sorted(now_fails - prev_fails)
        if new:
            note = " (check count unchanged: possible REGRESSION)" if prev_total == total else ""
            print(f"  newly failing since the last review{note}: {', '.join(new)}")
        for k in sorted(now_fails):
            print(f"  FAIL {k}: {runs[-1][2][k]}")
    else:
        print("harness runs: none in this window")

    # --- code changes from the checkpoints
    base = prev.get("commit")
    log = git("log", "--format=%h %ad %s", "--date=format:%H:%M", "-n", "400").splitlines()
    head = log[0].split()[0] if log else None
    if base is None and log:
        base = log[-1].split()[0]                        # the first checkpoint
    if head and base and head != base:
        print(f"\n## checkpoints {base}..{head} ({len(git('rev-list', f'{base}..{head}').split())} new)")
        stat = git("diff", "--stat=160", f"{base}..{head}")
        print(stat.rstrip()[-2500:])
        names = git("diff", "--name-only", f"{base}..{head}").split()
        tests = [n for n in names if TEST_FILE.match(n)]
        if tests:
            diff = git("diff", "-U2", f"{base}..{head}", "--", *tests)
            removed_checks = re.findall(r"^-\s*chk\('([^']+)'", diff, re.M)
            added_checks = re.findall(r"^\+\s*chk\('([^']+)'", diff, re.M)
            gone = sorted(set(removed_checks) - set(added_checks))
            print(f"\n## test changes ({', '.join(tests)}): checks removed: {gone or 'none'}; "
                  f"checks touched: {sorted(set(removed_checks) | set(added_checks)) or 'none'}")
            lines = diff.splitlines()
            print("\n".join(lines[:260]) + (f"\n... ({len(lines) - 260} more diff lines)" if len(lines) > 260 else ""))
        if "PLAN.md" in names:
            pdiff = git("diff", "-U0", f"{base}..{head}", "--", "PLAN.md")
            ticked = re.findall(r"^\+\s*- \[x\] (.{0,90})", pdiff, re.M)
            unticked = re.findall(r"^\+\s*- \[ \] (.{0,90})", pdiff, re.M)
            print(f"\n## PLAN.md: ticked {len(ticked)}" + "".join(f"\n  + {t}" for t in ticked[:12])
                  + (f"\n  re-opened/added open: {len(unticked)}" if unticked else ""))
            blocked = re.findall(r"^\+.*Blocked:.*$", pdiff, re.M)
            if blocked:
                print("  BLOCKED line added: " + blocked[0][:200])
    else:
        print("\n(no new checkpoints since the last review)" if head else "\n(no checkpoints yet)")

    if not peek:
        STATE.write_text(json.dumps({
            "ts": max([e.get("ts") or 0 for e in evs] + [since]),
            "commit": head or base, "plan_done": plan.get("done"),
            "fails": sorted(runs[-1][2]) if runs else prev.get("fails", []),
            "total": int(HARNESS.search(runs[-1][1]).group(4)) if runs else prev.get("total")}))


if __name__ == "__main__":
    main()
```

## Tool: pw_contra.js

Run with `node pw_contra.js <playwright-core dir> file:///mnt/data/DL-AI-workspace/CONTRA/index.html`; playwright-core is in `~/.local/share/dl-ai/mcp-npm/node_modules/`.

```javascript
// Load CONTRA's index.html at 390/768/1440 px in headless Chromium; report console errors, the FPS readout and a resize.
const [PW, PAGE] = process.argv.slice(-2);
const { chromium } = require(PW);
(async () => {
  const b = await chromium.launch({ headless: true });
  const out = {};
  for (const w of [390, 768, 1440]) {
    const p = await b.newPage({ viewport: { width: w, height: Math.round(w * 0.75) } });
    const errs = [];
    p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    p.on('pageerror', e => errs.push('uncaught: ' + String(e)));
    await p.goto(PAGE, { waitUntil: 'load', timeout: 20000 });
    await p.waitForTimeout(3000);
    const fps = await p.evaluate(() => { const e = document.getElementById('hFps'); return e ? e.textContent : null; });
    const diag = await p.evaluate(() => { const e = document.getElementById('diag'); return e ? e.textContent : null; });
    const buf = await p.evaluate(() => { const c = document.getElementById('stage'); return c ? c.width + 'x' + c.height : null; });
    await p.setViewportSize({ width: Math.round(w * 0.8), height: Math.round(w * 0.6) });
    await p.waitForTimeout(800);
    const buf2 = await p.evaluate(() => { const c = document.getElementById('stage'); return c ? c.width + 'x' + c.height : null; });
    out[w] = { errors: errs.slice(0, 8), fps, diag, buffer: buf, afterResize: buf2 };
    await p.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => console.log(JSON.stringify({ launch_error: String(e).slice(0, 400) })));
```

## Related

- [D.L. CLI Keeps Its Task: Trim Protection, PLAN.md, Memory Files, Finish Checks](../decisions/dl-cli-task-memory-and-finish-checks.md) - the run's analysis and every D.L. CLI fix
- [Home Assistant Core Deployment and Strata MCP Integration](../decisions/home-assistant-strata-mcp.md) - the trigger words narrowed after the run

## Sources

1. User, chat, 2026-10-20 and 2026-10-21.
2. Claude Code session scratchpad (`watch_review.py`, `pw_contra.js`, `resume-note*.txt`, `audit-note.txt`), 2026-10-21.
3. Transcript `~/.local/state/dl-ai/transcripts/dl-ai-code/2026-10-2*.jsonl` and checkpoints `~/.local/state/dl-ai/checkpoints/CONTRA-0eab32175f1d.git`, 2026-10-21.
