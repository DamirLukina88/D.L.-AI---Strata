---
title: "Harness² Research and Feasibility Analysis for Ray"
type: artifact
description: "Analysis of Harness² (arXiv 2610.14224v1, google-research/harness2) method, benchmark numbers, tradeoffs, and architectural fit for Ray."
status: active
tags: [harness2, research, architecture, benchmarks, evaluation]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Harness² for Ray: Research & Trade-offs Analysis

## Summary

Analysis of Google Cloud AI Research's Harness² framework ([arXiv:2610.14224v1](https://arxiv.org/html/2610.14224v1), [google-research/harness2](https://github.com/google-research/harness2)) evaluated against Ray and our single-GPU AMD RX 7600 XT setup. Concludes that closed-loop recursive self-editing by an IQ1_M local quant carries severe risk of prompt degradation and safety softening, leading to our chosen architectural separation: autonomous local struggle diary telemetry + human & frontier model (Claude Opus 5.5 / Antigravity) harness engineering.

## 1. What Harness² Does

The paper's starting point is that **Agent = Model + Harness**. The model's weights stay fixed, and only the harness evolves. The harness consists of 8 editable file components:

| Group | Component | When the model sees it |
|---|---|---|
| Context | `systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md` | every call |
| Context | `skills/<n>/SKILL.md` (+ scripts) | only when invoked |
| Tool interface | `tool_guidance.md`, `scripts/*.py` | every call / run via bash |
| Orchestration | `sub_agents/<n>/AGENT.md` | task tool (its own context) |
| Middleware | `plugin/*.ts` (hooks in the tool loop) | enforced as code, not as an instruction |

### Two Levels of Recursion
1. **Task-level recursion (Propose, Probe, Compose):** two candidate harnesses are each executed on the same task. Comparing the trajectories ("did the edit change the behaviour it was aimed at?") stands in for a verifier.
2. **Harnessing-level recursion:** each task starts again from H0. Old harnesses are not inherited; instead a library of adopted harnesses plus evidence-backed lessons guides the next round of edits.

## 2. Benchmark Results Reported by Upstream
- **Gains**: Up to +11.5 on WorkBuddy-Bench, +4.5 on JobBench, and +11.8 percentage points on LAB with $k=1$. Parallel $k=5$ adds +3.9 to +6.7 points.
- **Tool-Use Reliability**: Tool error rate fell 37% on JobBench (14.4% → 9.1%).
- **Cross-Model Transfer**: Refined harnesses transferred effectively across models (Gemini Flash refined harness boosted GLM-5 by +17.3 on Code).
- **Critical Failure Mode**: Refining the harness *without* probes or an experience library degraded performance significantly (Code dropped 73.4 → 63.2).

## 3. Trade-offs and Constraints for Local Workstation
- **Execution Latency**: At ~25-28 tok/s decode, a $k=1$ contrastive step (4 full task runs) on a 12-step task takes 3–4 hours; $k=5$ (~20 runs) is unfeasible on a desktop PC.
- **Side Effects**: Probing on live Home Assistant devices, mail, or shell commands causes repeated physical actions unless sandboxed.
- **Model Capacity Gap**: Self-refinement was demonstrated with Gemini Flash, GLM-5, and Opus 4.8. An IQ1_M quantized local model lacks the meta-reasoning capacity to reliably self-critique without prompt drift.

## Sources

1. User, chat, 2026-10-24.
2. arXiv:2610.14224v1 (Harness²: Recursive Agent Harnessing for an Open World, Google Cloud AI Research, 2026).
3. GitHub google-research/harness2 (2026).
