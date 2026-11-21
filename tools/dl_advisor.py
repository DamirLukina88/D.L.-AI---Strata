#!/usr/bin/env python3
"""The DeepSeek helper: when Ray stays stuck on one problem, D.L. CLI (not the model) asks DeepSeek for a diagnosis and
hands the answer to Ray as advice; Ray keeps doing the work locally.

Opt-in with DL_ADVISOR=1 (off by default, so the default path is unchanged).  It asks only after the auto thinking
level is already on high (or the effort is fixed), when one of these holds:

  * the same failure (the first FAIL / Error / Traceback line of a result) came back DL_ADVISOR_REPEATS times (3);
  * DL_ADVISOR_STALL rounds (12) passed without progress (a check with fewer failures than before, or none) and at
    least 3 results in them failed;
  * Ray was raised for a thinking loop or a repeated call twice.

Models (the user's choice, 2026-11-14): the first consult on a problem uses V4.1 Flash (cheap); when Ray is still
stuck on it after Flash's advice, the next consult uses V4 Pro.  A finished Plan Mode plan is reviewed once by Pro
before the Execute card (review_plan; DL_ADVISOR_PLAN_REVIEW=0 turns that off).
A run that started from an approved plan gets a final review by Pro when the agent says it is done (final_review,
called from dl_cli.finish_checks): bugs and unmet plan requirements send it back, and the review repeats after the
fixes, up to DL_ADVISOR_FINAL_MAX rounds (5); it stops early when nothing changed since the last review.
DL_ADVISOR_FINAL=0 turns that off.  These reviews have their own budget.
Limits: DL_ADVISOR_MAX consults per request (3), at most DL_ADVISOR_PRO_MAX of them Pro (1), DL_ADVISOR_COOLDOWN
rounds between them (10; 6 before the Pro follow-up), one Flash consult per failure.
The question goes through Ray's MCP registry (deepseek__deepseek_reason): its credential filter applies, and outside
YOLO the usual DeepSeek approval card is shown.  The brief holds the request, the failing output, the code diff of this
request and a one-line list of what was tried - never memory-store files.  Every consult is logged to
~/.local/state/dl-ai/advisor.jsonl with whether progress followed.  Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

try:
    from tools import dl_profile
except ImportError:
    import dl_profile

TOOL = "deepseek__deepseek_reason"
FLASH = "auto"             # the newest Flash model (deepseek_mcp.model_ladder), stepping down if it is unavailable
PRO = "deepseek-v4-pro"
LOG = Path(os.environ.get("DL_ADVISOR_LOG") or Path.home() / ".local" / "state" / "dl-ai" / "advisor.jsonl")
BRIEF_MAX = 24000          # characters (about 6-8k tokens)
FAIL_LINE = re.compile(r"^.*\b(FAIL(?:ED)?|Error|Exception|Traceback|AssertionError|not ok)\b.*$", re.M)
COUNT_FAIL = re.compile(r"\bFAIL(?:ED)?\b|\bnot ok\b")
EXIT_CODE = re.compile(r"\[Command exited with code (\d+)\]")
# Browser testing repeats calls by nature (the same page reloaded, the same key pressed, the same snapshot): those
# repeats are not going in circles (the 2026-11-14 12:19 consult was such a false alarm).
INTERACTIVE = re.compile(r"(playwright|browser|chrome|puppeteer)__|__(navigate|snapshot|press_key|click|find|"
                         r"screenshot|type|hover|wait|select|scroll)", re.I)

SYSTEM = ("You are a senior software engineer advising a smaller local coding agent that is stuck. You cannot run "
          "anything; you see a brief of its task, the failing output, its code changes and what it already tried. "
          "Find the root cause. Say plainly whether the code or the test is wrong. Give the next concrete steps "
          "(at most 10 short lines), naming exact files, functions and lines, with a small code snippet only where "
          "it is needed. Do not rewrite whole files. If the brief lacks what you need, say which file or output to "
          "look at next.")

NOTE = ("[D.L. CLI] You were stuck ({why}), so D.L. CLI asked a stronger model (DeepSeek, {model}) for a second "
        "opinion. Its advice:\n\n{advice}\n\nCheck it against the code before you apply it - you know the files, it "
        "only saw a brief. Then continue the task.")


# Patch mode (the user's choice, 2026-11-14): when the stuck work is in known files, DeepSeek writes the fix itself as
# exact old -> new blocks; D.L. CLI checks every OLD block occurs exactly once, and Ray applies and tests them.
PATCH_SYSTEM = ("You fix code for a smaller local coding agent that is stuck. You see its task, why it is stuck, its "
                "changes so far and the full text of the files it works on. You cannot run anything. Find the root "
                "cause and write the fix as patch blocks, nothing else before them:\n"
                "FILE: <the file's path exactly as given in the brief>\n<<<OLD\n<lines copied exactly from the file, "
                "enough of them to be unique>\n===\n<the replacement lines>\nNEW>>>\n"
                "Use as many blocks as needed, smallest change that fixes it, no reformatting. After the blocks, one "
                "line 'CHECK: <how the agent should verify the fix>' and at most 3 short lines on why. If the files "
                "shown are not where the problem is, write no blocks and say which file or output to look at.")

PATCH_NOTE = ("[D.L. CLI] You were stuck ({why}), so D.L. CLI asked a stronger model (DeepSeek, {model}) to write the "
              "fix. Each OLD block below was checked: it occurs exactly once in its file.\n\n{patch}\n\nApply every "
              "block with replace_file_content (TargetContent = the OLD text, ReplacementContent = the NEW text), "
              "exactly as given, then verify: {check}. If the check fails, say why and fix it yourself.")

PATCH_BLOCK = re.compile(r"FILE:\s*(?P<file>[^\n]+?)\s*\n<<<OLD\n(?P<old>.*?)\n===\n(?P<new>.*?)\n?NEW>>>", re.S)
PATCH_CHECK = re.compile(r"^CHECK:\s*(.+)$", re.M)
SKIP_FILES = re.compile(r"(^|/)(\.env[^/]*|secrets?[^/]*|[^/]*\.(pem|key|p12)|node_modules/.*|\.git/.*|\.jj/.*)$", re.I)
PATCH_FILE_MAX = 200_000


def parse_patch(answer: str, ws: Path) -> tuple[list[dict], list[str], str]:
    """(valid blocks, rejected reasons, check line) from a patch answer.  A block is valid when its file is inside
    the workspace and its OLD text occurs exactly once there (blocks on one file are checked in order)."""
    ws = Path(ws).resolve()
    valid, bad, texts = [], [], {}
    for m in PATCH_BLOCK.finditer(answer or ""):
        raw = m.group("file").strip().strip("`")
        p = (ws / raw).resolve() if not raw.startswith("/") else Path(raw).resolve()
        if p != ws and ws not in p.parents or not p.is_file():
            bad.append(f"{raw}: not a file in the workspace")
            continue
        if p not in texts:
            texts[p] = p.read_text(encoding="utf-8", errors="replace")
        old, new = m.group("old"), m.group("new")
        n = texts[p].count(old) if old else 0
        if n != 1:
            bad.append(f"{raw}: OLD text found {n} times")
            continue
        texts[p] = texts[p].replace(old, new, 1)
        valid.append({"file": str(p), "old": old, "new": new})
    check = PATCH_CHECK.search(answer or "")
    return valid, bad, (check.group(1).strip() if check else "run the project's own check")


PLAN_SYSTEM = ("You review a software plan written by a smaller local coding agent before it is executed. List only "
               "what matters: steps that are missing or in the wrong order, wrong assumptions, risky choices, things "
               "that cannot be verified as planned, and anything far more complex than needed. At most 12 short "
               "bullets, most important first. If the plan is sound, say so in one line. Do not rewrite the plan.")

PLAN_NOTE = ("[D.L. CLI] Before the user approves it, a stronger model (DeepSeek, {model}) reviewed your plan "
             "({why}). Its notes:\n\n{advice}\n\nRevise the plan where the notes are right (you know the workspace; "
             "it only saw the plan), say briefly which notes you did not take and why, and present the final plan.")


# An empty balance or a refused key: no model can answer, so the helper pauses (DL_ADVISOR_PAUSE_S, an hour) instead
# of failing again on every new problem.  Shared by every request of the daemon; a restart clears it.
DEAD_END = re.compile(r"\b40[123]\b|insufficient balance|authentication|invalid api key|api key|unauthori[sz]ed", re.I)
_PAUSE = {"until": 0.0, "why": ""}


def paused() -> str | None:
    """Why the helper is paused, or None."""
    return _PAUSE["why"] if time.time() < _PAUSE["until"] else None


FINAL_SYSTEM = ("You are the final reviewer of work a smaller local coding agent says it has finished. You get the "
                "approved plan, the agent's final report, and the full text of every file it changed. You cannot run "
                "anything, so reason from the code. Look for: wrong behaviour and bugs (logic, coordinates, off-by-one, "
                "state that is never reset, input handling), crashes, and requirements of the plan that are not met or "
                "only claimed. Ignore style and taste. A changed file that the plan does not mention may be the user's "
                "own work: never ask for a file to be deleted, removed or reverted; at most note it under Optional.\n"
                "Answer in exactly this form. First line: 'VERDICT: PASS' when there is no bug and no unmet plan "
                "requirement, or 'VERDICT: FIX' otherwise. Then under 'Must fix:' one bullet per bug or unmet "
                "requirement, each naming the file, the function or line, what is wrong and how to see it, most "
                "important first (at most 10). Then, optionally, under 'Optional:' at most 5 bullets of minor "
                "suggestions; those never block.")

FINAL_NOTE = ("[D.L. CLI] A final review by a stronger model (DeepSeek, {model}, round {round} of at most {max}) read "
              "the plan, your report and the changed files, and found problems to fix before this is done:\n\n"
              "{advice}\n\nCheck each point against the code (it could not run anything), fix the real ones, test "
              "them, and say briefly which points you rejected and why. Then report again; the review runs again.")


def enabled() -> bool:
    return dl_profile.env("DL_ADVISOR", "0") == "1" and paused() is None


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def failure_signature(text: str) -> str | None:
    """The first failure line of a tool result, with numbers and paths blurred, so the same failure on the next run
    matches; None when the result shows no failure."""
    m = FAIL_LINE.search(text or "")
    code = EXIT_CODE.search(text or "")
    if not m and not (code and code.group(1) != "0"):
        return None
    if m:
        line = m.group(0)
    else:   # no FAIL/Error line: the last line of output before the exit code tells failures apart
        body = (text or "")[:code.start()].strip().splitlines()
        tail = next((l for l in reversed(body) if l.strip() and l.strip() != "Stderr:"), "")
        line = f"exit code {code.group(1)}: {tail.strip()}"
    line = line.strip()
    line = re.sub(r"0x[0-9a-f]+|\d+", "#", line)
    line = re.sub(r"(/[\w.-]+)+", "<path>", line)
    return line[:160]


class Advisor:
    """One request's struggle state and the consults it made."""

    def __init__(self, session_context: dict | None = None):
        self.ctx = session_context or {}
        self.round = 0
        self.last_progress = 0
        self.best_fails: int | None = None
        self.fail_rounds: list[int] = []
        self.sigs: dict[str, int] = {}
        self.raises: list[str] = []
        self.raise_rounds: list[int] = []       # the round of each raise: going in circles means two close together
        self.consults: list[dict] = []
        self.asked: set[str] = set()
        self.tried: list[str] = []
        self.last_fail_text = ""
        self.pro_used = 0
        self.fails_since_consult = 0
        self.touched: dict[str, int] = {}       # workspace file -> times Ray viewed, edited or named it in a command

    # ------------------------------------------------------------------ signals
    def note_raise(self, reason: str | None, tool: str = "") -> None:
        if not reason:
            return
        if reason == "repeated tool call" and INTERACTIVE.search(tool or ""):
            return
        if reason == "tool call sent as text":      # a format slip D.L. CLI already handles (and revives the server);
            return                                  # it is not going in circles (2026-11-14 16:04 false alarm)
        self.raises.append(reason)
        self.raise_rounds.append(self.round)

    def note_result(self, name: str, args: dict, result: str) -> None:
        """One tool result: what was tried, whether it failed, and whether it was progress."""
        arg = ""
        if isinstance(args, dict):
            arg = str(args.get("CommandLine") or args.get("command") or args.get("TargetFile") or args.get("path")
                      or args.get("AbsolutePath") or args.get("query") or "")
        head = (result or "").strip().splitlines()[0][:90] if (result or "").strip() else ""
        self.tried.append(f"{name} {arg[:120]!s} -> {head}")
        self._touch(name, args)
        self.tried = self.tried[-12:]
        sig = failure_signature(result)
        n_fail = len(COUNT_FAIL.findall(result or ""))
        ran_check = bool(EXIT_CODE.search(result or "")) or n_fail or "PASS" in (result or "")
        if sig:
            self.fails_since_consult += 1
            self.sigs[sig] = self.sigs.get(sig, 0) + 1
            self.fail_rounds.append(self.round)
            self.last_fail_text = result or ""
        if ran_check and (n_fail == 0 and not sig or self.best_fails is not None and n_fail < self.best_fails):
            self.last_progress = self.round                     # fewer failures than before, or none
            self.sigs = {sig: 1} if sig else {}                 # the failures left are counted afresh
        if ran_check and (self.best_fails is None or n_fail < self.best_fails):
            self.best_fails = n_fail

    def _touch(self, name: str, args) -> None:
        ws = self.ctx.get("workspace")
        if not ws or not isinstance(args, dict):
            return
        ws = Path(ws).resolve()
        if name in ("view_file", "replace_file_content", "write_to_file"):
            names = [str(args.get("AbsolutePath") or args.get("TargetFile") or args.get("path") or "")]
        elif name == "run_command":
            names = re.findall(r"[\w./-]+\.[A-Za-z]\w{0,5}\b", str(args.get("CommandLine") or args.get("command") or ""))
        else:
            return
        for raw in names:
            if not raw:
                continue
            p = (ws / raw).resolve() if not raw.startswith("/") else Path(raw).resolve()
            if (p.parent == ws or ws in p.parents) and p.is_file() and not SKIP_FILES.search(str(p.relative_to(ws))):
                rel = str(p.relative_to(ws))
                self.touched[rel] = self.touched.get(rel, 0) + 1

    def target_files(self, changed: list[str] | None = None, limit: int = 3) -> dict[str, str]:
        """The workspace files the stuck work is in: those changed in this request first, then the ones Ray touched
        most; text files only, at most PATCH_FILE_MAX characters each."""
        ws = Path(self.ctx.get("workspace") or ".").resolve()
        order = [c for c in (changed or []) if not SKIP_FILES.search(c)]
        order += [k for k, _ in sorted(self.touched.items(), key=lambda kv: -kv[1]) if k not in order]
        out: dict[str, str] = {}
        for rel in order:
            p = (ws / rel).resolve()
            try:
                if not p.is_file() or p.stat().st_size > PATCH_FILE_MAX:
                    continue
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            out[rel] = text
            if len(out) >= limit:
                break
        return out

    def end_round(self) -> None:
        self.round += 1

    # ------------------------------------------------------------------ decision
    def stuck(self) -> tuple[str, str, str] | None:
        """(why, problem key, model) when the helper should ask now, else None."""
        if not enabled() or len(self.consults) >= _int("DL_ADVISOR_MAX", 3):
            return None
        effort = self.ctx.get("effort")
        if self.ctx.get("effort_auto") and effort != "high" and not self.ctx.get("raised"):
            return None                                         # the cheaper rung (thinking on high) comes first
        last = self.consults[-1] if self.consults else None
        since = self.round - last["round"] if last else 10 ** 6
        # Flash's advice did not help: still no progress and more failures since -> Pro, once
        if (last and last.get("model_wanted") != PRO and self.pro_used < _int("DL_ADVISOR_PRO_MAX", 1)
                and self.last_progress <= last["round"] and self.fails_since_consult >= 2
                and since >= _int("DL_ADVISOR_PRO_AFTER", 6)):
            return (f"still stuck {since} rounds after Flash's advice ({self.fails_since_consult} more failed results; "
                    f"first: {last['why'][:120]})"), last["key"] + "#pro", PRO
        if since < _int("DL_ADVISOR_COOLDOWN", 10):
            return None
        repeats = _int("DL_ADVISOR_REPEATS", 3)
        for sig, n in sorted(self.sigs.items(), key=lambda kv: -kv[1]):
            if n >= repeats and sig not in self.asked:
                return f"the same failure came back {n} times: {sig}", sig, FLASH
        stall = _int("DL_ADVISOR_STALL", 12)
        recent_fails = [r for r in self.fail_rounds if r >= self.round - stall]
        if self.round - self.last_progress >= stall and len(recent_fails) >= 3 and "stall" not in self.asked:
            return (f"{self.round - self.last_progress} rounds without progress, {len(recent_fails)} failed results",
                    "stall", FLASH)
        # two repeats close together, not two anywhere in a long request (2026-11-15 09:27: repeats 73 rounds apart
        # in a run that was editing fine got a 7-block patch nobody needed)
        window = _int("DL_ADVISOR_LOOP_WINDOW", 12)
        loops = [r for r, n in zip(self.raises, self.raise_rounds)
                 if r in ("thinking loop", "repeated tool call") and n >= self.round - window]
        failing_lately = any(r >= self.round - 10 for r in self.fail_rounds)
        if len(loops) >= 2 and failing_lately and "loops" not in self.asked:
            return f"it went in circles ({', '.join(loops[-2:])})", "loops", FLASH
        return None

    # ------------------------------------------------------------------ the brief
    def brief(self, why: str, diff: str = "") -> str:
        task = str(self.ctx.get("user_text") or "").strip()
        plan = self.ctx.get("plan_file")
        parts = [f"## Task\n{task[:3000]}"]
        if plan:
            try:
                text = Path(plan).read_text(encoding="utf-8", errors="replace")
                open_steps = [l for l in text.splitlines() if l.strip().startswith("- [ ]")][:12]
                if open_steps:
                    parts.append("## Open plan steps\n" + "\n".join(open_steps))
            except OSError:
                pass
        parts.append(f"## Why the agent is stuck\n{why}")
        if self.last_fail_text:
            parts.append("## Latest failing output\n" + self.last_fail_text[-6000:])
        if diff:
            parts.append("## Code changes in this request (diff)\n" + diff[:9000])
        if self.tried:
            parts.append("## What it tried (latest last)\n" + "\n".join(f"- {t}" for t in self.tried))
        if self.consults:                      # DeepSeek keeps no session: an earlier answer is sent along again
            last = self.consults[-1]
            parts.append(f"## Advice already given ({last.get('model', '?')}, round {last['round']}); it did not "
                         "lead to progress, so look for another cause\n" + str(last.get("advice", ""))[:3000])
        text = "\n\n".join(parts)
        return text[:BRIEF_MAX]

    # ------------------------------------------------------------------ asking
    def consult(self, registry, why: str, key: str, model: str = FLASH, diff: str = "", approve=None,
                emit=None, *, prompt: str | None = None, system: str | None = None, note: str | None = None,
                max_tokens: int | None = None) -> str | None:
        """Ask DeepSeek through the registry; the note for the model's messages, or None when nothing came back."""
        self.asked.add(key)
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "round": self.round, "why": why, "key": key,
                 "model_wanted": model, "workspace": str(self.ctx.get("workspace") or "")}
        if registry is None or not getattr(registry, "active", False) or "deepseek" not in registry.catalog:
            entry["result"] = "no deepseek server in the MCP catalogue"
            self._log(entry)
            return None
        if not registry.owns(TOOL):
            out = registry.enable("deepseek", "the DeepSeek helper")
            if out.startswith("error") or not registry.owns(TOOL):
                entry["result"] = out[:200]
                self._log(entry)
                return None
        args = {"prompt": prompt if prompt is not None else self.brief(why, diff), "system": system or SYSTEM,
                "include_thinking": False, "model": model,
                "web": dl_profile.env("DL_ADVISOR_WEB", "0") == "1",
                # Pro thinks long and its thinking counts against max_tokens: 8192 left it 164 characters of answer
                "max_tokens": max_tokens or (32768 if model == PRO else 16384)}
        blocked = registry.leak(args)
        if blocked:
            entry["result"] = "blocked: the brief held a credential"
            self._log(entry)
            return None
        ask = registry.approval(TOOL, args)
        if ask and not self.ctx.get("yolo") and approve is not None:
            if not approve("tool", ask[0], "D.L. CLI's DeepSeek helper: " + ask[1]):
                entry["result"] = "denied by the user"
                self._log(entry)
                return None
        if emit:
            emit({"type": "notice", "level": "info",
                  "text": f"Asking DeepSeek for help: {why[:160]} (DL_ADVISOR=0 turns this off)."})
        t0 = time.time()
        text = registry.call(TOOL, args, cancel=self.ctx.get("cancel"))
        entry.update(seconds=round(time.time() - t0, 1), sent_chars=len(args["prompt"]), got_chars=len(text or ""))
        # a failed call starts with the registry's "error: " or the server's own error line; advice that merely
        # begins with the word "Error..." is advice
        if not text or text.lstrip().startswith(("error: ", "error:", "Error: DEEPSEEK_API_KEY", "DeepSeek API Error")):
            entry["result"] = (text or "empty")[:200]
            msg = f"DeepSeek helper failed: {(text or 'empty')[:160]}"
            if DEAD_END.search(text or ""):
                hold = _int("DL_ADVISOR_PAUSE_S", 3600)
                _PAUSE.update(until=time.time() + hold, why=(text or "")[:160])
                entry["paused_s"] = hold
                msg += (f" The helper is paused for {hold // 60} min (no model can answer: balance or key); Ray goes on "
                        "alone. After topping up, restart dl-ai-sessiond to resume at once.")
            self._log(entry)
            if emit:
                emit({"type": "notice", "level": "warn", "text": msg})
            return None
        m = re.search(r"\[model: ([^\];]+)", text)
        model = m.group(1) if m else "auto"
        advice = re.sub(r"\n*\[model: [^\]]*\]\s*$", "", text).strip()
        entry.update(result="ok", model=model, fails_before=self.best_fails)
        self.consults.append({**entry, "advice": advice[:3000]})    # kept for the next brief, not written to the log
        self.fails_since_consult = 0
        if model == PRO or entry["model_wanted"] == PRO:
            self.pro_used += 1
        self._log(entry)
        if emit and system != PATCH_SYSTEM:                    # patch() reports what it hands over itself
            emit({"type": "notice", "level": "info", "text": f"DeepSeek ({model}) answered in {entry['seconds']} s; "
                                                             "its advice was handed to Ray."})
        # a patch is parsed by patch(): it gets the whole answer (cut at 8,000 it lost its later blocks)
        return (note or NOTE).format(why=why[:200], model=model,
                                     advice=advice if system == PATCH_SYSTEM else advice[:8000])

    def patch(self, registry, why: str, key: str, model: str = FLASH, files: dict[str, str] | None = None,
              diff: str = "", approve=None, emit=None) -> str | None:
        """Patch mode: DeepSeek writes the fix for the files the stuck work is in.  The note hands Ray the blocks whose
        OLD text matches its file exactly once; with none valid, the answer goes to Ray as advice."""
        files = files or {}
        if not files:
            return self.consult(registry, why, key, model, diff=diff, approve=approve, emit=emit)
        body = [self.brief(why, diff)]
        budget = 60000 - len(body[0])
        for rel, text in files.items():
            chunk = f"## File {rel}\n```\n{text}\n```"
            if len(chunk) > budget:
                continue                        # a cut file cannot be patched exactly; leave it out
            body.append(chunk)
            budget -= len(chunk)
        if len(body) == 1:                      # no full file fit in the brief budget: ask for advice instead
            return self.consult(registry, why, key, model, diff=diff, approve=approve, emit=emit)
        answer = self.consult(registry, why, key, model, approve=approve, emit=emit, prompt="\n\n".join(body),
                              system=PATCH_SYSTEM, note="{advice}")
        if answer is None:
            return None
        got = self.consults[-1].get("model", model) if self.consults else model
        valid, bad, check = parse_patch(answer, Path(self.ctx.get("workspace") or "."))
        if self.consults:
            self.consults[-1].update(patch_blocks=len(valid), patch_rejected=len(bad))
        if not valid:
            if emit:
                emit({"type": "notice", "level": "warn", "text": f"DeepSeek ({got})'s patch did not match the files ("
                      + "; ".join(bad[:3] or ["no blocks"]) + "); handed to Ray as advice."})
            return NOTE.format(why=why[:200], model=got, advice=answer[:8000])
        ws = Path(self.ctx.get("workspace") or ".").resolve()
        shown = []
        for b in valid:
            rel = str(Path(b["file"]).relative_to(ws)) if ws in Path(b["file"]).parents else b["file"]
            shown.append(f"FILE: {rel}\n<<<OLD\n{b['old']}\n===\n{b['new']}\nNEW>>>")
        if bad:
            shown.append("(Dropped, they did not match the file: " + "; ".join(bad[:5]) + ".)")
        if emit:
            emit({"type": "notice", "level": "info", "text": f"DeepSeek ({got}) wrote a patch in "
                  f"{self.consults[-1].get('seconds', '?') if self.consults else '?'} s: {len(valid)} block(s)"
                  + (f", {len(bad)} dropped" if bad else "") + "; handed to Ray to apply and test."})
        return PATCH_NOTE.format(why=why[:200], model=got, patch="\n\n".join(shown)[:16000], check=check[:300])

    def review_plan(self, registry, plan: str, approve=None, emit=None) -> str | None:
        """Plan Mode: Pro reads Ray's finished plan once and lists gaps and risks; the note asks Ray to revise it before
        the Execute card.  None when it is off, refused, or nothing came back."""
        if not enabled() or dl_profile.env("DL_ADVISOR_PLAN_REVIEW", "1") == "0" or not (plan or "").strip():
            return None
        task = str(self.ctx.get("user_text") or "").strip()
        prompt = (f"## The user's request\n{task[:4000]}\n\n## The agent's plan\n{plan[:16000]}")
        return self.consult(registry, "plan review", "plan", model=PRO, approve=approve, emit=emit,
                            prompt=prompt, system=PLAN_SYSTEM, note=PLAN_NOTE)

    def final_review(self, registry, plan: str, report: str, files: dict[str, str], round_no: int,
                     approve=None, emit=None) -> tuple[str, str | None]:
        """A plan run that the agent says is done: Pro reviews the plan, the final report and the changed files.
        ('pass', None), ('fix', note to send the agent back with), or ('skip', None) when it could not ask."""
        if not enabled() or dl_profile.env("DL_ADVISOR_FINAL", "1") == "0":
            return "skip", None
        rounds = _int("DL_ADVISOR_FINAL_MAX", 5)
        body = [f"## The user's request\n{str(self.ctx.get('user_text') or '')[:3000]}",
                f"## The approved plan\n{plan[:12000]}", f"## The agent's final report\n{report[:5000]}"]
        budget = 60000 - sum(map(len, body))
        for name, text in files.items():
            chunk = f"## File {name}\n```\n{text}\n```"
            if len(chunk) > budget:
                chunk = chunk[:max(0, budget - 60)] + "\n[... file cut: the brief is full]\n```"
            body.append(chunk)
            budget -= len(chunk)
            if budget <= 0:
                break
        prompt = "\n\n".join(body)
        note = self.consult(registry, f"final review round {round_no}", f"final#{round_no}", model=PRO,
                            approve=approve, emit=emit, prompt=prompt, system=FINAL_SYSTEM,
                            note=FINAL_NOTE.replace("{round}", str(round_no)).replace("{max}", str(rounds)))
        if note is None:
            return "skip", None
        verdict = re.search(r"VERDICT:\s*(PASS|FIX)", note)
        if verdict and verdict.group(1) == "PASS":
            return "pass", None
        return "fix", note

    def finish(self) -> None:
        """At the end of the request: log whether each consult was followed by progress."""
        for c in self.consults:
            self._log({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "outcome_of": c["time"],
                       "progress_after": self.last_progress > c["round"], "fails_now": self.best_fails,
                       "rounds_after": self.round - c["round"]})

    @staticmethod
    def _log(entry: dict) -> None:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
