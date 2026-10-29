---
title: "Ray Persona Research and A/B (2026-10-29)"
type: artifact
description: "Research on persona prompts, the red panda persona rewrite, persona bench and persona on/off quick-bench A/B on the RX 7600 XT"
status: active
tags: [ray, persona, prompt, benchmark, research]
created: 2026-10-29
updated: 2026-10-29
last_verified: 2026-10-29
---

# Ray Persona Research and A/B (2026-10-29)

## Summary

Persona prompts don't make models more accurate (papers below), and Ray's own A/B found no quality difference on the
quick bench: all three configurations passed 25/25 hidden tests. The red panda rewrite of `RAY_ABOUT` fixed "this
machine" and made naming the owner in introductions rarer (it still happens, see below), but introductions now call tools more often (7 of 10 runs against 3
of 8 before), which the small-talk guard added afterwards stops (0 ran, see below).

## What changed

- `RAY_ABOUT` (`tools/dl_cli.py`): one sentence for the place ("the home server"; the model and its thinking stay
  there, and tools for online services send what a task needs: web search, Gmail, Google Drive, Proton Mail, DeepL,
  DeepSeek, weather and other lookups; the user corrected an earlier "nothing leaves it except DeepSeek"), which removes "never this machine" next to "on this machine" and "nothing goes to the
  cloud" next to DeepSeek. A light red panda character (curious, playful, good-natured; a panda touch in small talk
  and voice, none in code), an honesty line ("friendly never means agreeing"), positive address wording instead of
  "no sir/madam", credit shortened, hardware and the device list moved to `tools/ray_identity_mcp.py`.
- Role lines: "a powerful autonomous software engineering agent" and "…architect" became plain descriptions.
- `VOICE_NOTE` also excludes lists and parentheses.
- `DL_PERSONA=minimal` (opt-in, for benches only) replaces `RAY_ABOUT` with one line; unset, the prompt is
  byte-identical to before (checked against HEAD `9b890835`, act and plan, two workspaces).
- `tools/ray_persona_bench.py`: Chat-tab leftovers gone; a place-wording check in every basic case; P1 needs a male
  self-reference; new P3 (red panda), P4 (two sentences about yourself), K1 (no persona in code), K2 (disagrees with
  a false premise); spoken cases use auto effort. `tools/test_ray_persona_bench.py` gives every check a failing reply.
- `ray_identity` catalogue (`~/.config/dl-ai/mcp.json`): small-talk triggers removed ("who are you", "about
  yourself", "tko si ti", "o sebi", "rei identity"); "who made you", "how do you work", "your hardware" added.
- Web: voice card describes the server Piper voice, test line "Hi, I'm Ray, the household's red panda, on the home
  server.", Auto voice takes ryan (male) before lessac (female) without hfc_male, cache tags `panda16`.

## Measurements (RX 7600 XT, Qwen3.8-Flash-Next Coder IQ1_M, one run per configuration unless noted)

| | Before (original persona) | After (red panda rewrite) |
| :-- | --: | --: |
| Prompt, engine tokens (system + 11 tools) | 4,928 | 4,855 (final text) |
| Cold read, model loaded | 15.9 s | 15.4 s |
| Persona bench, full run | 86/94 | 86/94 (first after-text) |
| "this machine" | 1 | 0 |
| Owner named unasked (P4, two sentences about yourself) | 1/1 | 0/2 (final text) |
| Tools called in introductions (S1, A2, A4, S5) | 3 of 8 runs* | 7 of 10 runs (final text) |
| Credit C1–C4, 4 repeats | - | 15/16, then C1 and C3 4/4 (final text) |
| K2 false premise corrected | 1/1 | 4/4 |

\* before: A1, A4, S5, one run each over 8 intro-type cases.

The prompt was 2,295 tokens / 9.8 s cold on 2026-10-23; the growth to about 4,900 is mostly the `mcp` meta tool
(5,274 chars listing 38 servers) and the workspace's AGENTS.md, CLAUDE.md and wiki titles, not the persona.

Quick agent bench (bugfix, roman, intervals; auto effort):

| | Hidden tests | Wall time | Tool calls | Tool errors |
| :-- | --: | --: | --: | --: |
| Original persona | 25/25 | 677 s | 30 | 0 |
| Red panda persona (first after-text) | 25/25 | 1,759 s | 43 | 4 |
| No persona (`DL_PERSONA=minimal`) | 25/25 | 829 s | 22 | 0 |

The after run's roman took 1,273 s because the model wrote (500, "V") and (400, "IV") into its numeral table and
debugged it; one call went to a non-existent `write_file`. One run each: the time differences are within run-to-run
noise, and the quick tasks are too easy to separate quality (all pass).

Iterations on the after text: a pointer "look it up with ray_identity's ray_self_identity" made introductions call
that tool in 6 of 10 runs; narrowing it to "only when someone asks" did not help; removing the mention left 7 of 10
introduction runs calling some tool (local_wiki, get_system_health, ray_identity). Dropping "curious" did not help
either (6 of 8 intro runs), so it went back; the prompt alone could not stop it.

## Tool precision fixes (2026-10-29, later)

- **Small-talk guard** (`execute_agent_loop` in `tools/dl_cli.py`, `is_small_talk` in `tools/dl_effort.py`): on a turn
  that is only small talk (greetings, "introduce yourself", "what can you do", Ray's names and filler, at most one
  other word such as a friend's name), a tool call is answered with `SMALL_TALK_NOTE` and not run. The tools stay in
  the request: `tool_choice: "none"` would drop them and re-read the whole prompt, as turning a server on does.
  "Hello Ray, check the printer" is not small talk here (it is for the thinking level). `DL_SMALLTALK_GUARD=0` turns
  it off. The Code tab and the benches see the call with `skipped: "small talk"`.
- **Tool descriptions:** `get_system_health`, `get_engine_status`, `local_wiki` and the `mcp` switch say when to use
  them, and that a greeting or a question about Ray does not need them.
- **Aliases:** `write_file`, `create_file`, `read_file`, `open_file`, `edit_file`, `bash`, `shell`, `execute_command`
  run the real tool when the arguments fit (`TOOL_ALIASES`); `write_file` was called in the roman run.
- **Measurement:** the persona bench prints "unneeded in x/y runs that need none, missing in x/y runs that need one";
  T1 (read a file), T2 (weather) and T3 (list files) must call a tool.
- **🐾:** there is no red panda emoji, and the model drew itself as 🦍 and 🐺; the user chose paw prints. The persona
  says his emoji is 🐾 and no other animal; the bench's `paw_emoji_only` check fails any other animal emoji.

| Persona bench | Checks | Unneeded tool calls (ran) | Missing tool calls |
| :-- | --: | --: | --: |
| Original persona | 86/94 | 3/9 (3 ran) | 0/3 |
| Red panda persona | 86/94 | 4/9 (4 ran) | 0/3 |
| Cloud wording fixed, intro cases ×2 | 73/80 | 6/12 (6 ran) | - |
| Guard + descriptions + aliases (29 cases) | 94/97 | 2/9 (0 ran, 2 answered by the guard) | 0/6 |
| 🐾 rule, intro cases ×2 | 65/68 | 2/8 (0 ran) | - |

- The guard run before the 🐾 rule, re-scored with `paw_emoji_only`: 3 of 29 cases used another animal (S1, S4,
  P3). After the rule: 🐾 only in 12 runs; the spoken V2 used no emoji (the voice note).
- Quick agent bench with the guard: 25/25 hidden tests, 782 s (bugfix 100 s, roman 503 s, intervals 179 s), 28 tool
  calls, 0 tool errors, 0 unknown tools.
- Prompt: 4,996 tokens, 15.9 s cold (the descriptions added about 100 tokens).
- Still open: introductions sometimes credit Damir unasked (P4 1 of 2, spoken V2 2 of 2), helped along by the profile
  line that names the home server's owner.

## Not tested

- The deep agent bench (crc32c, expr), more than one run per configuration, the persona in long conversations
  (drift), and spoken prompts by ear in the Code tab.

## Research (read 2026-10-29; [abs] = abstract only)

- Zheng et al. 2024, "When 'A Helpful Assistant' Is Not Really Helpful", EMNLP Findings, arXiv 2311.10054: 162
  personas on 2,410 questions, no gain over no persona.
- PRISM 2026, arXiv 2603.18507 [abs]: expert personas 68.0% vs 71.6% on MMLU; help tone and safety.
- Araujo et al. 2025, "Principled Personas", EMNLP, arXiv 2508.19764 [abs]: irrelevant persona details cost up to
  almost 30 points.
- Salomon et al. 2026, arXiv 2607.17420 [abs]: engineer personas did not improve code correctness; an off-domain
  persona dropped it from 0.92 to 0.67.
- Ruangtanusak et al. 2025, "Talk Less, Call Right", arXiv 2509.00482 [abs]: persona agents over-speak and make
  unneeded tool calls.
- Ibrahim et al. 2025, arXiv 2507.21919: a warm persona set only in the system prompt raised errors by up to 14
  points on Qwen-32B when the user stated a false belief.
- Shah et al. 2026, ACL, arXiv 2604.10733 [abs]: persona agreeableness correlated with sycophancy (up to r = 0.87).
- Li et al. 2024, COLM, arXiv 2402.10962 [abs]; Araujo et al. 2026, EACL, arXiv 2512.12775 [abs]: personas drift
  over long conversations.
- Shi et al. 2023, ICML, arXiv 2302.00093; Levy et al. 2024, ACL, arXiv 2402.14848: irrelevant or longer context
  lowers accuracy.
- Gan and Sun 2025, RAG-MCP, arXiv 2505.03275 [abs]: all MCP tool descriptions in the prompt gave 13.6% tool
  selection accuracy, retrieving only relevant ones 43.1%.
- Rana 2026, arXiv 2601.08070 [abs], single-author: naming a forbidden word primes it.
- Cho et al. 2024, "Speechworthy Instruction-tuned Language Models", EMNLP: listeners dislike lists and parentheses
  in spoken answers.
- Vendor guidance: Anthropic prompting best practices (say what to do and why), OpenAI GPT-4.1 and GPT-5 prompting
  guides (no hype or all-caps; contradictions waste reasoning), Google Gemini prompting strategies (persona in the
  system instruction).

## Related

- [Ray: Assistant Name, Voice and Persona](../decisions/ray-assistant-persona.md)
- [Ray Persona Bench and Prompt Trim (2026-10-23)](ray-persona-bench-2026-10-23.md)

## Sources

1. User, chat, 2026-10-29.
2. Runs in the daemon's default workspace (`STRATA_WORKSPACE_DIR`), folder bench/20261029-* (1029-before, 1029-after, 1029-after-r, 1029-fix, 1029-fix2,
   1029-full-before, 1029-full-after, 1029-minimal).
3. URLs: https://arxiv.org/abs/2311.10054, https://arxiv.org/pdf/2603.18507, https://arxiv.org/abs/2508.19764,
   https://arxiv.org/abs/2607.17420, https://arxiv.org/abs/2509.00482, https://arxiv.org/abs/2507.21919,
   https://arxiv.org/abs/2604.10733, https://arxiv.org/abs/2402.10962, https://arxiv.org/abs/2512.12775,
   https://arxiv.org/abs/2302.00093, https://arxiv.org/abs/2402.14848, https://arxiv.org/abs/2505.03275,
   https://arxiv.org/abs/2601.08070, https://aclanthology.org/2024.emnlp-main.595 (all accessed 2026-10-29).
