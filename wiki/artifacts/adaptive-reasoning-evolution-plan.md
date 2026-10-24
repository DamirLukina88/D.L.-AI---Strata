---
title: "Adaptive Reasoning Evolution Plan"
type: artifact
description: "Implementation plan for tiered reasoning budget caps, empirical evaluation matrix, and CPU semantic router."
status: active
tags: [effort, reasoning, plan, budget, semantic-router]
created: 2026-10-23
updated: 2026-10-24
last_verified: 2026-10-24
---

# Adaptive Reasoning Evolution: Multi-Phase Implementation Plan

## Goal Description
Evolve Strata's `/effort auto` thinking system from pure keyword/failure-event heuristics into an empirically verified, budget-capped, hybrid semantic reasoning framework based on findings in test-time compute literature (Snell et al. 2024, Ares 2026, Kassenaar et al. 2026, RouteLLM).

The implementation is structured into three self-contained phases:
1. **Phase 1: Dynamic Reasoning Budget Capping (`reasoning_budget_tokens`) & Runaway Loop Protection**: Pair each auto effort level with a tiered token budget cap, preventing runaway 7,000-token loops without clipping valid reasoning.
2. **Phase 2: Empirical Response Matrix & Evaluation Suite (`tools/bench_effort_matrix.py`)**: Implement an offline-replayable and live evaluation harness across Voice, Chat, and Coding cohorts to establish local ground-truth labels and compute efficiency statistics.
3. **Phase 3: CPU-Based Semantic Difficulty Scorer for Ambiguous Middle-Band Prompts**: Deploy a dependency-free, lightweight CPU embedding/similarity router (<2 ms latency) to classify nuanced queries where keyword heuristics fall short.

---

## Architecture

```text
User Prompt (Voice / Typed)
       │
       ▼
Layer 1: High-Confidence Intent Rules (tools/dl_effort.py)
       ├─── Intent Match (Small talk / Home / Code / Plan) ───► Concrete Level (none / high)
       └─── Middle Band (Ambiguous / General) ────────────────► Layer 3: CPU Semantic Scorer (Phase 3)
                                                                       │
                                                                       ▼
                                                             Resolved Level (none / low / med / high)
                                                                       │
                                                                       ▼
                                                             Assign Tiered Budget (Phase 1)
                                                             none: 0 | low: 1024 | med: 2048 | high: 4096
                                                                       │
                                                                       ▼
                                                             Agent Loop (tools/dl_cli.py)
                                                                       │
                                                             [Failure / Exit != 0] ──► Mid-Turn Escalation
                                                                                       Effort -> high | Budget -> 4096
                                                                       │
                                                                       ▼
                                                             Strata Engine Execution (serve/server.py)
                                                             [Tokens >= Budget] ──► Inject Wrap-Up & Answer
```

---

## Detailed Components

### Component 1: Phase 1 — Dynamic Reasoning Budget Capping
- Module constant `BUDGET_TIERS: dict[str, int] = {"none": 0, "low": 1024, "medium": 2048, "high": 4096}` in `tools/dl_effort.py`.
- Helper `budget_for(level: str, custom_caps: dict[str, int] | None = None) -> int`.
- In `Session._agent` (`tools/dl_sessiond.py`), resolve budget and pass `ctx["reasoning_budget_tokens"]`.
- In `stream_chat_turn` (`tools/dl_cli.py`), inject `"reasoning_budget_tokens": budget` into the OpenAI payload when `budget > 0`.
- In `_auto_raise`, escalate effort to `"high"` and budget to `4096`.

### Component 2: Phase 2 — Empirical Response Matrix & Evaluation Suite
- Standalone benchmark runner in `tools/bench_effort_matrix.py`.
- 75 benchmark items across `VOICE_HOUSEHOLD`, `CHAT_EXPLAIN`, and `CODING_AGENT`.
- Modes: `--offline` (default, instant 0-GPU simulation) and `--live` (live model sweep).
- Outputs comprehensive markdown table and exports JSON dataset to `~/.local/state/dl-ai/benchmarks/effort_matrix.json`.

### Component 3: Phase 3 — CPU-Based Semantic Difficulty Scorer
- Fast zero-dependency classifier in `tools/dl_effort_scorer.py`.
- Deterministic CRC32 token/n-gram hashing + cosine similarity $k\text{-NN}$.
- Inference latency strictly <2 ms (benchmarked at 0.09 ms/query).
- Upward safety bias: confidence < 0.65 defaults to `high`.
- Integrated into `dl_effort.pick(..., semantic=True)`, enabled via `DL_SEMANTIC_ROUTER=1`.

---

## Related
- [Auto Thinking Level (/effort auto)](../decisions/auto-thinking-level.md)
- [Strata v0.1.44.1 Benchmark Report (2026-10-23 Baseline)](strata-benchmark-2026-10-23-baseline.md)

---

## Sources
- Antigravity session `f88cd8d3-9b5b-4621-9af1-cd228f9add83`, 2026-10-23 to 2026-10-24.
- Test-time compute literature: Snell et al. 2024, Ares 2026, Kassenaar et al. 2026, RouteLLM.
- Benchmark records: `bench/results/2026-10-23-community-unknown-qwen3-8-flash-next-coder-iq1-m/`.
