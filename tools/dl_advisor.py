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

TOOL = "deepseek__deepseek_reason"
FLASH = "auto"             # the newest Flash model (deepseek_mcp.model_ladder), stepping down if it is unavailable
PRO = "deepseek-v4-pro"
LOG = Path(os.environ.get("DL_ADVISOR_LOG") or Path.home() / ".local" / "state" / "dl-ai" / "advisor.jsonl")
BRIEF_MAX = 24000          # characters (about 6-8k tokens)
FAIL_LINE = re.compile(r"^.*\b(FAIL(?:ED)?|Error|Exception|Traceback|AssertionError|not ok)\b.*$", re.M)
COUNT_FAIL = re.compile(r"\bFAIL(?:ED)?\b|\bnot ok\b")
EXIT_CODE = re.compile(r"\[Command exited with code (\d+)\]")

SYSTEM = ("You are a senior software engineer advising a smaller local coding agent that is stuck. You cannot run "
          "anything; you see a brief of its task, the failing output, its code changes and what it already tried. "
          "Find the root cause. Say plainly whether the code or the test is wrong. Give the next concrete steps "
          "(at most 10 short lines), naming exact files, functions and lines, with a small code snippet only where "
          "it is needed. Do not rewrite whole files. If the brief lacks what you need, say which file or output to "
          "look at next.")

NOTE = ("[D.L. CLI] You were stuck ({why}), so D.L. CLI asked a stronger model (DeepSeek, {model}) for a second "
        "opinion. Its advice:\n\n{advice}\n\nCheck it against the code before you apply it - you know the files, it "
        "only saw a brief. Then continue the task.")


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


def enabled() -> bool:
    return os.environ.get("DL_ADVISOR", "0") == "1" and paused() is None


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
    line = (m.group(0) if m else f"exit code {code.group(1)}").strip()
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
        self.consults: list[dict] = []
        self.asked: set[str] = set()
        self.tried: list[str] = []
        self.last_fail_text = ""
        self.pro_used = 0
        self.fails_since_consult = 0

    # ------------------------------------------------------------------ signals
    def note_raise(self, reason: str | None) -> None:
        if reason:
            self.raises.append(reason)

    def note_result(self, name: str, args: dict, result: str) -> None:
        """One tool result: what was tried, whether it failed, and whether it was progress."""
        arg = ""
        if isinstance(args, dict):
            arg = str(args.get("CommandLine") or args.get("command") or args.get("TargetFile") or args.get("path")
                      or args.get("AbsolutePath") or args.get("query") or "")
        head = (result or "").strip().splitlines()[0][:90] if (result or "").strip() else ""
        self.tried.append(f"{name} {arg[:120]!s} -> {head}")
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

    def end_round(self) -> None:
        self.round += 1

    # ------------------------------------------------------------------ decision
    def stuck(self) -> tuple[str, str, str] | None:
        """(why, problem key, model) when the helper should ask now, else None."""
        if not enabled() or len(self.consults) >= _int("DL_ADVISOR_MAX", 3):
            return None
        effort = self.ctx.get("effort")
        if self.ctx.get("effort_auto") and effort != "high":
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
        loops = [r for r in self.raises if r in ("thinking loop", "repeated tool call", "tool call sent as text")]
        if len(loops) >= 2 and "loops" not in self.asked:
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
        text = "\n\n".join(parts)
        return text[:BRIEF_MAX]

    # ------------------------------------------------------------------ asking
    def consult(self, registry, why: str, key: str, model: str = FLASH, diff: str = "", approve=None,
                emit=None, *, prompt: str | None = None, system: str | None = None, note: str | None = None) -> str | None:
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
                "web": os.environ.get("DL_ADVISOR_WEB", "0") == "1"}
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
        if not text or text.lstrip().lower().startswith(("error", "deepseek api error")):
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
        self.consults.append(entry)
        self.fails_since_consult = 0
        if model == PRO or entry["model_wanted"] == PRO:
            self.pro_used += 1
        self._log(entry)
        if emit:
            emit({"type": "notice", "level": "info", "text": f"DeepSeek ({model}) answered in {entry['seconds']} s; "
                                                             "its advice was handed to Ray."})
        return (note or NOTE).format(why=why[:200], model=model, advice=advice[:8000])

    def review_plan(self, registry, plan: str, approve=None, emit=None) -> str | None:
        """Plan Mode: Pro reads Ray's finished plan once and lists gaps and risks; the note asks Ray to revise it before
        the Execute card.  None when it is off, refused, or nothing came back."""
        if not enabled() or os.environ.get("DL_ADVISOR_PLAN_REVIEW", "1") == "0" or not (plan or "").strip():
            return None
        task = str(self.ctx.get("user_text") or "").strip()
        prompt = (f"## The user's request\n{task[:4000]}\n\n## The agent's plan\n{plan[:16000]}")
        return self.consult(registry, "plan review", "plan", model=PRO, approve=approve, emit=emit,
                            prompt=prompt, system=PLAN_SYSTEM, note=PLAN_NOTE)

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
