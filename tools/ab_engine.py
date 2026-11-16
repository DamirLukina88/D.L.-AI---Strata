"""A/B two engine builds or environments on one config: restart the server per arm, alternate arms over rounds.

    python tools/ab_engine.py strata-q2_0.json A:exe=/path/a B:exe=/path/b,STRATA_EXP_MODE=0 [--rounds 3]

An arm is NAME:key=value,...; `exe` replaces the config's engine, `xargs` appends ';'-separated engine arguments,
`lib_dirs` replaces the config's library folders (';'-separated), `dropargs` removes ';'-separated engine flags
(and their values) from the config's arguments, `drop` removes ';'-separated engine switches from
the config's "env", every other key is set in the engine's environment (over the config's "env").
--prompt-tokens 256,2048,... adds one long prompt per size (about that many tokens); --starts N only starts each arm
N times with one short answer (stability count); --out keeps each start's engine log in that folder.  Each round starts the server once per arm (the arms' order alternates), warms it up with one short
answer, then sends the same requests: greedy, fixed prompts, a short chat set and one long prompt.  Prints the
server's own timings (llama.cpp's `timings`: decode and prompt tokens per second) per request and the per-arm
medians.  Decode numbers move run to run (the adaptive expert tier, the OS), so compare medians over rounds.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = (
    "Write a Python function that merges two sorted lists into one sorted list, with a docstring and two tests.",
    "Explain in two paragraphs how a refrigerator moves heat from inside to outside.",
    "List ten practical tips for learning a new language as an adult, one sentence each.",
)


def long_prompt(words: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    vocab = ("river stone market lantern copper winter garden signal harbor needle orbit velvet canyon ember "
             "ledger quartz meadow anchor violet thunder").split()
    body = " ".join(rng.choice(vocab) for _ in range(words))
    return f"Here is a list of words:\n{body}\n\nSummarize what kinds of words appear in the list, in five sentences."


def post(port: int, prompt: str, max_tokens: int) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
                         "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())


def wait_ready(port: int, proc: subprocess.Popen, timeout: float = 1800) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with {proc.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=5) as r:
                if r.status == 200:
                    post(port, "Say hi.", 8)
                    return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError("server not ready")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--long-words", type=int, default=6000)
    ap.add_argument("--log", default="ab_engine.jsonl")
    ap.add_argument("--prompt-tokens", default="", help="comma-separated prompt sizes in tokens, one long prompt each")
    ap.add_argument("--no-chat", action="store_true", help="leave out the short chat prompts")
    ap.add_argument("--starts", type=int, default=0, help="only start each arm N times with one short answer")
    ap.add_argument("--out", default="", help="folder for the engine logs (default: the temp folder)")
    a = ap.parse_args()
    base = json.loads(Path(a.config).read_text())
    arms = []
    for s in a.arms:
        name, _, kv = s.partition(":")
        env = dict(x.split("=", 1) for x in kv.split(",") if x)
        arms.append((name, env))
    reqs = [] if a.no_chat else [(f"chat{i}", p) for i, p in enumerate(PROMPTS)]
    if a.prompt_tokens:                                   # a vocabulary word is about 1.6 tokens with its space
        reqs += [(f"p{n}", long_prompt(max(16, int(int(n) / 1.6)), seed=int(n))) for n in a.prompt_tokens.split(",")]
    elif not a.no_chat:
        reqs.append(("long", long_prompt(a.long_words)))
    if a.starts:
        reqs = [("start", "Say hi.")]
    logdir = Path(a.out) if a.out else Path(tempfile.gettempdir())
    logdir.mkdir(parents=True, exist_ok=True)
    out = open(a.log, "a")
    res: dict = {n: {} for n, _ in arms}
    for rnd in range(a.starts or a.rounds):
        order = arms if rnd % 2 == 0 else arms[::-1]
        for name, env in order:
            cfg = dict(base)
            e = dict(env)
            if "exe" in e:
                cfg["exe"] = e.pop("exe")
            if "xargs" in e:                       # extra engine arguments, ';'-separated
                cfg["args"] = list(base["args"]) + e.pop("xargs").split(";")
            for flag in [f for f in e.pop("dropargs", "").split(";") if f]:   # an engine flag (and its value) this arm lacks
                args, kept = list(cfg["args"]), []
                while args:
                    x = args.pop(0)
                    if x == flag:
                        if args and not args[0].startswith("--"):
                            args.pop(0)
                        continue
                    kept.append(x)
                cfg["args"] = kept
            if "lib_dirs" in e:
                cfg["lib_dirs"] = e.pop("lib_dirs").split(";")
            cenv = dict(base.get("env") or {})
            for k in e.pop("drop", "").split(";"):
                cenv.pop(k, None)
            cenv.update(e)                         # the arm's switches win over the config's
            cfg["env"] = cenv
            cfg["port"] = a.port
            cfg["log"] = str(logdir / f"ab_{name}_r{rnd}.log")
            cpath = logdir / f"ab_{name}.json"
            cpath.write_text(json.dumps(cfg, indent=1))
            penv = dict(os.environ)
            penv.pop("STRATA_API_KEY", None)       # the A/B server listens on 127.0.0.1 only; requests carry no key
            proc = subprocess.Popen([sys.executable, str(ROOT / "serve" / "server.py"), "--engine", "strata", "--config",
                                     str(cpath), "--port", str(a.port)], cwd=str(ROOT), env=penv,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                t0 = time.time()
                wait_ready(a.port, proc)
                ready_s = time.time() - t0
                print(f"round {rnd} {name}: ready in {ready_s:.0f} s", flush=True)
                for tag, p in reqs:
                    t1 = time.time()
                    r = post(a.port, p, 8 if a.starts else a.max_new)
                    t = r.get("timings", {})
                    row = {"round": rnd, "arm": name, "req": tag, "decode": t.get("predicted_per_second"),
                           "prompt": t.get("prompt_per_second"), "prompt_n": t.get("prompt_n"),
                           "n": r.get("usage", {}).get("completion_tokens"), "ready_s": round(ready_s, 1),
                           "prompt_ms": t.get("prompt_ms"), "wall_s": round(time.time() - t1, 2),
                           "text": r["choices"][0]["message"].get("content", "")}
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    res[name].setdefault(tag, []).append(row)
                    print(f"  {tag:6s} decode {row['decode']} tok/s  prompt {row['prompt']} tok/s ({row['prompt_n']})  "
                          f"n {row['n']}", flush=True)
            except Exception as ex:                # a start that fails is a result too (stability), not the end of the run
                out.write(json.dumps({"round": rnd, "arm": name, "error": f"{type(ex).__name__}: {ex}"}) + "\n")
                out.flush()
                print(f"round {rnd} {name}: FAILED {type(ex).__name__}: {ex}", flush=True)
            finally:
                proc.terminate()
                try:
                    proc.wait(60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                time.sleep(5)
    print("\nmedians over rounds:")
    for tag, _ in reqs:
        cells = []
        for name, _ in arms:
            rows = res[name].get(tag, [])
            d = statistics.median([x["decode"] for x in rows if x["decode"]]) if rows else float("nan")
            pr = statistics.median([x["prompt"] for x in rows if x["prompt"]]) if rows else float("nan")
            cells.append(f"{name}: decode {d:6.1f}  prompt {pr:7.1f}")
        print(f"  {tag:6s} | " + " | ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
