"""dl_effort.py - Rule-based thinking level selection and mid-turn escalation for /effort auto."""
from __future__ import annotations

import json
import os
import re

try:
    from tools import dl_effort_scorer
except ImportError:
    try:
        import dl_effort_scorer
    except ImportError:
        dl_effort_scorer = None

CODE_HINTS = ("```", "traceback", "error:", "exception", "exit code", "exited with code")
CODING_VERBS = (
    "fix", "fixing", "fixes", "fixed", "debug", "debugging", "refactor", "refactoring",
    "implement", "implementing", "build", "building",
    "write a script", "write a function", "write a test", "write tests",
    "optimize", "optimise", "optimizing", "review", "reviewing",
    "migrate", "migrating", "design", "designing", "plan", "planning",
    "why does", "why doesn't", "why doesnt",
)
COMPLAINTS = ("that's wrong", "thats wrong", "didn't work", "didnt work", "doesn't work", "doesnt work", "still", "why?")
SMALL_TALK = (
    "hi", "hello", "hey", "thanks", "thank you", "good morning", "good afternoon", "good evening",
    "how are you", "introduce yourself", "what can you do", "who are you",
)
SMALL_TALK_QUESTIONS = ("how are you", "what can you do", "who are you")
RAY_NAMES = ("ray", "rey", "rae", "wray")
HOME_VERBS = ("turn on", "turn off", "switch", "dim", "set", "open", "close")
HOME_NOUNS = ("light", "lights", "lamp", "lamps", "ac", "air conditioner", "plug", "plugs", "printer", "printers", "camera", "cameras")
EXPLAIN_WORDS = ("explain", "summarize", "summarise", "compare", "translate", "what is")
QUESTION_STARTERS = ("what", "what's", "whats", "who", "when", "where", "which", "how", "is", "are", "can", "could", "would", "do", "does", "did")
CODE_WORDS = (
    "code", "function", "class", "method", "variable", "script", "repo", "file", "test", "tests",
    "debug", "compile", "syntax", "git", "python", "javascript", "cpp", "c++", "html", "css", "sql",
    "bug", "patch", "diff",
)
AT_FILE_RE = re.compile(r"(?:^|\s)@[\w./-]+")
EXIT_CODE_RE = re.compile(r"\[Command exited with code (-?\d+)\]")

BUDGET_TIERS: dict[str, int] = {
    "none": 0,
    "low": 1024,
    "medium": 2048,
    "high": 4096,
}


def budget_for(level: str, custom_caps: dict[str, int] | None = None) -> int:
    """Return maximum thinking tokens allocated for this effort level (0: no budget / uncapped)."""
    caps = custom_caps if custom_caps is not None else BUDGET_TIERS
    return caps.get(level, 4096)


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    for p in phrases:
        pat = rf"(?:^|(?<=\s))\b{re.escape(p)}(?=$|\s|[.,!?;:])" if not p[-1].isalnum() else rf"\b{re.escape(p)}\b"
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _semantic_enabled() -> bool:
    v = os.environ.get("DL_SEMANTIC_ROUTER", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def pick(prompt: str, *, voice: bool = False, mode: str = "act", last_reply: str = "", semantic: bool | None = None) -> tuple[str, str]:
    """Pick (level, reason) for a prompt with rules and optional semantic routing. Matching is case-insensitive on raw prompt."""
    if mode == "plan":
        return "high", "plan mode"

    raw = (prompt or "").strip()
    low = raw.lower()
    words = len(raw.split())
    v_slack = 6 if voice else 0

    if AT_FILE_RE.search(raw) or any(h in low for h in CODE_HINTS):
        return "high", "code or error"
    if _has_any(raw, CODING_VERBS):
        return "high", "coding task"

    is_home = _has_any(raw, HOME_VERBS) and _has_any(raw, HOME_NOUNS)
    is_explain = _has_any(raw, EXPLAIN_WORDS)
    first_word = low.split()[0].rstrip(".,!?;:") if low else ""
    is_question = raw.endswith("?") or first_word in QUESTION_STARTERS

    if last_reply and last_reply.strip() and words <= 15 + v_slack and not is_home and not is_explain:
        if _has_any(raw, COMPLAINTS[:-1]) or low.rstrip().endswith("why?") or low == "why":
            return "high", "follow-up on a failed answer"

    bare_words = tuple(w.strip(".,!?;:") for w in low.split())
    if words <= 12 + v_slack and not is_home and not is_explain:
        if (_has_any(raw, SMALL_TALK) or (bare_words and all(w in RAY_NAMES or w in ("hi", "hello", "hey") for w in bare_words))):
            if not is_question or _has_any(raw, SMALL_TALK_QUESTIONS) or all(w in RAY_NAMES or w in ("hi", "hello", "hey") for w in bare_words):
                return "none", "small talk"

    if words <= 20 + v_slack and is_home:
        return "none", "home command"

    has_code = _has_any(raw, CODE_WORDS)
    if words <= 60 + (15 if voice else 0) and not has_code and is_explain:
        return "medium", "explanation"
    if words <= 20 + v_slack and not has_code and is_question:
        return "low", "short question"

    use_semantic = _semantic_enabled() if semantic is None else semantic
    if use_semantic and dl_effort_scorer is not None:
        try:
            s_lvl, s_conf = dl_effort_scorer.predict(raw)
            if s_conf >= 0.70 and s_lvl in ("none", "low", "medium"):
                return s_lvl, f"semantic {s_lvl}"
        except Exception:
            pass

    return "high", "default"


def raise_reason(fn_name: str, args: dict | None, result: str, seen: set[tuple[str, str]]) -> str | None:
    """Return escalation reason if tool failed, command exited non-zero, or call was repeated."""
    txt = (result or "").lstrip()
    if txt.startswith("Error"):
        return "tool error"
    m = EXIT_CODE_RE.search(txt)
    if m and m.group(1) != "0":
        return "command failed"
    call_sig = (fn_name, json.dumps(args or {}, sort_keys=True))
    if call_sig in seen:
        return "repeated tool call"
    seen.add(call_sig)
    return None
