#!/usr/bin/env python3
"""tools/bench_router_ab.py - Paired A/B benchmark for router modes (rules, model2vec, hybrid).

Evaluates thinking level selection (dl_effort / dl_effort_scorer) and MCP server routing
(dl_mcp / dl_mcp_router) against the private gold set (~/.local/state/dl-ai/benchmarks/router_gold/gold.json).
Never writes personal prompt text into benchmark outputs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dl_effort  # noqa: E402
import dl_effort_scorer  # noqa: E402
import dl_mcp  # noqa: E402
import dl_mcp_router  # noqa: E402
import dl_router  # noqa: E402

DEFAULT_GOLD_PATH = Path.home() / ".local" / "state" / "dl-ai" / "benchmarks" / "router_gold" / "gold.json"
DEFAULT_OUT_DIR = Path.home() / ".local" / "state" / "dl-ai" / "benchmarks"

EFFORT_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}

# Fallback nominal seconds per turn by thinking level (from bench_effort_matrix.py / wiki)
WIKI_LEVEL_SECONDS = {
    "none": 3.1,
    "low": 18.2,
    "medium": 56.4,
    "high": 139.5,
}
# Wiki cost of cold prefix re-read when a wrong server changes the tool list (2,295 tokens)
WIKI_FALSE_START_REREAD_S = 9.8
WIKI_EXTRA_SCHEMA_PER_IDLE_TURN_S = 0.6
WIKI_MISSED_SERVER_ROUND_S = 6.0


def measure_costs_from_gold(records: list[dict], idle_turns: int = 3) -> dict:
    """Estimate per-level thinking seconds and MCP round costs from transcript stats,
    falling back to named wiki figures where transcript sample counts are too small."""
    by_level: dict[str, list[float]] = defaultdict(list)
    single_round_secs: list[float] = []

    for r in records:
        stats = r.get("turn_stats") or []
        if not stats:
            continue
        for st in stats:
            sec = float(st.get("seconds") or 0.0)
            if 0.05 < sec < 600.0:
                single_round_secs.append(sec)
        if r.get("actual_raised"):
            continue
        lvl = r.get("actual_effort_pick")
        if lvl in EFFORT_ORDER:
            total_sec = sum(float(st.get("seconds") or 0.0) for st in stats)
            if 0.05 < total_sec < 600.0:
                by_level[lvl].append(total_sec)

    level_seconds: dict[str, float] = {}
    level_sources: dict[str, str] = {}
    for lvl in ("none", "low", "medium", "high"):
        vals = by_level.get(lvl) or []
        if len(vals) >= 5:
            level_seconds[lvl] = round(statistics.median(vals), 3)
            level_sources[lvl] = f"transcript_median_n={len(vals)}"
        else:
            level_seconds[lvl] = WIKI_LEVEL_SECONDS[lvl]
            level_sources[lvl] = f"wiki_fallback_n={len(vals)}"

    missed_s = (
        round(statistics.median(single_round_secs), 3)
        if len(single_round_secs) >= 10
        else WIKI_MISSED_SERVER_ROUND_S
    )
    false_start_s = round(WIKI_FALSE_START_REREAD_S + idle_turns * WIKI_EXTRA_SCHEMA_PER_IDLE_TURN_S, 3)
    return {
        "level_seconds": level_seconds,
        "level_sources": level_sources,
        "false_start_s": false_start_s,
        "false_start_source": f"wiki_reread_{WIKI_FALSE_START_REREAD_S}s+idle_{idle_turns}x{WIKI_EXTRA_SCHEMA_PER_IDLE_TURN_S}s",
        "missed_server_s": missed_s,
        "missed_server_source": (
            f"transcript_median_round_n={len(single_round_secs)}"
            if len(single_round_secs) >= 10
            else "wiki_fallback"
        ),
    }


def mcnemar_exact(a_ok: list[bool], b_ok: list[bool]) -> dict:
    """Paired McNemar test comparing baseline a_ok (rules) vs b_ok (arm)."""
    n01 = sum(1 for a, b in zip(a_ok, b_ok) if not a and b)  # b fixed a's miss
    n10 = sum(1 for a, b in zip(a_ok, b_ok) if a and not b)  # b broke a's hit
    n = n01 + n10
    if n == 0:
        return {"b_only": 0, "a_only": 0, "p_value": 1.0}
    k = min(n01, n10)
    # Two-sided exact binomial p-value for p=0.5
    p_one = sum(math.comb(n, i) * (0.5 ** n) for i in range(k + 1))
    return {"b_only": n01, "a_only": n10, "p_value": round(min(1.0, 2.0 * p_one), 6)}


def bootstrap_diff_ci(base_vals: list[float], arm_vals: list[float], n_boot: int = 2000, seed: int = 20261113) -> dict:
    """95% bootstrap CI for mean(arm - base); negative = arm saves seconds vs rules."""
    if not base_vals or len(base_vals) != len(arm_vals):
        return {"mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    diffs = [b - a for a, b in zip(base_vals, arm_vals)]
    n = len(diffs)
    mean_d = sum(diffs) / n
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[min(n_boot - 1, int(0.975 * n_boot))]
    return {
        "mean_diff": round(mean_d, 4),
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
    }


def _ensure_builtins_loaded() -> None:
    """Import dl_cli so secrets.env and built-in MCP servers (exa, proton, deepl, schedule)
    are registered in dl_mcp.BUILTINS, matching dl_sessiond.py."""
    try:
        if __package__ == "tools":
            from tools import dl_cli as _dl_cli  # noqa: F401
        else:
            import dl_cli as _dl_cli  # noqa: F401
    except ImportError:
        pass


def _mcp_rules_hits(text: str, origin: str, catalog: dict, surface: str = "code") -> tuple[list[str], bool]:
    """In-memory equivalent of McpRegistry.route() for rules (defaults + origins + triggers + unless)."""
    picked: list[str] = []
    regex_matched = False
    for name, entry in catalog.items():
        if entry.unavailable(surface):
            continue
        if entry.default_on:
            picked.append(name)
            continue
        if origin and any(origin == o or origin.startswith(o + "-") for o in entry.origins):
            picked.append(name)
            continue
        if any(rx.search(text) for rx in entry.unless):
            continue
        for rx in entry.triggers:
            if rx.search(text):
                picked.append(name)
                regex_matched = True
                break
    return picked, regex_matched


def _mcp_arm_hits(
    text: str,
    origin: str,
    catalog: dict,
    *,
    mode: str,
    model_dir: Path | str | None,
    min_score: float,
    none_margin: float,
    surface: str = "code",
) -> list[str]:
    if mode == "rules":
        picked, _ = _mcp_rules_hits(text, origin, catalog, surface=surface)
        return picked

    picked: list[str] = []
    for name, entry in catalog.items():
        if entry.unavailable(surface):
            continue
        if entry.default_on or (origin and any(origin == o or origin.startswith(o + "-") for o in entry.origins)):
            picked.append(name)

    if mode == "model2vec":
        hits, used = dl_mcp_router.route(
            text,
            catalog,
            surface=surface,
            enabled=set(picked),
            model_dir=model_dir,
            min_score=min_score,
            none_margin=none_margin,
        )
        if used:
            picked.extend(n for n, _ in hits)
            return picked
        fallback, _ = _mcp_rules_hits(text, origin, catalog, surface=surface)
        return fallback

    # hybrid
    rules_picked, regex_matched = _mcp_rules_hits(text, origin, catalog, surface=surface)
    picked = rules_picked
    if not regex_matched:
        hits, used = dl_mcp_router.route(
            text,
            catalog,
            surface=surface,
            enabled=set(picked),
            model_dir=model_dir,
            min_score=min_score,
            none_margin=none_margin,
        )
        if used:
            picked.extend(n for n, _ in hits)
    return picked


def _effort_arm_pick(
    rec: dict,
    *,
    mode: str,
    scorer: dl_effort_scorer.EffortScorer | None,
    exclude_self: bool,
) -> str:
    txt = rec["text"]
    voice = bool(rec.get("voice"))
    last_reply = rec.get("last_reply") or ""
    ex = txt if exclude_self else None

    if mode == "rules":
        lvl, _ = dl_effort.pick(txt, voice=voice, mode="act", last_reply=last_reply, router_mode="rules")
        return lvl

    if mode == "model2vec":
        if scorer is not None and scorer.use_model2vec:
            lvl, _ = scorer.predict(txt, exclude_text=ex)
            return lvl
        lvl, _ = dl_effort.pick(txt, voice=voice, mode="act", last_reply=last_reply, router_mode="rules")
        return lvl

    # hybrid
    lvl, rsn = dl_effort.pick(txt, voice=voice, mode="act", last_reply=last_reply, router_mode="rules")
    if rsn == "default" and scorer is not None and scorer.use_model2vec:
        s_lvl, _ = scorer.predict(txt, exclude_text=ex)
        return s_lvl
    return lvl


_ISOLATED_STATS_CACHE: dict[str, dict] = {}


def _isolated_router_stats(model_dir: Path | str | None) -> dict:
    key = str(dl_router.model_dir_path(model_dir))
    if key in _ISOLATED_STATS_CACHE:
        return _ISOLATED_STATS_CACHE[key]
    code = (
        "import json, sys, dl_router; "
        "print(json.dumps(dl_router.stats(sys.argv[1])))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{HERE}:{env.get('PYTHONPATH', '')}".rstrip(":")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, key],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            st = json.loads(proc.stdout.strip().splitlines()[-1])
            _ISOLATED_STATS_CACHE[key] = st
            return st
    except Exception:
        pass
    st = dl_router.stats(model_dir)
    _ISOLATED_STATS_CACHE[key] = st
    return st


def evaluate_arm(
    arm_name: str,
    records: list[dict],
    catalog: dict,
    costs: dict,
    *,
    mode: str,
    model_dir: Path | str | None,
    effort_threshold: float,
    effort_min_sim: float,
    mcp_min_score: float,
    mcp_none_margin: float,
    exclude_self_on_tune: bool,
    use_unreviewed_tune: bool,
    gold_path: Path,
    measure_isolated_rss: bool = True,
) -> dict:
    scorer = None
    router_stats = {"available": False, "rss_delta_mib": 0.0, "load_time_ms": 0.0}
    if mode in ("model2vec", "hybrid"):
        scorer = dl_effort_scorer.EffortScorer(
            threshold=effort_threshold,
            min_sim=effort_min_sim,
            model_dir=model_dir,
            gold_path=gold_path,
            include_gold_tune=True,
            use_unreviewed_tune=use_unreviewed_tune,
        )
        router_stats = _isolated_router_stats(model_dir) if measure_isolated_rss else dl_router.stats(model_dir)
        # Warm MCP index cache before timing queries
        dl_mcp_router.score_servers("warmup", catalog, model_dir=model_dir)

    lvl_secs = costs["level_seconds"]
    false_s = costs["false_start_s"]
    missed_s = costs["missed_server_s"]

    # Effort metrics (evaluated on records with gold_effort, or effort_proposed ONLY on unreviewed tune dry-run)
    eff_recs = []
    for r in records:
        g = r.get("gold_effort")
        if g in EFFORT_ORDER:
            eff_recs.append((r, g))
        elif use_unreviewed_tune and r.get("effort_sample") and r.get("effort_proposed") in EFFORT_ORDER:
            eff_recs.append((r, r["effort_proposed"]))
    eff_suff_flags: list[bool] = []
    eff_over_flags: list[bool] = []
    eff_under_flags: list[bool] = []
    eff_exact_flags: list[bool] = []
    eff_secs: list[float] = []
    eff_lat_ms: list[float] = []

    for r, gold in eff_recs:
        t0 = time.perf_counter()
        chosen = _effort_arm_pick(r, mode=mode, scorer=scorer, exclude_self=exclude_self_on_tune)
        eff_lat_ms.append((time.perf_counter() - t0) * 1000.0)
        eff_suff_flags.append(EFFORT_ORDER[chosen] >= EFFORT_ORDER[gold])
        eff_over_flags.append(EFFORT_ORDER[chosen] > EFFORT_ORDER[gold])
        eff_under_flags.append(EFFORT_ORDER[chosen] < EFFORT_ORDER[gold])
        eff_exact_flags.append(chosen == gold)
        # Expected thinking seconds (if under-thought, add expected mid-turn raise cost to high? Report raw chosen seconds + underthink note)
        eff_secs.append(lvl_secs[chosen])

    # MCP metrics (evaluated on all records in split)
    mcp_exact_flags: list[bool] = []
    mcp_full_recall_flags: list[bool] = []
    mcp_lost_secs: list[float] = []
    mcp_lat_ms: list[float] = []
    needed_total = 0
    recalled_total = 0
    false_starts_total = 0
    empty_gold_prompts = 0
    false_starts_on_empty = 0

    for r in records:
        gold_set = set(r.get("gold_mcp") or [])
        t0 = time.perf_counter()
        pred_list = _mcp_arm_hits(
            r["text"],
            r.get("origin") or "",
            catalog,
            mode=mode,
            model_dir=model_dir,
            min_score=mcp_min_score,
            none_margin=mcp_none_margin,
        )
        mcp_lat_ms.append((time.perf_counter() - t0) * 1000.0)
        pred_set = set(pred_list)

        tp = len(gold_set & pred_set)
        fp = len(pred_set - gold_set)
        fn = len(gold_set - pred_set)
        needed_total += len(gold_set)
        recalled_total += tp
        false_starts_total += fp
        if not gold_set:
            empty_gold_prompts += 1
            false_starts_on_empty += fp

        mcp_exact_flags.append(pred_set == gold_set)
        mcp_full_recall_flags.append(fn == 0)
        mcp_lost_secs.append(fp * false_s + fn * missed_s)

    n_eff = len(eff_recs) or 1
    n_all = len(records) or 1
    return {
        "arm": arm_name,
        "mode": mode,
        "model_dir": str(dl_router.model_dir_path(model_dir)) if model_dir or mode != "rules" else "",
        "router_stats": router_stats,
        "effort": {
            "n": len(eff_recs),
            "sufficiency": round(sum(eff_suff_flags) / n_eff, 4),
            "overthink_rate": round(sum(eff_over_flags) / n_eff, 4),
            "underthink_rate": round(sum(eff_under_flags) / n_eff, 4),
            "exact_rate": round(sum(eff_exact_flags) / n_eff, 4),
            "expected_thinking_s": round(sum(eff_secs) / n_eff, 3),
            "mean_router_ms": round(sum(eff_lat_ms) / n_eff, 3),
        },
        "mcp": {
            "n": len(records),
            "needed_instances": needed_total,
            "recalled_instances": recalled_total,
            "recall": round(recalled_total / needed_total, 4) if needed_total else 1.0,
            "full_recall_rate": round(sum(mcp_full_recall_flags) / n_all, 4),
            "exact_rate": round(sum(mcp_exact_flags) / n_all, 4),
            "false_starts": false_starts_total,
            "false_starts_per_turn": round(false_starts_total / n_all, 4),
            "empty_gold_prompts": empty_gold_prompts,
            "false_starts_on_empty": false_starts_on_empty,
            "false_starts_on_empty_rate": round(false_starts_on_empty / (empty_gold_prompts or 1), 4),
            "expected_lost_s": round(sum(mcp_lost_secs) / n_all, 3),
            "mean_router_ms": round(sum(mcp_lat_ms) / n_all, 3),
        },
        "_raw": {
            "eff_suff_flags": eff_suff_flags,
            "eff_secs": eff_secs,
            "mcp_full_recall_flags": mcp_full_recall_flags,
            "mcp_exact_flags": mcp_exact_flags,
            "mcp_lost_secs": mcp_lost_secs,
        },
    }


def tune_thresholds(
    records: list[dict],
    catalog: dict,
    costs: dict,
    model_dir: Path,
    gold_path: Path,
    *,
    use_unreviewed_tune: bool = False,
) -> dict:
    """Grid-search effort and MCP thresholds on the tuning split only."""
    lvl_secs = costs["level_seconds"]
    false_s = costs["false_start_s"]
    missed_s = costs["missed_server_s"]

    # Effort sweep (build EffortScorer once, precompute rules decisions)
    eff_recs = []
    for r in records:
        g = r.get("gold_effort")
        if g in EFFORT_ORDER:
            eff_recs.append((r, g))
        elif use_unreviewed_tune and r.get("effort_sample") and r.get("effort_proposed") in EFFORT_ORDER:
            eff_recs.append((r, r["effort_proposed"]))

    scorer = dl_effort_scorer.EffortScorer(
        model_dir=model_dir,
        gold_path=gold_path,
        include_gold_tune=True,
        use_unreviewed_tune=use_unreviewed_tune,
    )
    rules_eff = [
        dl_effort.pick(
            r["text"],
            voice=bool(r.get("voice")),
            mode="act",
            last_reply=r.get("last_reply") or "",
            router_mode="rules",
        )
        for r, _ in eff_recs
    ]
    n_eff = len(eff_recs) or 1

    best_eff = None
    for thr in (0.55, 0.60, 0.65, 0.70, 0.75):
        for min_sim in (0.25, 0.35, 0.45):
            scorer.threshold = thr
            scorer.min_sim = min_sim
            suff = 0
            over = 0
            under = 0
            exact = 0
            secs = 0.0
            for (r, gold), (r_lvl, r_rsn) in zip(eff_recs, rules_eff):
                if r_rsn == "default" and scorer.use_model2vec:
                    chosen, _ = scorer.predict(r["text"], exclude_text=r["text"])
                else:
                    chosen = r_lvl
                suff += int(EFFORT_ORDER[chosen] >= EFFORT_ORDER[gold])
                over += int(EFFORT_ORDER[chosen] > EFFORT_ORDER[gold])
                under += int(EFFORT_ORDER[chosen] < EFFORT_ORDER[gold])
                exact += int(chosen == gold)
                secs += lvl_secs[chosen]
            e = {
                "n": len(eff_recs),
                "sufficiency": round(suff / n_eff, 4),
                "overthink_rate": round(over / n_eff, 4),
                "underthink_rate": round(under / n_eff, 4),
                "exact_rate": round(exact / n_eff, 4),
                "expected_thinking_s": round(secs / n_eff, 3),
            }
            score = (e["sufficiency"] >= 0.85, -e["expected_thinking_s"], e["sufficiency"])
            if best_eff is None or score > best_eff[0]:
                best_eff = (score, {"threshold": thr, "min_sim": min_sim, "metrics": e})

    # MCP sweep (precompute rules + raw similarity scores once per record)
    pre_mcp = []
    for r in records:
        gold_set = set(r.get("gold_mcp") or [])
        rules_picked, regex_matched = _mcp_rules_hits(r["text"], r.get("origin") or "", catalog, surface="code")
        scored, none_s, used_m = (
            ([], 0.0, False)
            if regex_matched
            else dl_mcp_router.score_servers(
                r["text"],
                catalog,
                surface="code",
                enabled=set(rules_picked),
                model_dir=model_dir,
            )
        )
        pre_mcp.append((gold_set, rules_picked, regex_matched, scored, none_s, used_m))

    n_all = len(records) or 1
    best_mcp = None
    for ms in (0.35, 0.40, 0.42, 0.45, 0.50, 0.55):
        for mg in (0.00, 0.03, 0.05, 0.08, 0.12):
            needed_total = 0
            recalled_total = 0
            false_starts_total = 0
            empty_gold_prompts = 0
            false_starts_on_empty = 0
            full_recall_n = 0
            exact_n = 0
            lost_s = 0.0
            for gold_set, rules_picked, regex_matched, scored, none_s, used_m in pre_mcp:
                pred = list(rules_picked)
                if not regex_matched and used_m:
                    extra = [
                        name
                        for name, s in scored
                        if s >= ms and (s - none_s) >= mg
                    ][: dl_mcp_router.MAX_SERVERS]
                    pred.extend(extra)
                pred_set = set(pred)
                tp = len(gold_set & pred_set)
                fp = len(pred_set - gold_set)
                fn = len(gold_set - pred_set)
                needed_total += len(gold_set)
                recalled_total += tp
                false_starts_total += fp
                if not gold_set:
                    empty_gold_prompts += 1
                    false_starts_on_empty += fp
                full_recall_n += int(fn == 0)
                exact_n += int(pred_set == gold_set)
                lost_s += fp * false_s + fn * missed_s

            m = {
                "n": len(records),
                "needed_instances": needed_total,
                "recalled_instances": recalled_total,
                "recall": round(recalled_total / needed_total, 4) if needed_total else 1.0,
                "full_recall_rate": round(full_recall_n / n_all, 4),
                "exact_rate": round(exact_n / n_all, 4),
                "false_starts": false_starts_total,
                "false_starts_per_turn": round(false_starts_total / n_all, 4),
                "empty_gold_prompts": empty_gold_prompts,
                "false_starts_on_empty": false_starts_on_empty,
                "false_starts_on_empty_rate": round(false_starts_on_empty / (empty_gold_prompts or 1), 4),
                "expected_lost_s": round(lost_s / n_all, 3),
            }
            score = (-m["expected_lost_s"], m["recall"])
            if best_mcp is None or score > best_mcp[0]:
                best_mcp = (score, {"min_score": ms, "none_margin": mg, "metrics": m})

    return {
        "model_dir": str(model_dir),
        "best_effort": best_eff[1] if best_eff else {},
        "best_mcp": best_mcp[1] if best_mcp else {},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paired A/B benchmark of router modes on private gold split.")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    ap.add_argument("--split", choices=["tune", "test"], default="tune")
    ap.add_argument("--catalog", type=Path, default=None)
    ap.add_argument("--tune-thresholds", action="store_true", help="Sweep thresholds on tune split ONLY")
    ap.add_argument("--tune-model", choices=["128m", "32m", "both"], default="both")
    ap.add_argument("--effort-threshold", type=float, default=dl_effort_scorer.CONFIDENCE_THRESHOLD)
    ap.add_argument("--effort-min-sim", type=float, default=dl_effort_scorer.MIN_SIMILARITY)
    ap.add_argument("--mcp-min-score", type=float, default=dl_mcp_router.MIN_SCORE)
    ap.add_argument("--mcp-none-margin", type=float, default=dl_mcp_router.NONE_MARGIN)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.tune_thresholds and args.split != "tune":
        print("Error: --tune-thresholds is only allowed with --split tune.", file=sys.stderr)
        return 2

    if not args.gold.is_file():
        print(f"Error: gold dataset not found at {args.gold}. Run tools/router_gold.py first.", file=sys.stderr)
        return 1

    data = json.loads(args.gold.read_text(encoding="utf-8"))
    reviewed = bool(data.get("reviewed", False))
    if args.split == "test" and not reviewed:
        print(
            "Error: gold.json is not reviewed yet (reviewed=false). "
            "Gate 1 requires reviewing review.md and running tools/router_gold.py --import-review before --split test.",
            file=sys.stderr,
        )
        return 2
    use_unreviewed_tune = args.split == "tune" and not reviewed
    all_records = data.get("records") or []
    records = [r for r in all_records if r.get("split") == args.split]
    if not records:
        print(f"Error: no records found for split={args.split!r}.", file=sys.stderr)
        return 1

    _ensure_builtins_loaded()
    catalog, settings, problems = dl_mcp.load_catalog(args.catalog)
    costs = measure_costs_from_gold(all_records, idle_turns=int(settings.get("idle_turns", 3)))

    models_root = Path.home() / ".local" / "share" / "dl-ai" / "models"
    m128 = models_root / "potion-multilingual-128M-int8"
    m32 = models_root / "potion-base-32M-int8"

    if args.tune_thresholds:
        out_tune = {}
        if args.tune_model in ("128m", "both"):
            out_tune["128m"] = tune_thresholds(
                records,
                catalog,
                costs,
                m128,
                args.gold,
                use_unreviewed_tune=use_unreviewed_tune,
            )
        if args.tune_model in ("32m", "both"):
            out_tune["32m"] = tune_thresholds(
                records,
                catalog,
                costs,
                m32,
                args.gold,
                use_unreviewed_tune=use_unreviewed_tune,
            )
        print(json.dumps(out_tune, indent=2))
        return 0

    arms_cfg = [
        ("rules", "rules", None),
        ("model2vec_128m", "model2vec", m128),
        ("hybrid_128m", "hybrid", m128),
        ("model2vec_32m", "model2vec", m32),
        ("hybrid_32m", "hybrid", m32),
    ]

    results = {}
    exclude_self = args.split == "tune"
    for arm_name, mode, mdir in arms_cfg:
        results[arm_name] = evaluate_arm(
            arm_name,
            records,
            catalog,
            costs,
            mode=mode,
            model_dir=mdir,
            effort_threshold=args.effort_threshold,
            effort_min_sim=args.effort_min_sim,
            mcp_min_score=args.mcp_min_score,
            mcp_none_margin=args.mcp_none_margin,
            exclude_self_on_tune=exclude_self,
            use_unreviewed_tune=use_unreviewed_tune,
            gold_path=args.gold,
        )

    base = results["rules"]["_raw"]
    comparisons = {}
    for arm_name, res in results.items():
        if arm_name == "rules":
            continue
        raw = res["_raw"]
        comparisons[arm_name] = {
            "effort_suff_mcnemar": mcnemar_exact(base["eff_suff_flags"], raw["eff_suff_flags"]),
            "effort_seconds_diff_vs_rules": bootstrap_diff_ci(base["eff_secs"], raw["eff_secs"]),
            "mcp_recall_mcnemar": mcnemar_exact(base["mcp_full_recall_flags"], raw["mcp_full_recall_flags"]),
            "mcp_exact_mcnemar": mcnemar_exact(base["mcp_exact_flags"], raw["mcp_exact_flags"]),
            "mcp_lost_seconds_diff_vs_rules": bootstrap_diff_ci(base["mcp_lost_secs"], raw["mcp_lost_secs"]),
        }

    # Strip raw per-prompt lists before saving
    clean_arms = {k: {kk: vv for kk, vv in v.items() if kk != "_raw"} for k, v in results.items()}
    effort_labels_source = "unreviewed_proposed_dry_run" if use_unreviewed_tune else "reviewed_gold"
    report = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "split": args.split,
        "reviewed": reviewed,
        "effort_labels_source": effort_labels_source,
        "record_count": len(records),
        "settings": {
            "effort_threshold": args.effort_threshold,
            "effort_min_sim": args.effort_min_sim,
            "mcp_min_score": args.mcp_min_score,
            "mcp_none_margin": args.mcp_none_margin,
        },
        "costs": costs,
        "arms": clean_arms,
        "comparisons_vs_rules": comparisons,
    }

    out_path = args.out
    if out_path is None:
        fname = "router_ab_20261113.json" if args.split == "test" else "router_ab_tune_20261113.json"
        out_path = DEFAULT_OUT_DIR / fname
    out_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    # Print summary table (no prompt texts)
    print(f"Split: {args.split} ({len(records)} prompts) | Saved: {out_path}")
    print("\nThinking level:")
    print(f"{'Arm':<16} {'Suff':>7} {'Over':>7} {'Exact':>7} {'Exp(s)':>8} {'Delta(s)':>10} {'Router(ms)':>10}")
    for k, v in clean_arms.items():
        e = v["effort"]
        d = comparisons[k]["effort_seconds_diff_vs_rules"]["mean_diff"] if k in comparisons else 0.0
        print(f"{k:<16} {e['sufficiency']:>7.3f} {e['overthink_rate']:>7.3f} {e['exact_rate']:>7.3f} "
              f"{e['expected_thinking_s']:>8.2f} {d:>+10.2f} {e['mean_router_ms']:>10.3f}")

    print("\nMCP servers:")
    print(f"{'Arm':<16} {'Recall':>7} {'FS/turn':>8} {'FS@empty':>9} {'Lost(s)':>8} {'Delta(s)':>10} {'RSS(MiB)':>9}")
    for k, v in clean_arms.items():
        m = v["mcp"]
        d = comparisons[k]["mcp_lost_seconds_diff_vs_rules"]["mean_diff"] if k in comparisons else 0.0
        rss = v["router_stats"].get("rss_delta_mib", 0.0)
        print(f"{k:<16} {m['recall']:>7.3f} {m['false_starts_per_turn']:>8.4f} {m['false_starts_on_empty_rate']:>9.4f} "
              f"{m['expected_lost_s']:>8.3f} {d:>+10.3f} {rss:>9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
