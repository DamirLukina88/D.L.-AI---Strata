#!/usr/bin/env python3
"""weather_reasoning_bench.py - Benchmark D.L. CLI across reasoning levels (none, low, medium, high).

Executes the prompt:
    "I would like you to create a weather forecast table for me for todays and tomorrow's weather,
     our forecast and send it to me per email."

Evaluates:
  1. Location inference: Does the model infer "our forecast" -> Zagreb, Croatia (from user profile/timezone)
     instead of falling for the IP geolocation trap (Rijeka)?
  2. Weather forecast completeness: Did it fetch both today & tomorrow and format a structured table?
  3. Autonomous tool usage: Did it discover/enable and use Proton Mail?
  4. Email delivery: Did it send the email to the recipient (--recipient; default the profile's email) with subject and table?
  5. Telemetry: Thinking time, wall time, reasoning length, and tool turn efficiency.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import queue
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
DEFAULT_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "dl-ai" / "sessiond.sock"
DEFAULT_ROOT = Path.home() / ".cache" / "strata" / "bench" / "weather_reasoning"
DEFAULT_PROMPT = "I would like you to create a weather forecast table for me for todays and tomorrow's weather, our forecast and send it to me per email."
def _profile_email() -> str:
    """The user's address from ~/.config/dl-ai/profile.json ("email"), so none is written in the repository."""
    try:
        return str(json.loads((Path.home() / ".config" / "dl-ai" / "profile.json").read_text()).get("email") or "")
    except (OSError, ValueError, AttributeError):
        return ""


DEFAULT_RECIPIENT = _profile_email()

# ANSI Colors (Strata Palette)
C_ORANGE = "\033[38;5;208m"
C_WHITE = "\033[38;5;255m"
C_MUTED = "\033[38;5;244m"
C_GREEN = "\033[38;5;71m"
C_RED = "\033[38;5;203m"
C_YELLOW = "\033[38;5;220m"
C_CYAN = "\033[38;5;44m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HEDGE_RE = re.compile(r"\b(?:hmm+|actually|wait|let me check|thinking|perhaps)\b", re.I)


# ---------------------------------------------------------------------- Connection & Live Session
class LiveSession:
    """Attached connection to running dl-ai-sessiond daemon."""

    def __init__(self, session: str, sock_path: Path):
        self.session = session
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(str(sock_path))
        self.f = self.s.makefile("rwb")
        self.q: queue.Queue = queue.Queue()
        self.send(op="attach")
        hello = json.loads(self.f.readline())
        self.state = hello.get("state", {})
        self.closed = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        try:
            for line in self.f:
                if not line.strip():
                    continue
                self.q.put(json.loads(line.decode("utf-8", errors="replace")))
        except (OSError, ValueError):
            pass
        finally:
            self.closed = True
            self.q.put({"type": "_closed"})

    def send(self, **msg) -> None:
        payload = json.dumps({"session": self.session, **msg}, ensure_ascii=False) + "\n"
        self.f.write(payload.encode("utf-8"))
        self.f.flush()

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


def approval_filter(summary: str, ws: Path, allowed_email: str) -> bool:
    """Approves Proton Mail / Gmail to allowed_email, and safe filesystem operations."""
    low = summary.lower()
    if "send_mail" in low or "send_gmail_message" in low or "send mail" in low:
        addrs = {a.lower() for a in EMAIL_RE.findall(summary)}
        if allowed_email.lower() in addrs:
            return True
        if not addrs:
            return True
        return False

    # Standard safe filesystem check
    if "~" in summary or ".." in summary:
        return False
    roots = (str(ws), "/tmp", "/dev/null")
    paths = re.findall(r"(?<![\w.\-])(/[^\s'\";|&<>()]+)", summary)
    return all(any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots) for p in paths)


def drive_turn(live: LiveSession, text: str, ws: Path, timeout: float, allowed_email: str) -> dict:
    """Send one prompt and follow until turn end."""
    rec = {
        "text": text,
        "tool_calls": [],
        "tool_results": [],
        "approvals": [],
        "errors": [],
        "thinking": [],
        "tokens": 0,
        "seconds": 0.0,
    }
    t0 = time.time()
    live.send(op="input", text=text, origin="bench")

    interrupted = False
    finished = False
    texts = []
    think_chunks: list[str] = []
    think_t0: float | None = None

    def close_think(ts: float):
        nonlocal think_chunks, think_t0
        if think_chunks:
            full_think = "".join(think_chunks)
            dur = max(0.0, ts - (think_t0 or ts))
            rec["thinking"].append({
                "chars": len(full_think),
                "words": len(full_think.split()),
                "seconds": round(dur, 2),
                "text": full_think,
            })
            think_chunks = []
            think_t0 = None

    while True:
        try:
            ev = live.q.get(timeout=1.0)
        except queue.Empty:
            elapsed = time.time() - t0
            if not interrupted and elapsed > timeout:
                live.send(op="interrupt")
                interrupted = True
                rec["timed_out"] = True
            if interrupted and elapsed > timeout + 60:
                rec["errors"].append("Agent did not terminate after interrupt")
                break
            continue

        etype = ev.get("type")
        ts = ev.get("ts") or time.time()

        if etype == "thinking":
            if think_t0 is None:
                think_t0 = ts
            think_chunks.append(ev.get("text", ""))
            continue

        if etype in ("text", "tool_call", "stats", "error", "turn_end", "_closed"):
            close_think(ts)

        if etype == "_closed":
            rec["errors"].append("Connection to dl-ai-sessiond closed")
            break
        elif etype == "turn_end":
            break
        elif etype == "tool_call":
            rec["tool_calls"].append({"name": ev.get("name", ""), "args": ev.get("args") or {}})
            texts = []
        elif etype == "tool_result":
            rec["tool_results"].append({"name": ev.get("name", ""), "text": ev.get("text", "")[:3000]})
            texts = []
        elif etype == "text":
            texts.append(ev.get("text", ""))
        elif etype == "stats":
            rec["tokens"] += int(ev.get("tokens") or 0)
            finished = True
        elif etype == "error":
            rec["errors"].append(ev.get("text", ""))
        elif etype == "approval_request":
            summary = ev.get("summary", "")
            ok = approval_filter(summary, ws, allowed_email)
            rec["approvals"].append({"summary": summary[:300], "ok": ok})
            live.send(op="approve" if ok else "deny", id=ev.get("id"))

    close_think(time.time())
    rec["seconds"] = round(time.time() - t0, 1)
    rec["final_text"] = "".join(texts)
    rec["finished"] = finished
    return rec


# ---------------------------------------------------------------------- Scoring Rubric
def score_reasoning_turn(steps: list[dict], recipient: str) -> dict:
    """Calculates 100-pt scorecard and detailed verification breakdown."""
    all_calls = [c for s in steps for c in s.get("tool_calls", [])]
    all_results = [r for s in steps for r in s.get("tool_results", [])]
    all_text = " ".join([s.get("final_text", "") for s in steps] +
                        [str(c.get("args", "")) for c in all_calls] +
                        [r.get("text", "") for r in all_results]).lower()

    # 1. Location Inference (25 pts)
    # The intentional test: "our forecast" -> Zagreb, Croatia.
    # IP Geolocation trap points to Rijeka.
    zagreb_detected = "zagreb" in all_text
    rijeka_trap = "rijeka" in all_text and not zagreb_detected
    location_pts = 0
    location_note = "No location inferred"
    if zagreb_detected:
        location_pts = 25
        location_note = "Correct: Inferred Zagreb from user profile/timezone"
    elif rijeka_trap:
        location_pts = 0
        location_note = "FAILED: Fell for IP geolocation trap (used Rijeka instead of Zagreb)"

    # 2. Forecast Table Quality (25 pts)
    # Needs today, tomorrow, temperatures, conditions, table formatting
    today_found = bool(re.search(r"\b(today|danas|17\.|oct 17|subota|saturday)\b", all_text))
    tomorrow_found = bool(re.search(r"\b(tomorrow|sutra|18\.|oct 18|nedjelja|sunday)\b", all_text))
    temps_found = bool(re.search(r"\b\d{1,2}\s*(?:°|c|deg)", all_text))
    table_structure = bool(re.search(r"(\|[ -]+\|)|(<table|<tr|<th|<td)", all_text))

    table_pts = 0
    table_reasons = []
    if today_found and tomorrow_found:
        table_pts += 10
        table_reasons.append("today+tomorrow")
    elif today_found or tomorrow_found:
        table_pts += 5
        table_reasons.append("partial dates")
    if temps_found:
        table_pts += 5
        table_reasons.append("temperatures")
    if table_structure:
        table_pts += 10
        table_reasons.append("table format")
    table_note = ", ".join(table_reasons) if table_reasons else "Missing structured forecast table"

    # 3. Email Dispatch via Proton (25 pts)
    # Proton tool: proton__send_mail or send_mail
    mail_calls = [c for c in all_calls if "send_mail" in c.get("name", "") or "send_gmail" in c.get("name", "")]
    proton_calls = [c for c in all_calls if "send_mail" in c.get("name", "")]

    mail_pts = 0
    mail_reasons = []
    if proton_calls:
        mail_pts += 10
        mail_reasons.append("proton tool called")
    elif mail_calls:
        mail_pts += 5
        mail_reasons.append("other mail tool called")

    # Check recipient
    to_recipient = False
    for c in mail_calls:
        args_str = json.dumps(c.get("args", {})).lower()
        if recipient.lower() in args_str:
            to_recipient = True
            break
    if to_recipient:
        mail_pts += 10
        mail_reasons.append(f"sent to {recipient}")

    # Check send result (no error)
    mail_sent_ok = False
    for r in all_results:
        if "send_mail" in r.get("name", "") and not r.get("text", "").startswith(("Error", "Traceback")):
            mail_sent_ok = True
            break
    if mail_sent_ok:
        mail_pts += 5
        mail_reasons.append("smtp success")
    mail_note = ", ".join(mail_reasons) if mail_reasons else "No email dispatched"

    # 4. Reasoning & Tool Efficiency (25 pts)
    # Check autonomous MCP activation or tool success, and turn efficiency
    efficiency_pts = 0
    eff_reasons = []

    mcp_tool_called = any(c.get("name") == "mcp" for c in all_calls)
    if mcp_tool_called or proton_calls:
        efficiency_pts += 10
        eff_reasons.append("autonomous tool discovery")

    # Turn efficiency: prompt + response in <= 4 turns = 10 pts, <= 6 = 7 pts, <= 8 = 4 pts
    turn_count = len(all_calls)
    if turn_count <= 4:
        efficiency_pts += 10
        eff_reasons.append(f"high turn efficiency ({turn_count} calls)")
    elif turn_count <= 6:
        efficiency_pts += 7
        eff_reasons.append(f"moderate turn efficiency ({turn_count} calls)")
    elif turn_count <= 8:
        efficiency_pts += 4
        eff_reasons.append(f"adequate turns ({turn_count} calls)")

    # No fatal errors
    has_errors = any(s.get("errors") for s in steps)
    if not has_errors:
        efficiency_pts += 5
        eff_reasons.append("zero errors")
    efficiency_note = ", ".join(eff_reasons) if eff_reasons else "Inefficient or error encountered"

    total_score = min(100, location_pts + table_pts + mail_pts + efficiency_pts)

    # Telemetry roll-up
    all_thinks = [t for s in steps for t in s.get("thinking", [])]
    think_seconds = sum(t.get("seconds", 0) for t in all_thinks)
    think_chars = sum(t.get("chars", 0) for t in all_thinks)
    think_words = sum(t.get("words", 0) for t in all_thinks)
    longest_think = max((t.get("chars", 0) for t in all_thinks), default=0)
    wall_seconds = sum(s.get("seconds", 0) for s in steps)

    return {
        "total_score": total_score,
        "location": {"score": location_pts, "max": 25, "note": location_note},
        "forecast_table": {"score": table_pts, "max": 25, "note": table_note},
        "email_delivery": {"score": mail_pts, "max": 25, "note": mail_note},
        "efficiency": {"score": efficiency_pts, "max": 25, "note": efficiency_note},
        "telemetry": {
            "wall_seconds": round(wall_seconds, 1),
            "think_seconds": round(think_seconds, 1),
            "think_chars": think_chars,
            "think_words": think_words,
            "longest_think_chars": longest_think,
            "tool_calls": len(all_calls),
            "tool_names": list(dict.fromkeys(c.get("name", "") for c in all_calls)),
        }
    }


# ---------------------------------------------------------------------- Single Level Runner
def run_level(effort: str, run_dir: Path, timeout_minutes: float, max_turns: int,
              sock_path: Path, prompt: str, recipient: str) -> dict:
    """Executes a single reasoning level run."""
    ws = run_dir / f"ws-{effort}"
    ws.mkdir(parents=True, exist_ok=True)
    session = f"bench-weather-{effort}-{int(time.time())}"[:64]

    print(f"\n{C_BOLD}{C_ORANGE}▶ Starting Level: thinking={effort}{C_RESET} (session: {session})", flush=True)
    print(f"  {C_MUTED}Watch live: python3 tools/dl_cli.py --attach {session}{C_RESET}", flush=True)

    live = LiveSession(session, sock_path)
    steps: list[dict] = []
    timeout_s = timeout_minutes * 60.0

    try:
        # Session initialization: clean slate, task dir, and set effort
        for cmd in ("/clear", f"/cd {ws}", f"/effort {effort}"):
            live.send(op="input", text=cmd, origin="bench")
            while True:
                try:
                    ev = live.q.get(timeout=10.0)
                    if ev.get("type") in ("turn_end", "stats", "_closed"):
                        break
                except queue.Empty:
                    break

        # Step 1: Send the primary prompt
        step1 = drive_turn(live, prompt, ws, timeout_s, recipient)
        steps.append(step1)

        # Optional follow-up turns if agent pauses with questions or incomplete actions
        turns_left = max_turns - 1
        while turns_left > 0:
            last = steps[-1]
            if last.get("timed_out") or last.get("finished"):
                break
            # If agent requested something or did a tool call but didn't finish
            if last.get("tool_calls") and not last.get("finished"):
                step_next = drive_turn(live, "continue", ws, timeout_s, recipient)
                steps.append(step_next)
                turns_left -= 1
            else:
                break

    finally:
        live.close()

    # Save step trace
    log_file = run_dir / f"{effort}.steps.jsonl"
    with log_file.open("w", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    score_card = score_reasoning_turn(steps, recipient)
    score_card["effort"] = effort
    score_card["session"] = session
    score_card["workspace"] = str(ws)

    t = score_card["telemetry"]
    print(f"  {C_BOLD}Score:{C_RESET} {score_card['total_score']}/100 | "
          f"{C_BOLD}Wall:{C_RESET} {t['wall_seconds']}s | "
          f"{C_BOLD}Think:{C_RESET} {t['think_seconds']}s ({t['think_chars']} ch) | "
          f"{C_BOLD}Calls:{C_RESET} {t['tool_calls']} {t['tool_names']}", flush=True)

    return score_card


# ---------------------------------------------------------------------- Sweep & Output Report
def format_summary_table(results: list[dict]) -> str:
    """Markdown comparison table."""
    headers = [
        "Thinking Level",
        "Score",
        "Location (Zagreb)",
        "Forecast Table",
        "Email (Proton)",
        "Wall Time",
        "Think Time",
        "Think Chars",
        "Calls"
    ]
    rows = []
    for r in results:
        t = r["telemetry"]
        rows.append([
            f"**{r['effort']}**",
            f"**{r['total_score']}/100**",
            f"{r['location']['score']}/25 ({r['location']['note'][:20]}...)" if len(r['location']['note']) > 20 else f"{r['location']['score']}/25",
            f"{r['forecast_table']['score']}/25",
            f"{r['email_delivery']['score']}/25",
            f"{t['wall_seconds']}s",
            f"{t['think_seconds']}s",
            f"{t['think_chars']}",
            f"{t['tool_calls']}"
        ])

    col_widths = [max(len(row[i]) for row in [headers] + rows) for i in range(len(headers))]
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    data_lines = ["| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)) + " |" for row in rows]
    return "\n".join([header_line, sep_line] + data_lines)


def run_benchmark(efforts: list[str], root_dir: Path, timeout_minutes: float,
                  max_turns: int, sock_path: Path, prompt: str, recipient: str, label: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root_dir / f"{timestamp}-{label}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{C_BOLD}{C_ORANGE}======================================================================{C_RESET}")
    print(f"{C_BOLD}{C_ORANGE}  D.L. CLI Weather Reasoning Benchmark Sweep{C_RESET}")
    print(f"{C_BOLD}{C_ORANGE}======================================================================{C_RESET}")
    print(f"  {C_BOLD}Efforts:{C_RESET}     {', '.join(efforts)}")
    print(f"  {C_BOLD}Timeout:{C_RESET}     {timeout_minutes} minutes per level")
    print(f"  {C_BOLD}Turns max:{C_RESET}   {max_turns}")
    print(f"  {C_BOLD}Prompt:{C_RESET}      \"{prompt}\"")
    print(f"  {C_BOLD}Recipient:{C_RESET}   {recipient}")
    print(f"  {C_BOLD}Run Dir:{C_RESET}     {run_dir}\n")

    results = []
    for effort in efforts:
        res = run_level(
            effort=effort,
            run_dir=run_dir,
            timeout_minutes=timeout_minutes,
            max_turns=max_turns,
            sock_path=sock_path,
            prompt=prompt,
            recipient=recipient
        )
        results.append(res)

    # Save results.json
    results_file = run_dir / "results.json"
    results_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Generate Markdown Report
    table_md = format_summary_table(results)
    report_md = f"""# Weather Reasoning Benchmark Report
**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Prompt:** *"{prompt}"*
**Target Recipient:** `{recipient}`
**Levels Tested:** {', '.join(efforts)}

## Comparison Summary

{table_md}

## Detailed Observations

"""
    for r in results:
        t = r["telemetry"]
        report_md += f"""### Reasoning Level: `{r['effort']}` (Total Score: {r['total_score']}/100)
- **Location Inference:** {r['location']['score']}/25 - {r['location']['note']}
- **Weather Table:** {r['forecast_table']['score']}/25 - {r['forecast_table']['note']}
- **Email Delivery:** {r['email_delivery']['score']}/25 - {r['email_delivery']['note']}
- **Tool & Turn Efficiency:** {r['efficiency']['score']}/25 - {r['efficiency']['note']}
- **Telemetry:** Wall: {t['wall_seconds']}s | Thinking: {t['think_seconds']}s ({t['think_chars']} chars) | Tools called: {t['tool_calls']} {t['tool_names']}

"""

    report_file = run_dir / "report.md"
    report_file.write_text(report_md, encoding="utf-8")

    print(f"\n{C_BOLD}{C_GREEN}✔ Benchmark Sweep Finished Successfully!{C_RESET}")
    print(f"\n{table_md}\n")
    print(f"Full report saved to: {report_file}")
    print(f"Structured results:   {results_file}\n")


# ---------------------------------------------------------------------- Main
def main():
    parser = argparse.ArgumentParser(description="Weather Reasoning Benchmark across CLI thinking levels")
    parser.add_argument("--efforts", default="none,low,medium,high",
                        help="Comma-separated list of thinking efforts to test (default: none,low,medium,high)")
    parser.add_argument("--timeout-minutes", type=float, default=20.0,
                        help="Minutes timeout per reasoning level turn (default: 20.0)")
    parser.add_argument("--max-turns", type=int, default=10,
                        help="Maximum turns per level (default: 10)")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET),
                        help=f"Socket path for dl-ai-sessiond (default: {DEFAULT_SOCKET})")
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help=f"Directory to store benchmark outputs (default: {DEFAULT_ROOT})")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT,
                        help="Prompt to execute across each level")
    parser.add_argument("--recipient", default=DEFAULT_RECIPIENT,
                        help="Target recipient email for Proton Mail")
    parser.add_argument("--label", default="sweep",
                        help="Run directory label prefix")

    args = parser.parse_args()

    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
    valid_efforts = {"none", "low", "medium", "high"}
    invalid = [e for e in efforts if e not in valid_efforts]
    if invalid:
        print(f"{C_RED}Error: Invalid effort level(s): {invalid}. Valid options are: {sorted(valid_efforts)}{C_RESET}",
              file=sys.stderr)
        sys.exit(1)

    sock = Path(args.socket)
    if not sock.exists():
        print(f"{C_RED}Error: dl-ai-sessiond socket not found at {sock}. Is dl-ai-sessiond running?{C_RESET}",
              file=sys.stderr)
        sys.exit(1)

    run_benchmark(
        efforts=efforts,
        root_dir=Path(args.root),
        timeout_minutes=args.timeout_minutes,
        max_turns=args.max_turns,
        sock_path=sock,
        prompt=args.prompt,
        recipient=args.recipient,
        label=args.label
    )


if __name__ == "__main__":
    main()
