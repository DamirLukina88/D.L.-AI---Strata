---
title: "Engine Port Check Scripts (2026-10-21)"
type: artifact
description: "The greedy answer check, A/B bench wrapper and streamed-timings check used to verify the 0.2.2 engine port on the RX 7600 XT, plus the serve tests that already failed before it"
status: active
tags: [benchmark, identity-check, engine, testing, gfx1102, scripts]
created: 2026-10-21
updated: 2026-10-21
last_verified: 2026-10-21
---

# Engine Port Check Scripts (2026-10-21)

## Summary

Three small scripts checked the four ported upstream 0.2.2 fixes before and after the engine swap (see [Upstream Strata 0.2.2 Review](upstream-v0-2-2-review-2026-10-21.md)). Reuse them for the next engine port. All three read `STRATA_API_KEY` from `~/.config/dl-ai/secrets.env` and never print it; the model configs carry no `api_key`.

How they were used:

1. `identity.py old_a.json` and `old_b.json` on the running engine, then swap the engine, then `new_a.json` and `new_b.json`.
2. Compare answers per prompt. On this install the old engine itself differs on a repeat for 3 of 7 prompts (near-tie wording), so judge by correct answers and similar near-tie splits, not bitwise identity.
3. `bench.sh new1`, swap back, `bench.sh old1`, same day.
4. `stream_check.py`: the last streamed chunk must carry `timings.predicted_per_second`, and it must equal the console's `[strata] done:` rate.

Engine swap gotcha: `cp` onto a running `engine/strata` fails with "Text file busy". Copy to `engine/strata.new` and `mv -f` it over, then `systemctl --user restart strata-server`. With `lazy_load`, the first request loads the model (about 40 s).

## Serve tests that already failed before the port

On unchanged `d53a4361`, `python -m unittest discover -s serve -t . -p "test_*.py"` (pytest is not installed) gives these failures. Compare a new run against this list, not against zero:

- `serve.test_keepawake.KeepAwakeTests.test_service_holds_for_the_whole_request_including_early_close`
- `serve.test_server.WebApp.test_page_and_files`
- `serve.test_structured.Structured.test_invalid_generation_is_an_error_and_never_streams_content` (4 subtests)

## identity.py

```python
"""Greedy identity check against the running Strata server: same prompts, temperature 0, thinking off and on.
Writes the answers to OUT (json) so two engine builds can be compared.  The API key is read from the config, never printed.

    python identity.py OUT.json
"""
import json, sys, time, urllib.request

CFG = "/mnt/data/Strata/strata-coder-iq1_m.json"
BASE = "http://127.0.0.1:8080"
import os
KEY = ""
for line in open(os.path.expanduser("~/.config/dl-ai/secrets.env")):
    line = line.strip()
    if line.startswith(("STRATA_API_KEY=", "export STRATA_API_KEY=")):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'")

FILLER = " ".join(f"Line {i}: the quick brown fox number {i} jumps over lazy dog {i * 7 % 13}." for i in range(420))
PROMPTS = [
    ("capital", "What is the capital of Australia? Answer in one sentence.", False, 64),
    ("math", "Compute 17 * 23 and then add 391. Show the steps briefly.", False, 96),
    ("code", "Write a Python function that returns the n-th Fibonacci number iteratively.", False, 160),
    ("story", "Write the first three sentences of a short story about a lighthouse keeper.", False, 128),
    ("long4k", FILLER + "\n\nWhich line mentions fox number 211, and what dog number does it have? Answer briefly.", False, 64),
    ("think", "Is 391 a prime number? Answer yes or no with a one-line reason.", True, 384),
    ("tool", "List the files in the current folder.", False, 128),
]
TOOLS = [{"type": "function", "function": {"name": "shell", "description": "Run a shell command",
          "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}]


def chat(prompt, think, max_tokens, tools=None):
    body = {"model": "m", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0, "top_k": 1, "top_p": 1, "stream": False}
    if not think:
        body["reasoning_effort"] = "none"
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + KEY} if KEY else {})})
    t = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        out = json.load(r)
    m = out["choices"][0]["message"]
    return {"content": m.get("content"), "reasoning": m.get("reasoning_content"), "tool_calls": m.get("tool_calls"),
            "finish": out["choices"][0]["finish_reason"], "usage": out.get("usage"), "timings": out.get("timings"),
            "wall_s": round(time.time() - t, 2)}


res = {}
for name, prompt, think, mt in PROMPTS:
    res[name] = chat(prompt, think, mt, TOOLS if name == "tool" else None)
    r = res[name]
    tc = (r["timings"] or {}).get("predicted_per_second")
    print(f"{name:8s} finish={r['finish']:10s} tokens={(r['usage'] or {}).get('completion_tokens')} decode={tc} tok/s "
          f"wall={r['wall_s']} s", flush=True)
json.dump(res, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
```

## bench.sh

```bash
#!/bin/bash
# bench.sh NAME : run tools/strata_bench.py against the live server, key from secrets.env (never printed)
set -a; . ~/.config/dl-ai/secrets.env; set +a
cd /mnt/data/Strata
STRATA_KEY="$STRATA_API_KEY" timeout 3000 python tools/strata_bench.py --url http://127.0.0.1:8080 --runs 3 --quiet --out bench/results/v0.2.2-fixes-2026-10-21/$1 2>&1 | tail -30
```

## stream_check.py

```python
import json, os, urllib.request
KEY = ""
for line in open(os.path.expanduser("~/.config/dl-ai/secrets.env")):
    if line.strip().startswith("STRATA_API_KEY="):
        KEY = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
body = {"model": "m", "messages": [{"role": "user", "content": "Is 91 prime? One line."}], "max_tokens": 300, "stream": True}
req = urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
last = None
with urllib.request.urlopen(req, timeout=600) as r:
    for line in r:
        line = line.decode().strip()
        if line.startswith("data:") and line[5:].strip() != "[DONE]":
            j = json.loads(line[5:])
            if j.get("usage"): last = j
print("usage:", last.get("usage")); print("timings:", last.get("timings"))
```

## Sources

1. Claude Code session, 2026-10-21: scripts written in the session scratchpad and run against the live server; failing-test list from the unchanged worktree run.
2. Results: `bench/results/v0.2.2-fixes-2026-10-21/{new1,old1}` (git-ignored).
