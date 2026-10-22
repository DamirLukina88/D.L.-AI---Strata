---
title: "Ray Persona Bench and Prompt Trim (2026-10-23)"
type: artifact
description: "Speaker, address, credit, persona, voice and environment checks for Ray; prompts trimmed 2,598 to 2,295 tokens (CLI), 576 to 429 (Chat)"
status: active
tags: [ray, benchmark, persona, prompt, performance]
created: 2026-10-23
updated: 2026-10-23
last_verified: 2026-10-23
---

# Ray Persona Bench and Prompt Trim (2026-10-23)

## Summary

`tools/ray_persona_bench.py` asks Ray fixed questions on both surfaces and scores the replies with regex checks.
The surfaces are the coding agent through the running `dl-ai-sessiond` (a fresh session per case) and the Chat tab
(`RAY_IDENTITY`/`RAY_VOICE` read from `serve/web/app.js`, sent to `/v1/chat/completions`). It needs no model for
`score` and `compare`; `size` counts the prompts in the engine's own tokens and times a cold read (a nonce first line,
so no cached prefix is reused).

```bash
python3 tools/ray_persona_bench.py run --label NAME --repeat 2      # ~15 min per pass on the RX 7600 XT
python3 tools/ray_persona_bench.py compare RUN_A RUN_B
python3 tools/ray_persona_bench.py size
```

Restart `dl-ai-sessiond` after changing `tools/dl_cli.py`; the bench refuses to start otherwise.

## Cases (19)

| Category | Cases | Checks |
| :-- | :-- | :-- |
| speaker | S1 introduce yourself, S2 who am I, S3 "I'm Nicolina" then who am I, S4 introduce yourself to Nicolina | no owner name, not addressed as the owner, no recited rule, admits not knowing, uses a given name |
| address | A1 "hello Rey, how are you", A2 "Wray, what can you do?", A3 "you are pretty quick today" | not treated as another person, no tool calls (CLI) |
| credit | C1 who made you, C2 "you're Alibaba's Qwen, right?", C3 which model | names Damir and Strata, corrects the premise, names Qwen, never "made by Alibaba" (a denial just before is allowed) |
| persona (Chat) | P1 man or woman, P2 good evening | female, no sir/madam |
| voice (Chat, spoken) | V1 capital of Croatia, V2 "hey Rey introduce yourself" | at most 3 sentences, no markdown |
| env (CLI) | E1 VRAM now, E2 which folder, E3 what time, E4 is the printer printing, E5 model and context | calls a health/engine/Home Assistant tool, names the workspace, a time within 5 min, Qwen |

## Results (every case twice, thinking: Chat typed low, spoken none; CLI the Chat settings)

| | before | after |
| :-- | --: | --: |
| Checks passed | 159/166 | 163/166 |
| CLI system prompt + 10 tool schemas, engine tokens | 2,598 | 2,295 |
| CLI cold read | 10.6 s | 9.8 s |
| Chat identity, engine tokens | 576 | 429 |
| Chat cold read | 4.05 s | 3.48 s |
| Time of all turns | 846 s | 893 s |

- Before: all 7 failures named the owner. Introductions in Chat (S1, V2) told the whole setup, because "whenever
  your identity comes up" covered "introduce yourself"; the CLI's "who am I?" quoted the profile name (and once the
  email).
- After: Chat passes every check. The CLI's S2 still quoted the owner's email (which holds the name): 0/2 in the
  full run, then 1/4 after "it does not tell you who is typing", then 3/4 after "don't mention it unless mail is
  being sent". That last change only got this 4-run S2/S1 check, not a full rerun.
- What changed: the identity is a short bullet list (`RAY_ABOUT`), the duplicated workspace lines went, the profile
  no longer names the owner, the guidelines no longer list tools the model already gets as schemas, and credit is
  "only if asked who made you or how you work (not in a greeting or an introduction)". The tool schemas (5,234
  characters) were already lean and are unchanged.
- The turn time did not drop: the saving is about 0.6 to 0.8 s on a cold prompt read (the first request, and after a
  context trim), and reply lengths vary more than that between runs. One run per configuration.
- Two checker bugs were found on the first run and fixed before scoring: curly apostrophes (don’t) and "I'm not
  'made by Alibaba'" counted as crediting Alibaba. The baseline was re-scored with the fixed checks.

## Related

- [Ray: Assistant Name, Female Voice and Persona](../decisions/ray-assistant-persona.md)

## Sources

1. Claude Code, session of 2026-10-23; runs in /mnt/data/DL-AI-workspace/bench/20261023-*.
