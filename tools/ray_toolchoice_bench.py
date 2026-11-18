#!/usr/bin/env python3
"""ray_toolchoice_bench.py - does Ray turn on an MCP server only when the request needs one, and then the right one?

    python tools/ray_toolchoice_bench.py run --label before             # every case 3 times, ~40 min on the RX 7600 XT
    python tools/ray_toolchoice_bench.py run --label after --repeat 1 --cases N1,W2
    python tools/ray_toolchoice_bench.py score RUN_DIR                  # re-score a finished run (no model)
    python tools/ray_toolchoice_bench.py compare RUN_DIR_A RUN_DIR_B

The 2026-11-15 live check: "17 times 23" made Ray turn on Playwright and answer after 495 s.  This set has prompts that
need no server (arithmetic, a definition, a conversion: `want` is empty) and prompts that need one (`want`: any of the
named servers or tools counts).  Each run goes through the running dl-ai-sessiond in its own session
(rtc-<run>-<case>-<n>), as tools/ray_persona_bench.py does; the user's session is not touched.  Every approval card is
answered with no: which server Ray reaches for is what is scored, not whether the task finishes, and nothing is sent,
written or clicked on the user's behalf.

Per run it records: the servers turned on and why ("asked by the model", "matched '...'", "similar: ..."), the tool
calls, the seconds to the first text and to the end of the turn, and the model's thinking (to find out why it reached
for a server).  A no-server case passes when no MCP server was turned on, asked for or called (a shell command to check a fact is
not a miss); a server case passes
when one of its servers or tools was.  RUN_DIR/results.json and report.md; the prompts are fixed and not personal.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import queue
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_agent_bench as bench  # noqa: E402  (Live, drive, code_identity)

# want: () = no server; else the servers or built-in tools of which one must be turned on or called
CASES = [
    dict(id="N1", text="17 times 23", want=()),
    dict(id="N2", text="What is 15% of 240?", want=()),
    dict(id="N3", text="How many seconds are in a day?", want=()),
    dict(id="N4", text="Convert 72 Fahrenheit to Celsius.", want=()),
    dict(id="N5", text="What does the word ephemeral mean?", want=()),
    dict(id="N6", text="What's the capital of Australia?", want=()),
    dict(id="N7", text="Is 97 a prime number?", want=()),
    dict(id="N8", text="Write a haiku about rain.", want=()),
    dict(id="N9", text="What's the difference between a list and a tuple in Python? Two sentences.", want=()),
    dict(id="N10", text="Spell the word necessary backwards.", want=()),
    dict(id="N11", text="What is the square root of 144?", want=()),
    dict(id="N12", text="Explain what DNS is in two sentences.", want=()),
    dict(id="N13", text="What's 2 to the power of 16?", want=()),
    dict(id="N14", text="If a train travels 60 km in 45 minutes, what is its average speed in km/h?", want=()),
    dict(id="N15", text="Give me three synonyms for happy.", want=()),
    dict(id="W1", text="What's the weather in Zagreb tomorrow?", want=("weather", "exa", "fetch")),
    dict(id="W2", text="Open https://example.com in the browser and tell me the page's heading.",
         want=("playwright", "fetch")),
    dict(id="W3", text="Is the 3D printer printing anything right now?", want=("homeassistant",)),
    dict(id="W4", text="Translate \"good morning, how are you\" into German.", want=("deepl",)),
    dict(id="W5", text="Search the web for the latest stable Python release and tell me its version.",
         want=("exa", "fetch", "playwright")),
    dict(id="W6", text="Find a recent arXiv paper about mixture-of-experts inference and give me its title.",
         want=("arxiv", "exa", "openalex")),
    dict(id="W7", text="Are there any ZET tram service alerts in Zagreb right now?", want=("zagreb", "exa", "fetch")),
    dict(id="W8", text="Read https://example.org and tell me how many links are on the page.",
         want=("fetch", "playwright")),
    dict(id="W9", text="Does the Python package requests 2.19.0 have known vulnerabilities?", want=("osv", "exa")),
    dict(id="W10", text="What is the molecular weight of caffeine according to PubChem?", want=("pubchem", "exa")),
    dict(id="W11", text="Which RFC defines HTTP/2? Look it up, don't answer from memory.", want=("rfc", "exa", "fetch")),
    dict(id="W12", text="How much VRAM does the home server's graphics card have in use right now?",
         want=("get_system_health", "get_engine_status", "run_command", "ray_identity")),
]

ENABLED = re.compile(r"\+([A-Za-z0-9_]+)(?: \(([^)]*)\))?")


def one_turn(live, text: str, timeout: float) -> dict:
    """One prompt, followed until its turn ends.  Approvals are answered with no."""
    rec = {"enabled": [], "tool_calls": [], "notices": [], "thinking": "", "approvals": [], "errors": [],
           "first_text_s": None, "reply": ""}
    t0 = time.time()
    live.send(op="input", text=text, origin="bench")
    interrupted = False
    while True:
        # the limit is checked on every pass: while the model thinks or writes, an event comes every chunk and
        # q.get never timed out, so --timeout never interrupted a long turn (the 495 s "17 times 23")
        if not interrupted and time.time() - t0 > timeout:
            live.send(op="interrupt")
            interrupted, rec["timed_out"] = True, True
        if interrupted and time.time() - t0 > timeout + 120:
            rec["errors"].append("did not stop after interrupt")
            break
        try:
            ev = live.q.get(timeout=1)
        except queue.Empty:
            continue
        t = ev.get("type")
        if t in ("turn_end", "_closed"):
            if t == "_closed":
                rec["errors"].append("lost the connection to dl-ai-sessiond")
            break
        if t == "thinking":
            rec["thinking"] += ev.get("text", "")
        elif t == "text":
            if rec["first_text_s"] is None:
                rec["first_text_s"] = round(time.time() - t0, 1)
            rec["reply"] += ev.get("text", "")
        elif t == "tool_call":
            rec["tool_calls"].append({"name": ev.get("name", ""), "args": ev.get("args") or {},
                                      **({"skipped": ev["skipped"]} if ev.get("skipped") else {})})
            rec["reply"] = ""
        elif t == "notice":
            note = ev.get("text", "")
            rec["notices"].append(note[:200])
            m = ENABLED.search(note) if "MCP" in note else None
            if m:
                rec["enabled"].append({"server": m.group(1), "why": m.group(2) or ""})
        elif t == "error":
            rec["errors"].append(ev.get("text", ""))
        elif t == "approval_request" and ev.get("kind") != "plan":
            rec["approvals"].append(ev.get("summary", "")[:200])
            live.send(op="deny", id=ev["id"])
    rec["seconds"] = round(time.time() - t0, 1)
    rec["thinking"] = rec["thinking"][-6000:]
    return rec


def servers_used(rec: dict) -> set[str]:
    """Every server turned on, every server whose tool was called (name__tool), and every built-in tool called."""
    used = {e["server"] for e in rec["enabled"]}
    for c in rec["tool_calls"]:
        name = c["name"]
        if name == "mcp":
            if str(c["args"].get("action")) == "enable":
                used |= {s.strip() for s in str(c["args"].get("server") or "").split(",") if s.strip()}
            continue
        used.add(name.split("__", 1)[0] if "__" in name else name)
    return used


def mcp_used(rec: dict) -> set[str]:
    """Only the MCP servers: turned on, asked for, or called (name__tool)."""
    used = {e["server"] for e in rec["enabled"]}
    for c in rec["tool_calls"]:
        if c["name"] == "mcp" and str(c["args"].get("action")) == "enable":
            used |= {s.strip() for s in str(c["args"].get("server") or "").split(",") if s.strip()}
        elif "__" in c["name"]:
            used.add(c["name"].split("__", 1)[0])
    return used


def passed(case: dict, rec: dict) -> bool:
    """No-server case: no MCP server turned on, asked for or called, and an answer.  A built-in tool (a shell command
    to check a prime) is not a miss: that is evidence, and the user accepted it (2026-11-16).  Server case: one of
    its servers or tools was reached for."""
    if not case["want"]:
        return not mcp_used(rec) and bool(rec["reply"].strip())
    return bool(servers_used(rec) & set(case["want"]))


def report(res: dict) -> str:
    by_id = {c["id"]: c for c in CASES}
    rows, none_ok, none_n, need_ok, need_n = [], 0, 0, 0, 0
    for cid in dict.fromkeys(r["id"] for r in res["results"]):
        runs = [r for r in res["results"] if r["id"] == cid]
        case = by_id[cid]
        ok = sum(r["ok"] for r in runs)
        if case["want"]:
            need_ok, need_n = need_ok + ok, need_n + len(runs)
        else:
            none_ok, none_n = none_ok + ok, none_n + len(runs)
        used = sorted({s for r in runs for s in servers_used(r["rec"])})
        why = sorted({e["why"] for r in runs for e in r["rec"]["enabled"] if e["why"]})
        first = [r["rec"]["first_text_s"] for r in runs if r["rec"]["first_text_s"] is not None]
        end = [r["rec"]["seconds"] for r in runs]
        rows.append(f"| {cid} | {case['text'][:60]} | {', '.join(case['want']) or 'none'} | {ok}/{len(runs)} | "
                    f"{', '.join(used) or '-'} | {'; '.join(why) or '-'} | "
                    f"{(sorted(first)[len(first) // 2] if first else '-')} | {sorted(end)[len(end) // 2]} |")
    head = (f"# Ray tool choice: {res['label']} ({res['started']}, {res['repeat']} run(s) per case)\n\n"
            f"- Needs no server: {none_ok}/{none_n} runs stayed without one.\n"
            f"- Needs a server: {need_ok}/{need_n} runs reached for a right one.\n\n")
    return (head + "| Case | Prompt | Wanted | Passed | Reached for | Why turned on | First text s (median) | "
            "Turn s (median) |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")


def cmd_run(a) -> int:
    code = bench.code_identity()
    if code["changed_since_daemon_start"] and not a.stale_ok:
        print(f"dl-ai-sessiond is older than {code['changed_since_daemon_start']}: "
              "systemctl --user restart dl-ai-sessiond (or --stale-ok)", file=sys.stderr)
        return 2
    run = f"{datetime.datetime.now():%Y%m%d-%H%M}-{a.label}"
    run_dir = Path(a.out) / run
    run_dir.mkdir(parents=True, exist_ok=True)
    sock = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "dl-ai" / "sessiond.sock"
    want = set(a.cases.split(",")) if a.cases else None
    res = {"label": a.label, "started": datetime.datetime.now().isoformat(timespec="seconds"), "code": code,
           "repeat": a.repeat, "results": []}
    for n in range(1, a.repeat + 1):                    # round by round: a run cut short still has every case
        for case in CASES:
            if want and case["id"] not in want:
                continue
            print(f"{case['id']} #{n} ...", end=" ", flush=True)
            try:
                live = bench.Live(f"rtc-{run}-{case['id']}-{n}", sock)
                try:
                    ws = Path(live.state.get("workspace") or ".")
                    bench.drive(live, "/clear", ws, 60)
                    rec = one_turn(live, case["text"], a.timeout)
                finally:
                    live.close()
            except Exception as e:                      # one broken case never ends the run
                rec = {"enabled": [], "tool_calls": [], "notices": [], "thinking": "", "approvals": [],
                       "errors": [str(e)], "first_text_s": None, "reply": "", "seconds": 0}
            ok = passed(case, rec)
            res["results"].append({"id": case["id"], "n": n, "ok": ok, "rec": rec})
            print(("pass" if ok else "FAIL") + f" {rec['seconds']} s  " + ", ".join(sorted(servers_used(rec))),
                  flush=True)
            (run_dir / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(report(res), encoding="utf-8")
    print(f"\n{run_dir}/report.md\n")
    print(report(res).split("| Case |")[0])
    return 0


def rescored(run_dir: str) -> dict:
    """A finished run with today's pass rule (no model calls)."""
    by_id = {c["id"]: c for c in CASES}
    res = json.loads((Path(run_dir) / "results.json").read_text())
    for r in res["results"]:
        if r["id"] in by_id:
            r["ok"] = passed(by_id[r["id"]], r["rec"])
    return res


def cmd_score(a) -> int:
    res = rescored(a.run)
    (Path(a.run) / "report.md").write_text(report(res), encoding="utf-8")
    print(report(res))
    return 0


def cmd_compare(a) -> int:
    for d in a.runs:
        res = rescored(d)
        print(report(res).split("| Case |")[0].strip())
        bad = sorted({r["id"] for r in res["results"] if not r["ok"]})
        print("  failing cases: " + (", ".join(bad) or "none") + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--repeat", type=int, default=3)
    r.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    r.add_argument("--timeout", type=float, default=240, help="seconds per prompt before it is interrupted")
    r.add_argument("--out", default=str(Path.home() / ".local/state/dl-ai/benchmarks/toolchoice"))
    r.add_argument("--stale-ok", action="store_true", help="run although the code is newer than the daemon")
    c = sub.add_parser("compare")
    c.add_argument("runs", nargs="+")
    s = sub.add_parser("score")
    s.add_argument("run")
    a = ap.parse_args()
    return {"run": cmd_run, "compare": cmd_compare, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
