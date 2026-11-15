#!/usr/bin/env python3
"""tools/router_gold.py - Extract a private gold set from local dl-ai transcripts for router evaluation.

Reads ~/.local/state/dl-ai/transcripts/*/*.jsonl (strictly outside the repository).
Writes ~/.local/state/dl-ai/benchmarks/router_gold/gold.json and review.md.
Contains NO personal data or real prompts in code.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dl_effort  # noqa: E402
import dl_mcp  # noqa: E402

DEFAULT_TRANSCRIPTS_DIR = Path.home() / ".local" / "state" / "dl-ai" / "transcripts"
DEFAULT_OUT_DIR = Path.home() / ".local" / "state" / "dl-ai" / "benchmarks" / "router_gold"

KEEP_SESSIONS = ("dl-ai-code",)
DROP_SESSION_PATTERNS = (
    "rayb-*",
    "bench*",
    "speech-latency*",
    "verify*",
    "smoke*",
    "ray-name-test*",
    "dl-ai-schedule",
)
DROP_ORIGINS = {"bench", "test"}

# Lightweight topic hints used ONLY to flag "?" rows where no MCP server was used
# in the transcript, so the human reviewer can inspect potential rule misses.
UNCERTAIN_MCP_HINTS: dict[str, tuple[str, ...]] = {
    "weather": ("weather", "forecast", "vrijeme", "prognoz", "kiša", "kisa", "temperature outside", "vani stupnj"),
    "zagreb": ("zagreb", "zet", "tramvaj", "ljekarn", "čistoća", "cistoca", "bajs", "nextbike", "smog", "klaićev"),
    "croatia_live": ("hak", "autocest", "granic", "tečaj", "tecaj", "hnb", "goriv", "eurosuper", "eurodizel", "nedjelj", "blagdan", "dhmz"),
    "homeassistant": ("svjetl", "lamp", "klima", "air con", "bambu", "3d print", "filament", "utičnic", "uticnic", "vlaga", "humidity", "home assistant", "purifier"),
    "phone": ("mobitel", "telefon", "phone", "battery", "baterij", "flashlight", "svjetiljk", "notifikac", "obavijest", "ekran", "zaslon", "2fa", "otp", "alarm", "slikaj", "uslikaj"),
    "pc_music": ("youtube music", "liked songs", "pusti pjesmu", "pusti glazbu", "sljedeća pjesma", "pauziraj glazbu", "play music", "next song", "now playing"),
    "proton": ("proton", "e-mail", "email", "mail", "pošta", "posta", "sandučić", "sanducic", "inbox"),
    "gmail": ("gmail", "google mail", "g-mail"),
    "drive": ("google drive", "gdrive", "spreadsheet", "google sheets", "tablic", "na drive"),
    "docs": ("google doc", "gdoc"),
    "schedule": ("remind", "reminder", "schedule", "podsjet", "zakaži", "zakazi", "svaki dan", "svako jutro"),
    "deepl": ("translat", "prevedi", "prijevod", "prevod", "na engleski", "na hrvatski", "na njemački"),
    "fetch": ("http://", "https://", "www."),
    "exa": ("search online", "search the web", "pretraži", "potraži na", "latest news", "vijesti"),
    "context7": ("context7", "official docs", "documentation for", "dokumentacija za"),
    "solidcraft": ("solidcraft", "3d model", "step file", "stl file", "parametric"),
    "ray_identity": ("who built you", "tko te napravio", "tvoj hardver", "your hardware", "zadnji commit", "git status"),
    "drones": ("drone", "dron", "dji", "ccaa", "easa", "amc portal"),
    "photovideo": ("davinci", "s-log", "d-log", "c-log", "lufs", "shutter speed", "color grading"),
    "electronics": ("resistor", "capacitor", "mosfet", "pcb", "esp32", "lcsc", "jlcpcb", "pinout"),
    "networking": ("sfp", "fiber optic", "rj45", "t568", "vlan", "mac address", "poe"),
    "minipaint": ("citadel", "vallejo", "warhammer", "airbrush", "slapchop", "nmm", "miniature"),
    "laws": ("zakon", "narodne novine", "pravilnik", "gdpr", "ai act", "eur-lex"),
    "print3d": ("klipper", "gcode", "g-code", "nozzle temp", "bed temp"),
    "wikipedia": ("wikipedia", "wikipedij"),
    "arxiv": ("arxiv", "preprint"),
    "osm": ("coordinates of", "geocode", "latitude", "longitude"),
}


def _session_allowed(name: str) -> bool:
    if any(fnmatch.fnmatch(name, pat) for pat in DROP_SESSION_PATTERNS):
        return False
    return name in KEEP_SESSIONS


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def stable_split(text: str) -> str:
    h = hashlib.sha256(_norm_text(text).encode("utf-8")).hexdigest()
    return "tune" if (int(h[:8], 16) % 2 == 0) else "test"


def _parse_thinking_notice(text: str) -> tuple[str | None, str]:
    """Parse 'Thinking: low for this answer, because ...' or 'Auto thinking: low (...)'."""
    m = re.match(r"^Thinking:\s*(off|none|low|medium|high)\b(.*)$", text)
    if m:
        lvl = "none" if m.group(1) == "off" else m.group(1)
        reason = m.group(2).strip()
        if reason.startswith("for this answer, because "):
            reason = reason[len("for this answer, because "):].rstrip(".")
        return lvl, reason
    m2 = re.match(r"^Auto thinking:\s*(off|none|low|medium|high)\s*\(([^)]+)\)", text)
    if m2:
        lvl = "none" if m2.group(1) == "off" else m2.group(1)
        return lvl, m2.group(2).strip()
    return None, ""


def _parse_mcp_notice(text: str) -> str | None:
    m = re.match(r"^MCP\s+\+([A-Za-z0-9_-]+)\b", text)
    return m.group(1) if m else None


def extract_records(
    transcripts_dir: Path = DEFAULT_TRANSCRIPTS_DIR,
    catalog_path: Path | None = None,
) -> list[dict]:
    if not transcripts_dir.is_dir():
        return []

    catalog, _, _ = dl_mcp.load_catalog(catalog_path)
    records: list[dict] = []
    seen_prompts: set[str] = set()

    for session_dir in sorted(transcripts_dir.iterdir()):
        if not session_dir.is_dir() or not _session_allowed(session_dir.name):
            continue

        events: list[tuple[str, dict]] = []
        for jf in sorted(session_dir.glob("*.jsonl")):
            day = jf.stem
            try:
                lines = jf.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    events.append((day, ev))

        last_reply = ""
        for idx, (day, ev) in enumerate(events):
            etype = ev.get("type")
            if etype == "cleared":
                last_reply = ""
                continue
            if etype != "user":
                continue

            raw_text = (ev.get("text") or "").strip()
            origin = str(ev.get("origin") or "").strip()
            voice = bool(ev.get("voice"))

            # Scan the turn up to the next user/cleared event first so last_reply updates cleanly
            # even when a prompt itself is skipped as a duplicate or slash command.
            j = idx + 1
            turn_text_parts: list[str] = []
            turn_thinking_chars = 0
            turn_stats: list[dict] = []
            mcp_called: set[str] = set()
            mcp_meta_enabled: set[str] = set()
            mcp_routed: set[str] = set()
            all_tools: list[str] = []
            effort_pick: str | None = None
            effort_reason = ""
            raised = False

            while j < len(events) and events[j][1].get("type") not in ("user", "cleared"):
                e2 = events[j][1]
                t2 = e2.get("type")
                if t2 == "text":
                    txt2 = e2.get("text") or ""
                    if txt2:
                        turn_text_parts.append(txt2)
                elif t2 == "thinking":
                    turn_thinking_chars += len(e2.get("text") or "")
                elif t2 == "stats":
                    turn_stats.append({
                        "tokens": int(e2.get("tokens") or 0),
                        "seconds": float(e2.get("seconds") or 0.0),
                        "rate": float(e2.get("rate") or 0.0),
                    })
                elif t2 == "notice":
                    nt = e2.get("text") or ""
                    if nt.startswith(("Thinking:", "Auto thinking:")):
                        lvl, rsn = _parse_thinking_notice(nt)
                        if lvl:
                            effort_pick, effort_reason = lvl, rsn
                    if "raised to high" in nt.lower():
                        raised = True
                    if nt.startswith("MCP +"):
                        srv = _parse_mcp_notice(nt)
                        if srv:
                            mcp_routed.add(srv)
                elif t2 == "tool_call":
                    fn = str(e2.get("name") or "")
                    if fn:
                        all_tools.append(fn)
                    if fn == "mcp":
                        args = e2.get("args") if isinstance(e2.get("args"), dict) else {}
                        if str(args.get("action") or "") == "enable":
                            raw_srv = args.get("server") or ""
                            parts = raw_srv if isinstance(raw_srv, list) else str(raw_srv).split(",")
                            for s in parts:
                                s = str(s).strip()
                                if s:
                                    mcp_meta_enabled.add(s)
                    elif "__" in fn:
                        mcp_called.add(fn.split("__", 1)[0])
                j += 1

            prev_reply = last_reply
            turn_reply = "".join(turn_text_parts).strip()
            if turn_reply:
                last_reply = turn_reply

            if origin in DROP_ORIGINS:
                continue
            if not raw_text or raw_text.startswith(("/", "!")):
                continue

            norm_key = _norm_text(raw_text)
            if norm_key in seen_prompts:
                continue
            seen_prompts.add(norm_key)

            mcp_needed = sorted(mcp_called | mcp_meta_enabled)
            # Flag "?" where no MCP server was used in the transcript, but current triggers
            # or bilingual domain hints suggest one may have been needed.
            mcp_candidates: list[str] = []
            if not mcp_needed:
                low = raw_text.lower()
                for srv_name, entry in catalog.items():
                    if entry.origins and origin and any(origin == o or origin.startswith(o + "-") for o in entry.origins):
                        # Origin alone is noisy (e.g. phone on every Android prompt); only suggest
                        # if prompt text also hints at it.
                        pass
                    if any(rx.search(raw_text) for rx in entry.unless):
                        continue
                    if any(rx.search(raw_text) for rx in entry.triggers):
                        mcp_candidates.append(srv_name)
                if not mcp_candidates:
                    for srv_name, cues in UNCERTAIN_MCP_HINTS.items():
                        if srv_name in catalog and any(c in low for c in cues):
                            mcp_candidates.append(srv_name)

            records.append({
                "id": f"g{len(records) + 1:04d}",
                "session": session_dir.name,
                "day": day,
                "ts": float(ev.get("ts") or 0.0),
                "text": raw_text,
                "origin": origin,
                "voice": voice,
                "last_reply": prev_reply[:1200],
                "split": stable_split(raw_text),
                "actual_effort_pick": effort_pick,
                "actual_effort_reason": effort_reason,
                "actual_raised": raised,
                "actual_mcp_called": sorted(mcp_called),
                "actual_mcp_meta_enabled": sorted(mcp_meta_enabled),
                "actual_mcp_needed": mcp_needed,
                "actual_mcp_routed": sorted(mcp_routed),
                "tool_call_count": len(all_tools),
                "has_tools": bool(all_tools),
                "thinking_chars": turn_thinking_chars,
                "reply_chars": len(turn_reply),
                "turn_stats": turn_stats,
                "mcp_candidates_uncertain": sorted(set(mcp_candidates)),
                # Ground truth fields (filled with proposed values initially; updated on review import)
                "gold_mcp": list(mcp_needed),
                "mcp_uncertain": bool(mcp_candidates and not mcp_needed),
                "gold_effort": None,
                "effort_sample": False,
                "effort_proposed": None,
                "effort_proposed_reason": "",
            })

    _propose_effort_sample(records, target_n=200)
    return records


def _propose_effort_level(rec: dict) -> tuple[str, str]:
    """Propose the lowest thinking level that would still give a good answer, plus a 1-line reason."""
    txt = rec["text"]
    voice = rec["voice"]
    last_reply = rec.get("last_reply") or ""
    rule_lvl, rule_reason = dl_effort.pick(txt, voice=voice, mode="act", last_reply=last_reply, semantic=False)

    if rec["actual_raised"]:
        return "high", "turn was raised mid-turn after failure"

    # Strong high indicators: code, error, >2 tool calls, or multi-step requests
    if rule_reason in ("code or error", "coding task", "follow-up on a failed answer"):
        return "high", f"coding/error/follow-up ({rule_reason})"
    if rec["tool_call_count"] >= 4:
        return "high", f"multi-step tool workflow ({rec['tool_call_count']} tool calls)"

    # Small talk / direct home or media commands -> none
    if rule_reason in ("small talk", "home command"):
        return "none", f"direct {rule_reason}"
    low = txt.lower()
    words = len(txt.split())
    if words <= 10 and any(w in low for w in ("pause", "skip", "next song", "pauziraj", "sljedeća", "flashlight", "svjetiljk")):
        return "none", "simple direct media or phone command"

    # Short lookups / weather / transit / single-fact questions -> low
    if rule_reason == "short question":
        return "low", "short direct question"
    if words <= 18 and not rec["has_tools"] and "?" in txt and rule_lvl == "high":
        return "low", "short question without coding/multi-step work"

    # Explanations / comparisons / translations -> medium
    if rule_reason == "explanation":
        return "medium", "explanation, summary, comparison, or translation"
    if rec["tool_call_count"] in (1, 2, 3) and words <= 35:
        return "medium", f"moderate request using {rec['tool_call_count']} tool call(s)"

    if rule_lvl == "high" and words <= 25 and not rec["has_tools"]:
        return "medium", "short/medium non-tool prompt (review if low/medium suffices)"
    return rule_lvl, f"from turn context ({rule_reason})"


def _propose_effort_sample(records: list[dict], target_n: int = 200) -> None:
    """Select a deterministic stratified sample (~200) for human thinking-level review."""
    if not records:
        return
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        lvl, rsn = _propose_effort_level(rec)
        rec["effort_proposed"] = lvl
        rec["effort_proposed_reason"] = rsn
        key = (
            bool(rec["voice"]),
            rec["actual_effort_pick"] or "unrecorded",
            bool(rec["has_tools"]),
        )
        strata[key].append(rec)

    total = len(records)
    n = min(target_n, total)
    chosen_ids: set[str] = set()

    # Proportional allocation with floor >= 1 per stratum
    remainders: list[tuple[float, tuple, list[dict]]] = []
    for key, items in sorted(strata.items()):
        exact = (len(items) / total) * n
        take = min(len(items), max(1, int(exact)))
        # Deterministic spacing across chronological order
        step = len(items) / take
        for i in range(take):
            chosen_ids.add(items[int(i * step)]["id"])
        remainders.append((exact - take, key, items))

    # Top up or trim to hit target_n cleanly
    if len(chosen_ids) < n:
        for _, _, items in sorted(remainders, key=lambda x: -x[0]):
            for item in items:
                if len(chosen_ids) >= n:
                    break
                if item["id"] not in chosen_ids:
                    chosen_ids.add(item["id"])
            if len(chosen_ids) >= n:
                break

    for rec in records:
        if rec["id"] in chosen_ids:
            rec["effort_sample"] = True


def _md_cell(s: str, limit: int = 160) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s.replace("|", "\\|")


def render_review_md(records: list[dict]) -> str:
    effort_rows = [r for r in records if r["effort_sample"]]
    mcp_uncertain_rows = [r for r in records if r["mcp_uncertain"]]
    mcp_used_rows = [r for r in records if r["actual_mcp_needed"]]
    mcp_clear_none = [r for r in records if not r["actual_mcp_needed"] and not r["mcp_uncertain"]]

    lines = [
        "# Router Gold Label Review (Private)",
        "",
        "This file stays strictly outside the repository (`~/.local/state/dl-ai/benchmarks/router_gold/review.md`).",
        f"Total deduplicated real prompts: **{len(records)}** "
        f"(`tune`: {sum(1 for r in records if r['split'] == 'tune')}, "
        f"`test`: {sum(1 for r in records if r['split'] == 'test')}).",
        "",
        "## Bias note",
        "- `actual_mcp_needed` reflects servers that were actually called or enabled via the `mcp` tool during the real turn.",
        "- Because the rule router turned servers on before those turns, rows with servers used lean toward what the rules already matched.",
        "- Rows marked `?` below flag turns where **no** MCP server was used, yet triggers/hints suggest one may have been needed.",
        "",
        "## How to review (Gate 1)",
        "1. **Thinking level table (~200 rows):** Check every row. Put `✓` in **Your verdict** to accept the proposed level, or write `none`, `low`, `medium`, or `high`.",
        "2. **MCP servers:** Check every `?` row (put `✓` or the comma-separated server list, or `none`), and skim the used-server rows if you disagree with any.",
        "3. After editing this file, run:",
        "   `python3 tools/router_gold.py --import-review`",
        "",
        f"## 1. Thinking Level Sample ({len(effort_rows)} prompts)",
        "",
        "| ID | Split | Voice | Current | Tools | Prompt | Proposed | Reason | Your verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in effort_rows:
        cur = r["actual_effort_pick"] or "-"
        if r["actual_raised"]:
            cur += " (raised)"
        lines.append(
            f"| {r['id']} | {r['split']} | {'yes' if r['voice'] else 'no'} | {cur} | "
            f"{'yes' if r['has_tools'] else 'no'} | {_md_cell(r['text'], 140)} | "
            f"**{r['effort_proposed']}** | {_md_cell(r['effort_proposed_reason'], 80)} |  |"
        )

    lines += [
        "",
        f"## 2a. MCP Servers — Uncertain `?` Rows ({len(mcp_uncertain_rows)} prompts where none was used, check these)",
        "",
        "| ID | Split | Origin | Prompt | Proposed MCP | Your verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in mcp_uncertain_rows:
        orig = "ray-android" if r["origin"].startswith("ray-android") else ("web" if r["origin"] else "-")
        prop = ", ".join(r["mcp_candidates_uncertain"]) + " ?"
        lines.append(
            f"| {r['id']} | {r['split']} | {orig} | {_md_cell(r['text'], 160)} | {prop} |  |"
        )

    lines += [
        "",
        f"## 2b. MCP Servers — Used in Transcript ({len(mcp_used_rows)} prompts, skim for disagreements)",
        "",
        "| ID | Split | Origin | Prompt | Used MCP (called / meta) | Your verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in mcp_used_rows:
        orig = "ray-android" if r["origin"].startswith("ray-android") else ("web" if r["origin"] else "-")
        used = ", ".join(r["actual_mcp_needed"])
        lines.append(
            f"| {r['id']} | {r['split']} | {orig} | {_md_cell(r['text'], 160)} | {used} |  |"
        )

    lines += [
        "",
        f"## 2c. MCP Servers — No Server Used & No Hint Matched ({len(mcp_clear_none)} prompts)",
        "",
        "| ID | Split | Origin | Prompt | Proposed MCP | Your verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in mcp_clear_none:
        orig = "ray-android" if r["origin"].startswith("ray-android") else ("web" if r["origin"] else "-")
        lines.append(
            f"| {r['id']} | {r['split']} | {orig} | {_md_cell(r['text'], 160)} | none |  |"
        )

    return "\n".join(lines) + "\n"


def import_review(gold_path: Path, review_path: Path) -> tuple[int, int]:
    """Parse user verdicts from review.md back into gold.json. Returns (effort_updated, mcp_updated)."""
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in data["records"]}
    eff_updated = 0
    mcp_updated = 0
    section = ""

    for line in review_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 1. Thinking Level"):
            section = "effort"
            continue
        if line.startswith("## 2"):
            section = "mcp"
            continue
        if not line.startswith("| g"):
            continue
        # Split on unescaped pipes
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        rid = cells[0]
        rec = by_id.get(rid)
        if not rec:
            continue
        verdict = cells[-1].strip() if cells else ""
        if not verdict:
            continue
        if section == "effort":
            v = verdict.lower()
            if v in ("✓", "ok", "yes"):
                rec["gold_effort"] = rec["effort_proposed"]
                eff_updated += 1
            elif v in ("none", "low", "medium", "high"):
                rec["gold_effort"] = v
                eff_updated += 1
        elif section == "mcp":
            v = verdict.lower()
            if v in ("✓", "ok", "yes"):
                if rec["mcp_uncertain"] and rec["mcp_candidates_uncertain"]:
                    rec["gold_mcp"] = list(rec["mcp_candidates_uncertain"])
                else:
                    rec["gold_mcp"] = list(rec["actual_mcp_needed"])
                rec["mcp_uncertain"] = False
                mcp_updated += 1
            elif v in ("none", "-", "no"):
                rec["gold_mcp"] = []
                rec["mcp_uncertain"] = False
                mcp_updated += 1
            else:
                servers = [s.strip() for s in re.split(r"[,;\s]+", verdict) if s.strip() and s.strip() != "?"]
                rec["gold_mcp"] = sorted(set(servers))
                rec["mcp_uncertain"] = False
                mcp_updated += 1

    data["reviewed"] = True
    _write_private(gold_path, json.dumps(data, indent=2, ensure_ascii=False))
    return eff_updated, mcp_updated


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            os.chmod(tmp_path, 0o600)
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def summarize(records: list[dict]) -> dict:
    by_split = Counter(r["split"] for r in records)
    effort_sample = [r for r in records if r["effort_sample"]]
    effort_dist = Counter(r["effort_proposed"] for r in effort_sample)
    mcp_uncertain = sum(1 for r in records if r["mcp_uncertain"])
    mcp_used = sum(1 for r in records if r["actual_mcp_needed"])
    return {
        "total": len(records),
        "splits": dict(by_split),
        "voice_true": sum(1 for r in records if r["voice"]),
        "effort_sample": len(effort_sample),
        "effort_proposed_dist": dict(effort_dist),
        "mcp_used_rows": mcp_used,
        "mcp_uncertain_rows": mcp_uncertain,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build or import private gold router benchmark set.")
    ap.add_argument("--transcripts-dir", type=Path, default=DEFAULT_TRANSCRIPTS_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--catalog", type=Path, default=None)
    ap.add_argument("--import-review", action="store_true", help="Import edited review.md verdicts into gold.json")
    ap.add_argument("--stats", action="store_true", help="Print aggregate counts only (no prompt text)")
    args = ap.parse_args(argv)

    gold_path = args.out_dir / "gold.json"
    review_path = args.out_dir / "review.md"

    if args.stats:
        if not gold_path.is_file():
            print(json.dumps({"error": f"{gold_path} not found"}))
            return 1
        data = json.loads(gold_path.read_text(encoding="utf-8"))
        out = dict(summarize(data.get("records", [])))
        out["reviewed"] = bool(data.get("reviewed", False))
        print(json.dumps(out, indent=2))
        return 0

    if args.import_review:
        eff_n, mcp_n = import_review(gold_path, review_path)
        updated = json.loads(gold_path.read_text(encoding="utf-8"))
        recs = updated.get("records", [])
        unrev_eff = sum(1 for r in recs if r.get("effort_sample") and not r.get("gold_effort"))
        unrev_mcp = sum(1 for r in recs if r.get("mcp_uncertain"))
        print(json.dumps({
            "effort_updated": eff_n,
            "mcp_updated": mcp_n,
            "unreviewed_effort_sample": unrev_eff,
            "unreviewed_mcp_uncertain": unrev_mcp,
        }, indent=2))
        return 0

    records = extract_records(args.transcripts_dir, args.catalog)
    summary = summarize(records)
    payload = {"reviewed": False, "summary": summary, "records": records}
    _write_private(gold_path, json.dumps(payload, indent=2, ensure_ascii=False))
    _write_private(review_path, render_review_md(records))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
