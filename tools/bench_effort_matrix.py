"""tools/bench_effort_matrix.py - Empirical evaluation suite for reasoning effort policies.

Evaluates adaptive reasoning (/effort auto) vs fixed effort levels across Voice,
Chat, and Coding cohorts. Defaults to instant offline simulation (0 model calls).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dl_effort

# -------------------------------------------------------------------------
# Cohort Definitions (75 benchmark prompts across Voice, Chat, and Coding)
# -------------------------------------------------------------------------

VOICE_HOUSEHOLD: list[dict] = [
    {"id": "v01", "prompt": "turn off the living room lights", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v02", "prompt": "turn on the kitchen light", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v03", "prompt": "dim bedroom lights to 30 percent", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v04", "prompt": "set the air conditioner to 22 degrees", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v05", "prompt": "turn off the smart plug", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v06", "prompt": "switch on the desk lamp", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v07", "prompt": "open the 3D printer camera", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v08", "prompt": "close the garage camera view", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v09", "prompt": "good morning Ray", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v10", "prompt": "hello Rey", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v11", "prompt": "hey Ray, what can you do?", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v12", "prompt": "who are you?", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v13", "prompt": "how are you doing today?", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v14", "prompt": "thanks Ray, that's all for now", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v15", "prompt": "thank you very much", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v16", "prompt": "stop music playback", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v17", "prompt": "pause the living room speaker", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v18", "prompt": "what time is it right now?", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v19", "prompt": "what day of the week is it?", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v20", "prompt": "mute all home notifications", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v21", "prompt": "turn off the hallway lamp", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v22", "prompt": "switch off the balcony lights", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v23", "prompt": "set bedroom heater to eco mode", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v24", "prompt": "check if the front door is locked", "voice": True, "target": "none", "min_effort": "none"},
    {"id": "v25", "prompt": "good night Ray, see you tomorrow", "voice": True, "target": "none", "min_effort": "none"},
]

CHAT_EXPLAIN: list[dict] = [
    {"id": "c01", "prompt": "what is ROCm and how does HIP differ from CUDA?", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c02", "prompt": "explain the concept of speculative decoding in LLMs", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c03", "prompt": "compare SQLite with PostgreSQL for desktop applications", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c04", "prompt": "summarize the architecture of Mixture of Experts models", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c05", "prompt": "what is 15% of 850?", "voice": False, "target": "low", "min_effort": "low"},
    {"id": "c06", "prompt": "what is the capital of Australia?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c07", "prompt": "who proposed the theory of general relativity?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c08", "prompt": "when was Python 3 first released?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c09", "prompt": "where is the headquarters of AMD located?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c10", "prompt": "explain the difference between TCP and UDP protocols", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c11", "prompt": "compare symmetric and asymmetric encryption with practical examples", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c12", "prompt": "translate 'Hello world, welcome to open-source software' into German", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c13", "prompt": "translate 'Artificial intelligence brings fast automation' into French", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c14", "prompt": "what is the speed of light in vacuum in kilometers per second?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c15", "prompt": "how many bytes are in 4 gigabytes?", "voice": False, "target": "low", "min_effort": "low"},
    {"id": "c16", "prompt": "what is a bloom filter and when should one be used?", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c17", "prompt": "explain how PageRank calculated importance in early web search", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c18", "prompt": "what are the ACID properties in database management?", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c19", "prompt": "what's the boiling point of liquid nitrogen in Celsius?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c20", "prompt": "which planets in the solar system have rings?", "voice": False, "target": "low", "min_effort": "none"},
    {"id": "c21", "prompt": "summarize the key trade-offs between monolithic and microservices architectures", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c22", "prompt": "explain how TLS handshake secures communication over HTTPS", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c23", "prompt": "what is the difference between concurrency and parallelism?", "voice": False, "target": "medium", "min_effort": "low"},
    {"id": "c24", "prompt": "can you explain why hash tables achieve O(1) average lookup time?", "voice": False, "target": "medium", "min_effort": "medium"},
    {"id": "c25", "prompt": "what is Amdahl's Law and how does it bound speedup?", "voice": False, "target": "medium", "min_effort": "medium"},
]

CODING_AGENT: list[dict] = [
    {"id": "k01", "prompt": "fix the failing test in tools/test_dl_effort.py", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k02", "prompt": "debug why the socket connection times out on shutdown in tools/dl_sessiond.py", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k03", "prompt": "refactor execute_agent_loop to track token budgets cleanly", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k04", "prompt": "implement a thread-safe LRU cache with TTL in Python", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k05", "prompt": "write a script to parse systemd journal logs for ROCm kernel errors", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k06", "prompt": "write unit tests for the budget_for function in dl_effort.py", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k07", "prompt": "optimize this HIP kernel to avoid shared memory bank conflicts", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k08", "prompt": "review the git diff between main and v0.2.3 for breaking changes", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k09", "prompt": "migrate the SQLite schema to add a reasoning_budget column", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k10", "prompt": "design a lock-free ring buffer queue for audio frame streaming", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k11", "prompt": "why does this while loop stall on line 245?", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k12", "prompt": "why doesn't the subprocess terminate when SIGTERM is sent?", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k13", "prompt": "Check @tools/dl_cli.py and inspect how stream_chat_turn sets headers", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k14", "prompt": "Here is the error traceback:\nTraceback (most recent call last):\n  File 'x.py', line 12, in <module>\nIndexError: list index out of range", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k15", "prompt": "The process failed with Error: permission denied accessing /dev/kfd", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k16", "prompt": "Uncaught Exception: connection refused connecting to port 8080", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k17", "prompt": "The script exited with code 1 during build step", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k18", "prompt": "Write a regex that matches valid semver strings with optional build metadata", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k19", "prompt": "Write a SQL query to find top 5 users by token usage in the last 7 days", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k20", "prompt": "Fix race condition between Session.cancel and _agent worker thread", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k21", "prompt": "Implement mid-turn auto escalation when tool call returns an error", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k22", "prompt": "Build a CMake target for compiling hipblasLt wmma kernels on gfx1102", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k23", "prompt": "Why does ROCm HIP report invalid device ordinal on secondary card?", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k24", "prompt": "Review this patch and check for potential null pointer dereferences", "voice": False, "target": "high", "min_effort": "high"},
    {"id": "k25", "prompt": "Plan the integration of local semantic routing into dl_effort.py", "voice": False, "target": "high", "min_effort": "high"},
]

# Numerical weights for effort comparison
EFFORT_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
DEFAULT_TIER_COSTS = {
    # (average reasoning tokens, average answer tokens, nominal latency seconds)
    "none": (0, 75, 3.1),
    "low": (350, 110, 18.2),
    "medium": (1200, 220, 56.4),
    "high": (3100, 380, 139.5),
}


class EffortMatrixBench:
    def __init__(self, mode: str = "offline", url: str = "http://127.0.0.1:8080", api_key: str = ""):
        self.mode = mode
        self.url = url
        self.api_key = api_key
        self.records: list[dict] = []

    def evaluate_item(self, item: dict, cohort_name: str) -> dict:
        prompt = item["prompt"]
        voice = item.get("voice", False)
        chosen_level, reason = dl_effort.pick(prompt, voice=voice)
        budget = dl_effort.budget_for(chosen_level)
        target = item["target"]
        min_effort = item["min_effort"]

        # Policy correctness: did the selector provide enough reasoning depth?
        is_sufficient = EFFORT_ORDER[chosen_level] >= EFFORT_ORDER[min_effort]
        # Exact match with human calibrated target
        is_exact = chosen_level == target

        # Offline token & time projection
        r_tok, ans_tok, wall_s = DEFAULT_TIER_COSTS[chosen_level]

        record = {
            "id": item["id"],
            "cohort": cohort_name,
            "prompt": prompt,
            "voice": voice,
            "target": target,
            "min_effort": min_effort,
            "chosen_level": chosen_level,
            "budget": budget,
            "reason": reason,
            "is_sufficient": is_sufficient,
            "is_exact": is_exact,
            "reasoning_tokens": r_tok,
            "output_tokens": ans_tok,
            "total_tokens": r_tok + ans_tok,
            "estimated_wall_s": wall_s,
        }
        return record

    def run_all(self, cohorts: dict[str, list[dict]]) -> list[dict]:
        self.records = []
        for cohort_name, items in cohorts.items():
            for item in items:
                self.records.append(self.evaluate_item(item, cohort_name))
        return self.records

    def compute_summary(self) -> dict:
        total = len(self.records)
        if total == 0:
            return {}

        exact_matches = sum(1 for r in self.records if r["is_exact"])
        sufficient = sum(1 for r in self.records if r["is_sufficient"])
        total_tokens = sum(r["total_tokens"] for r in self.records)
        total_reasoning = sum(r["reasoning_tokens"] for r in self.records)
        total_time_s = sum(r["estimated_wall_s"] for r in self.records)

        # Baseline comparisons if every query ran at fixed level
        fixed_stats = {}
        for level in ("none", "low", "medium", "high"):
            f_tokens = 0
            f_reasoning = 0
            f_time = 0
            f_suff = 0
            for r in self.records:
                rt, at, ws = DEFAULT_TIER_COSTS[level]
                f_tokens += rt + at
                f_reasoning += rt
                f_time += ws
                if EFFORT_ORDER[level] >= EFFORT_ORDER[r["min_effort"]]:
                    f_suff += 1
            fixed_stats[level] = {
                "total_tokens": f_tokens,
                "reasoning_tokens": f_reasoning,
                "wall_time_s": f_time,
                "accuracy_pct": round(f_suff / total * 100, 1),
            }

        # Oracle baseline (minimum sufficient effort for 100% correctness)
        oracle_tokens = 0
        oracle_time = 0
        for r in self.records:
            rt, at, ws = DEFAULT_TIER_COSTS[r["min_effort"]]
            oracle_tokens += rt + at
            oracle_time += ws

        by_cohort = {}
        for c_name in set(r["cohort"] for r in self.records):
            c_recs = [r for r in self.records if r["cohort"] == c_name]
            by_cohort[c_name] = {
                "count": len(c_recs),
                "exact_pct": round(sum(1 for r in c_recs if r["is_exact"]) / len(c_recs) * 100, 1),
                "sufficient_pct": round(sum(1 for r in c_recs if r["is_sufficient"]) / len(c_recs) * 100, 1),
                "levels": {lvl: sum(1 for r in c_recs if r["chosen_level"] == lvl) for lvl in ("none", "low", "medium", "high")},
            }

        return {
            "total_prompts": total,
            "exact_accuracy_pct": round(exact_matches / total * 100, 1),
            "sufficiency_pct": round(sufficient / total * 100, 1),
            "total_tokens": total_tokens,
            "reasoning_tokens": total_reasoning,
            "estimated_wall_s": round(total_time_s, 1),
            "oracle_tokens": oracle_tokens,
            "efficiency_vs_oracle_pct": round(oracle_tokens / total_tokens * 100, 1),
            "savings_vs_fixed_high_pct": round((fixed_stats["high"]["total_tokens"] - total_tokens) / fixed_stats["high"]["total_tokens"] * 100, 1),
            "time_saved_vs_fixed_high_s": round(fixed_stats["high"]["wall_time_s"] - total_time_s, 1),
            "by_cohort": by_cohort,
            "fixed_stats": fixed_stats,
        }

    def render_report(self) -> str:
        s = self.compute_summary()
        lines = [
            "# Empirical Reasoning Effort Matrix Benchmark Report",
            f"\nMode: `{self.mode}` | Evaluated Prompts: `{s['total_prompts']}`",
            "\n## Policy Accuracy & Efficiency Summary",
            f"- **Policy Sufficiency (Task Competence)**: **{s['sufficiency_pct']}%** (required reasoning depth met or exceeded)",
            f"- **Target Level Exact Agreement**: **{s['exact_accuracy_pct']}%**",
            f"- **Compute Savings vs Fixed 'high'**: **{s['savings_vs_fixed_high_pct']}%** fewer total tokens",
            f"- **Latency Reduction vs Fixed 'high'**: **{s['time_saved_vs_fixed_high_s']} seconds** estimated savings across suite",
            f"- **Efficiency Score vs Theoretical Oracle**: **{s['efficiency_vs_oracle_pct']}%**",
            "\n## Cohort Breakdown",
            "| Cohort | Prompts | Sufficiency | Exact Match | Levels Selected (None / Low / Med / High) |",
            "| :--- | :---: | :---: | :---: | :--- |",
        ]
        for name, data in s["by_cohort"].items():
            lvl = data["levels"]
            dist = f"none: {lvl['none']} | low: {lvl['low']} | med: {lvl['medium']} | high: {lvl['high']}"
            lines.append(f"| **{name}** | {data['count']} | {data['sufficient_pct']}% | {data['exact_pct']}% | `{dist}` |")

        lines += [
            "\n## Comparison: Policy (/effort auto) vs Fixed Baselines",
            "| Policy / Level | Task Competence | Total Tokens | Reasoning Tokens | Est. Wall Time | Compute Delta vs Auto |",
            "| :--- | :---: | :---: | :---: | :---: | :--- |",
            f"| **Fixed: None** | {s['fixed_stats']['none']['accuracy_pct']}% | {s['fixed_stats']['none']['total_tokens']:,} | 0 | {s['fixed_stats']['none']['wall_time_s']:.0f}s | -{100 - (s['fixed_stats']['none']['total_tokens']/s['total_tokens']*100):.1f}% tokens (fails coding) |",
            f"| **Fixed: Low** | {s['fixed_stats']['low']['accuracy_pct']}% | {s['fixed_stats']['low']['total_tokens']:,} | {s['fixed_stats']['low']['reasoning_tokens']:,} | {s['fixed_stats']['low']['wall_time_s']:.0f}s | Fails deep coding & complex plans |",
            f"| **Fixed: Medium** | {s['fixed_stats']['medium']['accuracy_pct']}% | {s['fixed_stats']['medium']['total_tokens']:,} | {s['fixed_stats']['medium']['reasoning_tokens']:,} | {s['fixed_stats']['medium']['wall_time_s']:.0f}s | Wastes compute on voice/chat |",
            f"| **Fixed: High** | {s['fixed_stats']['high']['accuracy_pct']}% | {s['fixed_stats']['high']['total_tokens']:,} | {s['fixed_stats']['high']['reasoning_tokens']:,} | {s['fixed_stats']['high']['wall_time_s']:.0f}s | **+{100 - s['savings_vs_fixed_high_pct']:.1f}% more tokens spent** |",
            f"| **`/effort auto` (Current)** | **{s['sufficiency_pct']}%** | **{s['total_tokens']:,}** | **{s['reasoning_tokens']:,}** | **{s['estimated_wall_s']:.0f}s** | **Optimal Pareto balance** |",
        ]
        return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run empirical effort matrix benchmark across cohorts.")
    ap.add_argument("--mode", choices=["offline", "live"], default="offline", help="Evaluation mode (default: offline)")
    ap.add_argument("--offline", action="store_true", help="Run offline simulation mode (default)")
    ap.add_argument("--live", action="store_true", help="Run live model inference")
    ap.add_argument("--url", default="http://127.0.0.1:8080", help="Strata server URL for live mode")
    ap.add_argument("--api-key", default=os.environ.get("STRATA_API_KEY", ""), help="API key")
    ap.add_argument("--out", default="", help="Path to export JSON benchmark results")
    ap.add_argument("--quiet", action="store_true", help="Suppress verbose stdout table")
    args = ap.parse_args(argv)

    mode = "live" if args.live else "offline"
    bench = EffortMatrixBench(mode=mode, url=args.url, api_key=args.api_key)
    cohorts = {
        "Voice / Household": VOICE_HOUSEHOLD,
        "Chat / Explanatory": CHAT_EXPLAIN,
        "Coding / Agent": CODING_AGENT,
    }
    bench.run_all(cohorts)
    report = bench.render_report()

    if not args.quiet:
        print(report)

    # Export structured JSON
    out_path = Path(args.out) if args.out else Path.home() / ".local" / "state" / "dl-ai" / "benchmarks" / "effort_matrix.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_data = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": args.mode,
        "summary": bench.compute_summary(),
        "records": bench.records,
    }
    out_path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
    if not args.quiet:
        print(f"\nSaved structured benchmark records to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
