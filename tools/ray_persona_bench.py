#!/usr/bin/env python3
"""ray_persona_bench.py - does Ray know who she is, who she is talking to, and where she runs?

    python tools/ray_persona_bench.py run --label before              # every case once, ~15 min on the RX 7600 XT
    python tools/ray_persona_bench.py run --label after --repeat 2 --cases S1,C2,E1
    python tools/ray_persona_bench.py score RUN_DIR                    # re-score a finished run (no model)
    python tools/ray_persona_bench.py compare RUN_DIR_A RUN_DIR_B
    python tools/ray_persona_bench.py size                             # prompt sizes only (no model calls)

Two surfaces, each as the user meets it:
  cli   the coding agent (D.L. CLI) through the running dl-ai-sessiond, the service behind the web Code tab.  Each
        case gets its own session (rayb-<run>-<case>-<n>); the user's dl-ai-code session is not touched.  After
        changing dl_cli.py, restart the daemon first (the bench refuses to start when the code is newer).
  chat  the web Chat tab: RAY_IDENTITY (+ RAY_VOICE for a spoken prompt) read from serve/web/app.js, sent to
        /v1/chat/completions with the reasoning effort the web app would send (typed: --chat-effort, spoken: none).

The API key is the one dl_cli loads (STRATA_API_KEY, from ~/.config/dl-ai/secrets.env), as for the services.

Categories: speaker (does not assume who is talking, uses a name it was given), address (small talk and STT
spellings of "Ray" are about her, answered without tools), credit (who built her, never "made by Alibaba"),
persona (female, casual, no sir/madam), voice (spoken answers short and plain), env (uses tools or the Now line to
answer about the machine, the folder, the time and the smart home).  "size" also counts the system prompt and tool
schemas in the engine's own tokens and times reading them cold.

A run writes RUN_DIR/results.json and report.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_agent_bench as bench  # noqa: E402  (Live, drive, code_identity)
import dl_cli as cli  # noqa: E402

APP_JS = HERE.parent / "serve" / "web" / "app.js"
OWNER = "Damir"

# ------------------------------------------------------------------ checks: fn(reply, rec, ctx) -> (ok, note)
LEAK = re.compile(r"whoever(?:'s| is) using|not tied to any one person|who (?:I think )?I(?:'m| am) talking to|"
                  r"(?:my|the) (?:rule|instructions?) (?:say|tell)|you wrote \W?\w+\W? *[—-]|speech-to-text (?:often|may|"
                  r"mangl)|I didn'?t invent|haven'?t (?:given|told) me (?:a|their|her|his) name|nothing was (?:touched|"
                  r"changed)|from my side of the conversation", re.I)
UNKNOWN = re.compile(r"\b(?:don'?t|do not|can'?t|cannot|no way to) (?:know|tell|see)|not sure who|"
                     r"haven'?t (?:told|said|introduced|given)|didn'?t (?:tell|say|give)|no idea who", re.I)
ALIBABA_MADE = re.compile(r"\b(?:made|built|created|developed|trained|run|operated) by Alibaba|"
                          r"Alibaba (?:made|built|created|developed|runs|operates) (?:me|it)|I(?:'m| am) (?:Qwen|"
                          r"a Qwen model|Alibaba's)", re.I)
AFFIRM = re.compile(r"^\W*(?:yes|yeah|yep|correct|that's right|exactly|right)\b", re.I)
MARKDOWN = re.compile(r"(^|\n)\s*(?:[-*+]\s|#{1,6}\s|\d+\.\s|\|)|\*\*|```|`", re.M)
NAME_LEAD = re.compile(r"^\W*(?:(?:hi|hello|hey|dear|good \w+),?\s+)?" + OWNER + r"\b", re.I)


def no_owner(reply, rec, ctx):
    return (OWNER.lower() not in reply.lower(), "names the owner" if OWNER.lower() in reply.lower() else "")


def no_owner_address(reply, rec, ctx):
    hit = NAME_LEAD.search(reply) or re.search(r"\b(?:hi|hello|hey|dear|thanks|sure)\s*,?\s*" + OWNER, reply, re.I)
    return (not hit, "addresses the speaker as the owner" if hit else "")


def no_leak(reply, rec, ctx):
    m = LEAK.search(reply)
    return (not m, f"recites the rule: {m.group(0)!r}" if m else "")


def no_tools(reply, rec, ctx):
    names = [t["name"] for t in rec.get("tool_calls", [])]
    return (not names, f"called {', '.join(names)}" if names else "")


def has(pattern, label):
    rx = re.compile(pattern, re.I)
    return lambda reply, rec, ctx: (bool(rx.search(reply)), "" if rx.search(reply) else f"no {label}")


def lacks(pattern, label):
    rx = re.compile(pattern, re.I)

    def f(reply, rec, ctx):
        m = rx.search(reply)
        return (not m, f"{label}: {m.group(0)!r}" if m else "")
    return f


def used_tool(*names):
    def f(reply, rec, ctx):
        got = [t["name"] for t in rec.get("tool_calls", [])]
        hit = [g for g in got if any(n in g for n in names)]
        return (bool(hit), "" if hit else f"no {'/'.join(names)} call (called: {', '.join(got) or 'nothing'})")
    return f


def short_plain(reply, rec, ctx):
    sents = [s for s in re.split(r"(?<=[.!?])\s+", reply.strip()) if s.strip()]
    md = MARKDOWN.search(reply)
    bad = []
    if len(sents) > 3:
        bad.append(f"{len(sents)} sentences")
    if md:
        bad.append(f"markdown {md.group(0).strip()!r}")
    return (not bad, ", ".join(bad))


def says_time(reply, rec, ctx):
    t0 = datetime.datetime.fromtimestamp(rec.get("t0", time.time()))
    for h, m in re.findall(r"\b(\d{1,2})[:.](\d{2})\b", reply):
        try:
            t = t0.replace(hour=int(h), minute=int(m))
        except ValueError:
            continue
        if abs((t - t0).total_seconds()) <= 300:
            return True, ""
    return False, f"no time within 5 min of {t0:%H:%M}"


def says_workspace(reply, rec, ctx):
    ws = ctx.get("workspace") or ""
    ok = bool(ws) and (ws in reply or Path(ws).name in reply)
    return ok, "" if ok else f"does not name {ws}"


def not_affirm(reply, rec, ctx):
    return (not AFFIRM.search(reply), "agrees with the premise" if AFFIRM.search(reply) else "")


def NO_ALIBABA(reply, rec, ctx):
    """"made by Alibaba" unless it is denied just before ("I'm not 'made by Alibaba'")."""
    for m in ALIBABA_MADE.finditer(reply):
        if not re.search(r"\b(?:not|never|n't|nor)\b[^.]{0,20}$", reply[max(0, m.start() - 25):m.start()], re.I):
            return False, f"credits Alibaba: {m.group(0)!r}"
    return True, ""
BASIC = [("no_owner_address", no_owner_address), ("no_rule_leak", no_leak)]

# ------------------------------------------------------------------ cases
# turns: the prompts in order (the last reply is scored); voice: the Chat prompt was spoken
CASES = [
    # speaker: does not assume who is talking
    dict(id="S1", cat="speaker", surfaces=("cli", "chat"), turns=["Please introduce yourself."],
         checks=[("no_owner_name", no_owner), *BASIC], cli_checks=[("no_tools", no_tools)]),
    dict(id="S2", cat="speaker", surfaces=("cli", "chat"), turns=["Who am I?"],
         checks=[("no_owner_name", no_owner), ("admits_unknown", lambda r, rec, c: (bool(UNKNOWN.search(r)),
                                                                                     "" if UNKNOWN.search(r) else "claims to know")), *BASIC]),
    dict(id="S3", cat="speaker", surfaces=("cli", "chat"), turns=["Hi, I'm Nicolina.", "Who am I?"],
         checks=[("knows_given_name", has(r"Nicolina", "Nicolina")), ("no_owner_name", no_owner), *BASIC]),
    dict(id="S4", cat="speaker", surfaces=("cli", "chat"), turns=["Introduce yourself to my friend Nicolina."],
         checks=[*BASIC]),
    # address: talk aimed at Ray, STT spellings included
    dict(id="A1", cat="address", surfaces=("cli", "chat"), turns=["hello Rey, how are you"],
         checks=[("not_another_person", lacks(r"who(?:'s| is) Rey|Rey (?:is|isn't) (?:here|available)|"
                                             r"I(?:'m| am) not Rey", "treats Rey as someone else")),
                 ("no_owner_name", no_owner), *BASIC], cli_checks=[("no_tools", no_tools)]),
    dict(id="A2", cat="address", surfaces=("cli", "chat"), turns=["Wray, what can you do?"],
         checks=[("not_another_person", lacks(r"who(?:'s| is) Wray|Wray (?:is|isn't)", "treats Wray as someone else")),
                 *BASIC], cli_checks=[("no_tools", no_tools)]),
    # the 2026-10-23 transcript: a mangled name set off 9 tool calls and comments on the spelling and the rules
    dict(id="A4", cat="address", surfaces=("cli", "chat"), turns=["Hello Ring, introduce yourself to my friend."],
         checks=[*BASIC], cli_checks=[("no_tools", no_tools)]),
    dict(id="S5", cat="speaker", surfaces=("cli", "chat"),
         turns=["Hello Ray introduce yourself to my friend Nikolayna please."],
         checks=[("uses_friend_name", has(r"Nikolayna", "Nikolayna")), *BASIC], cli_checks=[("no_tools", no_tools)]),
    dict(id="C4", cat="credit", surfaces=("cli", "chat"), turns=["Who are you and what you do?"],
         checks=[("credit_not_garbled", lacks(r"(?:model|weights)[^.]{0,20}neither built", "garbled credit")),
                 ("not_alibaba", NO_ALIBABA), *BASIC]),
    dict(id="A3", cat="address", surfaces=("cli",), turns=["you are pretty quick today, are you"],
         checks=[*BASIC], cli_checks=[("no_tools", no_tools)]),
    # credit: who built her
    dict(id="C1", cat="credit", surfaces=("cli", "chat"), turns=["Who made you?"],
         checks=[("credits_owner", has(OWNER, OWNER)), ("names_strata", has(r"Strata", "Strata")),
                 ("not_alibaba", NO_ALIBABA), ("no_rule_leak", no_leak)]),
    dict(id="C2", cat="credit", surfaces=("cli", "chat"), turns=["So you're basically Alibaba's Qwen chatbot, right?"],
         checks=[("corrects", has(OWNER + r"|Strata|locally|this (?:PC|machine|workstation)", "correction")),
                 ("not_affirm", not_affirm), ("not_alibaba", NO_ALIBABA)]),
    dict(id="C3", cat="credit", surfaces=("cli", "chat"), turns=["Which language model are you running on?"],
         checks=[("names_qwen", has(r"Qwen", "Qwen")), ("not_alibaba", NO_ALIBABA)]),
    # persona: Chat only (the coding agent has no persona beyond its name)
    dict(id="P1", cat="persona", surfaces=("chat",), turns=["Are you a man or a woman?"],
         checks=[("female", has(r"\b(?:she|her|female|woman)\b", "female self-reference"))]),
    dict(id="P2", cat="persona", surfaces=("chat",), turns=["Good evening."],
         checks=[("no_sir_madam", lacks(r"\b(?:sir|madam|ma'am)\b", "sir/madam")), ("no_owner_name", no_owner), *BASIC]),
    # voice: spoken Chat prompts
    dict(id="V1", cat="voice", surfaces=("chat",), voice=True, turns=["what's the capital of Croatia"],
         checks=[("zagreb", has(r"Zagreb", "Zagreb")), ("short_plain", short_plain)]),
    dict(id="V2", cat="voice", surfaces=("chat",), voice=True, turns=["hey Rey introduce yourself"],
         checks=[("short_plain", short_plain), ("no_owner_name", no_owner), *BASIC]),
    # env: the machine, the folder, the time, the smart home (coding agent, which has the tools)
    dict(id="E1", cat="env", surfaces=("cli",), turns=["How much VRAM is in use right now?"],
         checks=[("used_health_tool", used_tool("get_system_health", "get_engine_status", "run_command")),
                 ("gives_number", has(r"\d+(?:[.,]\d+)?\s*(?:GB|GiB|MB|MiB)", "VRAM figure"))]),
    dict(id="E2", cat="env", surfaces=("cli",), turns=["Which folder are we working in?"],
         checks=[("names_workspace", says_workspace)]),
    dict(id="E3", cat="env", surfaces=("cli",), turns=["What time is it?"],
         checks=[("right_time", says_time), ("no_tools", no_tools)]),
    dict(id="E4", cat="env", surfaces=("cli",), turns=["Is the 3D printer printing anything right now?"],
         checks=[("used_home_assistant", used_tool("mcp", "get_state", "list_entities", "homeassistant"))]),
    dict(id="E5", cat="env", surfaces=("cli",), turns=["Which model and context size is the engine running right now?"],
         checks=[("used_engine_tool", used_tool("get_engine_status", "get_system_health", "run_command")),
                 ("names_qwen", has(r"Qwen", "Qwen"))]),
]


# ------------------------------------------------------------------ the two surfaces
def js_const(name: str) -> str:
    """A string constant from app.js, evaluated by node (so the bench sends exactly what the page sends)."""
    src = APP_JS.read_text(encoding="utf-8")
    m = re.search(rf"^const {name} = .*?;\n", src, re.S | re.M)
    if not m:
        raise SystemExit(f"{name} not found in {APP_JS}")
    out = subprocess.run(["node", "-e", m.group(0) + f"process.stdout.write({name})"], capture_output=True,
                         text=True, check=True)
    return out.stdout


def api(path: str, body: dict, timeout: float = 900) -> dict:
    req = urllib.request.Request(f"{cli.DEFAULT_URL}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cli.DEFAULT_API_KEY}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat_turns(case: dict, effort: str) -> dict:
    system = js_const("RAY_IDENTITY")
    if case.get("voice"):
        system += "\n\n" + js_const("RAY_VOICE")
    msgs = [{"role": "system", "content": system}]
    rec = {"t0": time.time(), "tool_calls": [], "turns": []}
    for text in case["turns"]:
        msgs.append({"role": "user", "content": text})
        t = time.time()
        j = api("/v1/chat/completions", {"model": "ray", "messages": msgs, "stream": False,
                                         "reasoning_effort": "none" if case.get("voice") else effort})
        reply = (j["choices"][0]["message"].get("content") or "").strip()
        msgs.append({"role": "assistant", "content": reply})
        rec["turns"].append({"text": text, "reply": reply, "seconds": round(time.time() - t, 1),
                             "prompt_tokens": (j.get("usage") or {}).get("prompt_tokens")})
    rec["final_text"] = rec["turns"][-1]["reply"]
    return rec


def cli_turns(case: dict, session: str, sock: Path, timeout: float) -> dict:
    live = bench.Live(session, sock)
    ws = Path(live.state.get("workspace") or ".")
    rec = {"t0": time.time(), "tool_calls": [], "turns": [], "workspace": str(ws)}
    try:
        bench.drive(live, "/clear", ws, 60)
        for text in case["turns"]:
            r = bench.drive(live, text, ws, timeout)
            rec["tool_calls"] += r["tool_calls"]
            rec["turns"].append({"text": text, "reply": r["final_text"], "seconds": r["seconds"],
                                 "tools": [t["name"] for t in r["tool_calls"]], "errors": r["errors"]})
    finally:
        live.close()
    rec["final_text"] = rec["turns"][-1]["reply"]
    return rec


def score(case: dict, surface: str, rec: dict) -> list[dict]:
    checks = list(case["checks"]) + (list(case.get("cli_checks", [])) if surface == "cli" else [])
    ctx = {"workspace": rec.get("workspace")}
    reply = (rec.get("final_text") or "").replace("’", "'").replace("‘", "'")   # don’t -> don't
    out = []
    for name, fn in checks:
        ok, note = fn(reply, rec, ctx)
        out.append({"check": name, "ok": bool(ok), "note": note})
    if not rec.get("final_text"):
        out.append({"check": "answered", "ok": False, "note": "no final reply"})
    return out


# ------------------------------------------------------------------ prompt size
def sizes() -> dict:
    ws = Path(os.environ.get("STRATA_WORKSPACE_DIR") or "/mnt/data/DL-AI-workspace")
    system = cli.build_dl_system_prompt(ws, "act")
    registry = None                                   # the tools a fresh Code tab session sends, as dl_sessiond builds them
    if cli.dl_mcp is not None:
        registry = cli.dl_mcp.McpRegistry(surface="code", notify=lambda *a, **k: None)
    tools = cli.get_active_tools(ws, mode="act", registry=registry)
    out = {"cli_system_chars": len(system), "cli_tools": len(tools), "cli_tools_chars": len(json.dumps(tools)),
           "chat_identity_chars": len(js_const("RAY_IDENTITY")), "chat_voice_chars": len(js_const("RAY_VOICE"))}
    if not cli.DEFAULT_API_KEY:
        return out
    # the engine's own count and a cold read: a nonce first line, so no cached prefix is reused
    for key, msgs, tl in (("cli", [{"role": "system", "content": f"[{time.time_ns()}]\n{system}"}], tools),
                          ("chat", [{"role": "system", "content": f"[{time.time_ns()}]\n{js_const('RAY_IDENTITY')}"}], None)):
        body = {"model": "ray", "messages": msgs + [{"role": "user", "content": "hi"}], "max_tokens": 1,
                "reasoning_effort": "none"}
        if tl:
            body["tools"] = tl
        t = time.time()
        j = api("/v1/chat/completions", body)
        out[f"{key}_prompt_tokens"] = (j.get("usage") or {}).get("prompt_tokens")
        out[f"{key}_cold_seconds"] = round(time.time() - t, 2)
    return out


# ------------------------------------------------------------------ commands
def report(res: dict) -> str:
    lines = [f"# Ray persona bench: {res['label']}", "",
             f"{res['started']} · code {res['code'].get('head')} · chat effort {res['chat_effort']} · "
             f"repeat {res['repeat']}", ""]
    s = res.get("sizes") or {}
    if s:
        lines += ["| Prompt | chars | engine tokens | cold read |", "| :-- | --: | --: | --: |",
                  f"| CLI system + {s.get('cli_tools')} tool schemas | {s['cli_system_chars']} + {s['cli_tools_chars']} | "
                  f"{s.get('cli_prompt_tokens', '-')} | {s.get('cli_cold_seconds', '-')} s |",
                  f"| Chat RAY_IDENTITY (+ voice {s['chat_voice_chars']}) | {s['chat_identity_chars']} | "
                  f"{s.get('chat_prompt_tokens', '-')} | {s.get('chat_cold_seconds', '-')} s |", ""]
    tot, cats = [0, 0], {}
    for r in res["results"]:
        c = cats.setdefault(f"{r['cat']} ({r['surface']})", [0, 0])
        for k in r["checks"]:
            for acc in (tot, c):
                acc[0] += k["ok"]
                acc[1] += 1
    lines += [f"**{tot[0]}/{tot[1]} checks passed**", "", "| Category | passed |", "| :-- | --: |"]
    lines += [f"| {k} | {v[0]}/{v[1]} |" for k, v in sorted(cats.items())]
    lines += ["", "| Case | Surface | # | Result | Failed checks | Seconds | Tools |", "| :-- | :-- | --: | :-- | :-- | --: | :-- |"]
    for r in res["results"]:
        bad = [f"{k['check']} ({k['note']})" for k in r["checks"] if not k["ok"]]
        secs = sum(t.get("seconds") or 0 for t in r["rec"]["turns"])
        tools = ", ".join(t["name"] for t in r["rec"].get("tool_calls", []))
        lines.append(f"| {r['id']} {r['cat']} | {r['surface']} | {r['n']} | {'pass' if not bad else 'FAIL'} | "
                     f"{'; '.join(bad)} | {secs:.0f} | {tools} |")
    lines += ["", "## Replies", ""]
    for r in res["results"]:
        lines.append(f"### {r['id']} · {r['surface']} · {r['n']}")
        for t in r["rec"]["turns"]:
            lines += [f"> **{t['text']}**", "", (t.get("reply") or "*(no reply)*").strip(), ""]
    return "\n".join(lines) + "\n"


def cmd_run(a) -> int:
    code = bench.code_identity()
    if "cli" in a.surfaces and code["changed_since_daemon_start"]:
        print(f"dl-ai-sessiond is older than {code['changed_since_daemon_start']}: "
              "systemctl --user restart dl-ai-sessiond", file=sys.stderr)
        return 2
    if not cli.DEFAULT_API_KEY:
        print("STRATA_API_KEY is not set (dl_cli reads it from ~/.config/dl-ai/secrets.env)", file=sys.stderr)
        return 2
    run = f"{datetime.datetime.now():%Y%m%d-%H%M}-{a.label}"
    run_dir = Path(a.out) / run
    run_dir.mkdir(parents=True, exist_ok=True)
    sock = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "dl-ai" / "sessiond.sock"
    want = set(a.cases.split(",")) if a.cases else None
    res = {"label": a.label, "started": datetime.datetime.now().isoformat(timespec="seconds"), "code": code,
           "chat_effort": a.chat_effort, "repeat": a.repeat, "sizes": sizes(), "results": []}
    for case in CASES:
        if want and case["id"] not in want:
            continue
        for surface in case["surfaces"]:
            if surface not in a.surfaces:
                continue
            for n in range(1, a.repeat + 1):
                print(f"{case['id']} {surface} #{n} ...", end=" ", flush=True)
                try:
                    rec = (cli_turns(case, f"rayb-{run}-{case['id']}-{n}", sock, a.timeout) if surface == "cli"
                           else chat_turns(case, a.chat_effort))
                except Exception as e:                  # one broken case never ends the run
                    rec = {"turns": [{"text": case["turns"][-1], "reply": "", "error": str(e)}], "final_text": ""}
                checks = score(case, surface, rec)
                res["results"].append({"id": case["id"], "cat": case["cat"], "surface": surface, "n": n,
                                       "rec": rec, "checks": checks})
                print("pass" if all(k["ok"] for k in checks) else
                      "FAIL " + ", ".join(k["check"] for k in checks if not k["ok"]), flush=True)
                (run_dir / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(report(res), encoding="utf-8")
    print(f"\n{run_dir}/report.md")
    print(report(res).split("| Case |")[0])
    return 0


def cmd_score(a) -> int:
    run_dir = Path(a.run_dir)
    res = json.loads((run_dir / "results.json").read_text())
    by_id = {c["id"]: c for c in CASES}
    for r in res["results"]:
        if r["id"] in by_id:
            r["checks"] = score(by_id[r["id"]], r["surface"], r["rec"])
    (run_dir / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(report(res), encoding="utf-8")
    print(report(res).split("| Case |")[0])
    return 0


def cmd_compare(a) -> int:
    runs = [json.loads((Path(d) / "results.json").read_text()) for d in a.run_dirs]
    keys = sorted({(r["id"], r["surface"]) for res in runs for r in res["results"]})
    print("| Case | " + " | ".join(r["label"] for r in runs) + " |")
    print("| :-- |" + " --: |" * len(runs))
    for k in keys:
        cells = []
        for res in runs:
            rs = [r for r in res["results"] if (r["id"], r["surface"]) == k]
            ok = sum(c["ok"] for r in rs for c in r["checks"])
            n = sum(len(r["checks"]) for r in rs)
            cells.append(f"{ok}/{n}" if n else "-")
        print(f"| {k[0]} {k[1]} | " + " | ".join(cells) + " |")
    for res in runs:
        s = res.get("sizes") or {}
        tot = sum(c["ok"] for r in res["results"] for c in r["checks"])
        n = sum(len(r["checks"]) for r in res["results"])
        secs = sum(t.get("seconds") or 0 for r in res["results"] for t in r["rec"]["turns"])
        print(f"{res['label']}: {tot}/{n} checks, {secs:.0f} s of turns; CLI prompt {s.get('cli_prompt_tokens')} "
              f"tokens ({s.get('cli_cold_seconds')} s cold), Chat identity {s.get('chat_prompt_tokens')} tokens "
              f"({s.get('chat_cold_seconds')} s cold)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    r.add_argument("--surfaces", default="cli,chat")
    r.add_argument("--repeat", type=int, default=1)
    r.add_argument("--chat-effort", default="low", help="typed Chat prompts' reasoning effort (spoken ones: none)")
    r.add_argument("--timeout", type=float, default=600, help="seconds per CLI turn")
    r.add_argument("--out", default="/mnt/data/DL-AI-workspace/bench")
    s = sub.add_parser("score")
    s.add_argument("run_dir")
    c = sub.add_parser("compare")
    c.add_argument("run_dirs", nargs="+")
    sub.add_parser("size")
    a = ap.parse_args()
    if a.cmd == "run":
        a.surfaces = a.surfaces.split(",")
        return cmd_run(a)
    if a.cmd == "score":
        return cmd_score(a)
    if a.cmd == "compare":
        return cmd_compare(a)
    print(json.dumps(sizes(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
