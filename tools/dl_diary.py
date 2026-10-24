"""tools/dl_diary.py - Autonomous Struggle & Incident Diary for Ray (D.L. CLI).

Monitors agent executions for friction (failures, inefficiencies, confusion, unasked clarifications,
and check interventions), logging incidents to an append-only JSONL index and a daily readable Markdown journal.
This journal provides grounded operational evidence for the human + Claude Opus / Antigravity improvement loop.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DIARY_DIR_DEFAULT = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    / "dl-ai"
    / "diary"
)

EXIT_CODE_RE = re.compile(r"\[Command exited with code (-?\d+)\]")
FILE_NOT_FOUND_RE = re.compile(r"(?:No such file or directory|FileNotFoundError|does not exist)", re.IGNORECASE)
USER_CORRECTIONS = (
    "that's wrong", "thats wrong", "didn't work", "didnt work", "doesn't work",
    "doesnt work", "why?", "no, i meant", "i meant", "not what i asked",
    "wrong file", "stop guessing", "you guessed",
)

CATEGORIES = (
    "FAILURE",
    "INEFFICIENCY",
    "CONFUSION",
    "UNASKED_CLARIFICATION",
    "INTERVENTION",
)


def get_diary_dir() -> Path:
    override = os.environ.get("DL_DIARY_DIR")
    p = Path(override) if override else DIARY_DIR_DEFAULT
    try:
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass
    return p


@dataclass
class IncidentReport:
    ts: float
    iso_time: str
    session_id: str
    workspace: str
    prompt: str
    categories: list[str] = field(default_factory=list)
    turns: int = 0
    tokens: int = 0
    duration_s: float = 0.0
    tool_calls_count: int = 0
    tool_errors_count: int = 0
    symptoms: list[str] = field(default_factory=list)
    clarification_gap: str | None = None
    transcript_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "iso_time": self.iso_time,
            "session_id": self.session_id,
            "workspace": self.workspace,
            "prompt": self.prompt,
            "categories": self.categories,
            "turns": self.turns,
            "tokens": self.tokens,
            "duration_s": round(self.duration_s, 2),
            "tool_calls_count": self.tool_calls_count,
            "tool_errors_count": self.tool_errors_count,
            "symptoms": self.symptoms,
            "clarification_gap": self.clarification_gap,
            "transcript_path": self.transcript_path,
        }


class FrictionTracker:
    """Tracks friction events throughout a single user request in execute_agent_loop."""

    def __init__(self, prompt: str, workspace: str, session_id: str = "dl-ai-code",
                 transcript_path: str | None = None):
        self.prompt = prompt.strip()
        self.workspace = workspace
        self.session_id = session_id
        self.transcript_path = transcript_path
        self.t_start = time.time()

        self.turns = 0
        self.tokens = 0
        self.tool_calls_count = 0
        self.tool_errors_count = 0
        self.seen_tool_calls: set[tuple[str, str]] = set()

        self.categories: set[str] = set()
        self.symptoms: list[str] = []
        self.clarification_gaps: list[str] = []

        # Check if the prompt itself is a correction of a previous turn
        p_low = self.prompt.lower()
        for corr in USER_CORRECTIONS:
            if corr in p_low:
                self.categories.add("UNASKED_CLARIFICATION")
                self.symptoms.append(f"User follow-up contained correction phrase: '{corr}'")
                self.clarification_gaps.append("Previous response made assumptions without clarifying with user")
                break

    def record_bad_arguments(self, fn_name: str, raw_args: str, err: str) -> None:
        self.categories.add("FAILURE")
        self.tool_errors_count += 1
        preview = (raw_args[:80] + "...") if len(raw_args) > 80 else raw_args
        self.symptoms.append(f"Malformed JSON arguments for {fn_name}: {err} (args: {preview})")

    def record_pseudo_tool_call(self, text_preview: str) -> None:
        self.categories.add("FAILURE")
        self.symptoms.append(f"Model emitted pseudo-tool call syntax in plain text: {text_preview[:120]}")

    def record_tool_dispatch(self, fn_name: str, args: dict, result_str: str) -> None:
        self.tool_calls_count += 1
        args_sig = json.dumps(args, sort_keys=True)
        call_key = (fn_name, args_sig)

        if call_key in self.seen_tool_calls:
            self.categories.add("INEFFICIENCY")
            self.symptoms.append(f"Repeated identical tool call: {fn_name}({args_sig[:60]}...)")
        self.seen_tool_calls.add(call_key)

        res_clean = (result_str or "").strip()
        is_err = False

        # Check for tool errors
        if res_clean.startswith("Error") or "is not a tool; ran" in res_clean:
            self.categories.add("FAILURE")
            is_err = True
            first_line = res_clean.splitlines()[0] if res_clean else "Unknown error"
            self.symptoms.append(f"Tool {fn_name} error: {first_line[:120]}")

            # Check if error is missing file/resource that model speculated on
            if FILE_NOT_FOUND_RE.search(first_line):
                self.categories.add("UNASKED_CLARIFICATION")
                self.symptoms.append(f"Model guessed non-existent target path/resource: {first_line[:100]}")
                self.clarification_gaps.append(f"Model speculated on path in {fn_name} instead of checking or asking")

        # Check for non-zero command exit
        m_exit = EXIT_CODE_RE.search(res_clean)
        if m_exit and m_exit.group(1) != "0":
            self.categories.add("FAILURE")
            is_err = True
            cmd = str(args.get("command") or args.get("CommandLine") or "")[:60]
            self.symptoms.append(f"Command failed (exit {m_exit.group(1)}): `{cmd}`")

        if is_err:
            self.tool_errors_count += 1

    def record_shrink_alarm(self, fn_name: str, details: str) -> None:
        self.categories.add("CONFUSION")
        self.symptoms.append(f"Shrink alarm triggered by {fn_name}: {details[:120]}")

    def record_check_intervention(self, check_name: str, reason: str) -> None:
        self.categories.add("INTERVENTION")
        self.symptoms.append(f"Sent back by {check_name}: {reason[:140]}")

    def record_stall_limit(self, plan_name: str, open_steps: int) -> None:
        self.categories.add("INEFFICIENCY")
        self.categories.add("INTERVENTION")
        self.symptoms.append(f"Plan stall limit reached on {plan_name} with {open_steps} open steps")

    def finalize(self, total_turns: int, total_tokens: int) -> IncidentReport | None:
        self.turns = total_turns
        self.tokens = total_tokens
        duration = time.time() - self.t_start

        # Detect high-cost / inefficiency
        if self.turns >= 10:
            self.categories.add("INEFFICIENCY")
            self.symptoms.append(f"High turn count: {self.turns} turns (>= 10)")
        if self.tokens >= 15000:
            self.categories.add("INEFFICIENCY")
            self.symptoms.append(f"High token consumption: {self.tokens:,} tokens (>= 15k)")
        if duration >= 180.0:
            self.categories.add("INEFFICIENCY")
            self.symptoms.append(f"Long execution duration: {duration:.1f}s (>= 3 minutes)")

        # Only record if there was friction
        if not self.categories and not self.symptoms:
            return None

        # Clean prompt for display
        clean_p = self.prompt.replace("\n", " ").strip()
        if len(clean_p) > 100:
            clean_p = clean_p[:97] + "..."

        clarification = "; ".join(self.clarification_gaps) if self.clarification_gaps else None

        now = time.time()
        iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        return IncidentReport(
            ts=now,
            iso_time=iso,
            session_id=self.session_id,
            workspace=str(self.workspace),
            prompt=clean_p or "(empty prompt)",
            categories=sorted(self.categories),
            turns=self.turns,
            tokens=self.tokens,
            duration_s=duration,
            tool_calls_count=self.tool_calls_count,
            tool_errors_count=self.tool_errors_count,
            symptoms=self.symptoms,
            clarification_gap=clarification,
            transcript_path=self.transcript_path,
        )


def log_incident(report: IncidentReport, diary_dir: Path | None = None) -> None:
    """Safely append incident to the JSONL index and daily Markdown log."""
    d_dir = diary_dir or get_diary_dir()
    try:
        # 1. Append to incidents.jsonl
        jsonl_path = d_dir / "incidents.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")

        # 2. Append to YYYY-MM-DD.md
        day_str = time.strftime("%Y-%m-%d", time.localtime(report.ts))
        md_path = d_dir / f"{day_str}.md"
        exists = md_path.exists()

        lines = []
        if not exists:
            lines.append(f"# Ray Struggle Diary - {day_str}\n")
            lines.append("Operational friction, failures, and unasked clarification gaps for review.\n\n")

        time_str = time.strftime("%H:%M:%S", time.localtime(report.ts))
        cats = " ".join(f"`[{c}]`" for c in report.categories)
        lines.append(f"### [{time_str}] {report.prompt}\n")
        lines.append(
            f"- **Session**: `{report.session_id}` | **Workspace**: `{report.workspace}` | "
            f"**Turns**: {report.turns} | **Tokens**: {report.tokens:,} | **Time**: {report.duration_s:.1f}s\n"
        )
        lines.append(f"- **Categories**: {cats}\n")
        lines.append("- **Symptoms**:\n")
        for s in report.symptoms:
            lines.append(f"  - {s}\n")
        if report.clarification_gap:
            lines.append(f"- **Clarification Gap**: {report.clarification_gap}\n")
        if report.transcript_path:
            lines.append(f"- **Transcript**: `{report.transcript_path}`\n")
        lines.append("\n---\n\n")

        with open(md_path, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        pass  # Disk or permission issues must never break the agent


def read_recent_incidents(n: int = 5, diary_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read the latest N incidents from the JSONL index."""
    d_dir = diary_dir or get_diary_dir()
    jsonl_path = d_dir / "incidents.jsonl"
    if not jsonl_path.is_file():
        return []
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
        results = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except ValueError:
                continue
            if len(results) >= n:
                break
        return results
    except OSError:
        return []


def format_recent_markdown(n: int = 5, diary_dir: Path | None = None) -> str:
    """Format recent incidents for display in CLI or Web Code tab."""
    incidents = read_recent_incidents(n=n, diary_dir=diary_dir)
    if not incidents:
        return "No friction incidents recorded in the diary yet. Ray runs clean!"

    out = [f"**Recent Struggle Diary Incidents (Last {len(incidents)}):**\n"]
    for inc in incidents:
        cats = " ".join(f"`[{c}]`" for c in inc.get("categories", []))
        out.append(f"• **[{inc.get('iso_time', '')}]** {inc.get('prompt', '')}")
        out.append(f"  {cats} · {inc.get('turns', 0)} turns · {inc.get('duration_s', 0):.1f}s")
        symptoms = inc.get("symptoms", [])
        if symptoms:
            for s in symptoms[:2]:
                out.append(f"    - {s}")
        if inc.get("clarification_gap"):
            out.append(f"    💡 *Clarification Gap*: {inc['clarification_gap']}")
        out.append("")
    return "\n".join(out).strip()
