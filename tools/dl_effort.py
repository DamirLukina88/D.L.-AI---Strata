"""dl_effort.py - Rule-based thinking level selection and mid-turn escalation for /effort auto."""
from __future__ import annotations

import json
import os
import re

if __package__ == "tools":
    from tools import dl_effort_scorer, dl_router
else:
    try:
        import dl_effort_scorer
    except ImportError:
        try:
            from tools import dl_effort_scorer
        except ImportError:
            dl_effort_scorer = None
    try:
        import dl_router
    except ImportError:
        try:
            from tools import dl_router
        except ImportError:
            dl_router = None

CODE_HINTS = ("```", "traceback", "error:", "exception", "exit code", "exited with code")
CODING_VERBS = (
    "fix", "fixing", "fixes", "fixed", "debug", "debugging", "refactor", "refactoring",
    "implement", "implementing", "build", "building",
    "write a script", "write a function", "write a test", "write tests",
    "optimize", "optimise", "optimizing", "review", "reviewing",
    "migrate", "migrating", "design", "designing", "plan", "planning",
    "why does", "why doesn't", "why doesnt",
)
EDIT_VERBS = (
    "change", "changing", "edit", "editing", "update", "updating",
    "add", "adding", "remove", "removing", "delete", "deleting",
    "replace", "replacing", "rename", "renaming",
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
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
CODE_FILE_RE = re.compile(
    r"(?<![:/@\w])[A-Za-z0-9_][\w./-]*\.(?:py|js|ts|jsx|tsx|html|css|c|cc|cpp|h|hpp|cu|hip|rs|go|sh|json|ya?ml|toml|sql)\b",
    re.I,
)
EXIT_CODE_RE = re.compile(r"\[Command exited with code (-?\d+)\]")
# A picture, recording or PDF attached to a prompt says nothing about how hard the request is: the thinking level
# follows the words (audit 2026-11-15: every attached photo was "code or error" -> high).  dl_cli.py's resolver uses
# the same extensions (IMAGE_/VIDEO_/AUDIO_/PDF_EXTENSIONS there).
MEDIA_EXTENSIONS = frozenset(
    ".jpg .jpeg .png .webp .bmp .gif .tiff .tif .avif .ppm .pgm .pbm .pnm .ico .tga .heic .heif "
    ".mp4 .mov .mkv .webm .avi .m4v .wav .mp3 .m4a .ogg .flac .aac .opus .pdf".split())
MEDIA_REF_RE = re.compile(r"(?:^|(?<=\s))@([\w./-]+)")
MEDIA_MARK_RE = re.compile(r"\[(?:Attached image|Image|Video|PDF|Audio|Photo)[^\]]*\]", re.I)


def strip_media(prompt: str) -> tuple[str, bool]:
    """(the prompt without attached media references, whether there were any).  `@notes.txt` and `@app.py` stay."""
    had = False

    def drop(m: re.Match) -> str:
        nonlocal had
        if os.path.splitext(m.group(1).lower())[1] in MEDIA_EXTENSIONS:
            had = True
            return ""
        return m.group(0)
    out = MEDIA_REF_RE.sub(drop, prompt or "")
    out, n = MEDIA_MARK_RE.subn("", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip(), had or n > 0

BUDGET_TIERS: dict[str, int] = {
    "none": 0,
    "low": 1024,
    "medium": 2048,
    "high": 4096,
}


# what may be left of a small-talk prompt besides the greetings, phrases and Ray's names ("to my friend Nikolayna please")
SMALL_TALK_FILLER = frozenset("please to my friend friends and you your me us there again today all everyone nice meet "
                              "so oh ok okay the a what do doing up is it going".split())


def is_small_talk(prompt: str, *, voice: bool = False, last_reply: str = "") -> bool:
    """Small talk and nothing else, for the coding agent's small-talk guard: pick() says small talk, and once the
    greetings, small-talk phrases, Ray's names and filler words are taken out, at most one word is left (a friend's
    name, or "Ring" for Ray).  "Hello Ray, check the printer" is small talk to pick() (for the thinking level) but a
    request here, so its tools still run."""
    if pick(prompt, voice=voice, last_reply=last_reply, semantic=False, router_mode="rules")[1] != "small talk":
        return False
    rest = (prompt or "").lower()
    for phrase in sorted(SMALL_TALK, key=len, reverse=True):
        rest = re.sub(rf"\b{re.escape(phrase)}\b", " ", rest)
    left = [w for w in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", rest) if w not in RAY_NAMES and w not in SMALL_TALK_FILLER]
    return len(left) <= 1


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


def _resolve_router_mode(router_mode: str | None = None, semantic: bool | None = None) -> str:
    if semantic is False:
        return "rules"
    if router_mode is not None:
        if dl_router is not None:
            return dl_router.router_mode(router_mode, subsystem="effort")
        m = str(router_mode).strip().lower()
        return m if m in ("rules", "model2vec", "hybrid") else "rules"
    if semantic is True:
        return "hybrid"
    if dl_router is not None:
        return dl_router.router_mode(subsystem="effort")
    for key in ("DL_EFFORT_ROUTER_MODE", "DL_ROUTER_MODE"):
        v = os.environ.get(key, "").strip().lower()
        if v:
            return v if v in ("rules", "model2vec", "hybrid") else "rules"
    legacy = os.environ.get("DL_SEMANTIC_ROUTER", "").strip().lower()
    return "hybrid" if legacy in ("1", "true", "yes", "on") else "rules"



def pick(
    prompt: str,
    *,
    voice: bool = False,
    mode: str = "act",
    last_reply: str = "",
    semantic: bool | None = None,
    router_mode: str | None = None,
) -> tuple[str, str]:
    """Pick (level, reason) for a prompt across rules, model2vec, or hybrid mode."""
    if mode == "plan":
        return "high", "plan mode"

    raw, had_media = strip_media((prompt or "").strip())
    if had_media and not raw:
        return "low", "picture only"
    effective_mode = _resolve_router_mode(router_mode=router_mode, semantic=semantic)

    if effective_mode == "model2vec" and dl_effort_scorer is not None:
        m2v_ready = dl_router is not None and dl_router.is_available()
        if m2v_ready:
            try:
                s_lvl, _s_conf = dl_effort_scorer.predict(raw)
                if s_lvl in ("none", "low", "medium", "high"):
                    return s_lvl, f"model2vec {s_lvl}"
            except Exception:
                pass
        # If Model2Vec is unavailable, fall back cleanly to rules below.

    low = raw.lower()
    words = len(raw.split())
    v_slack = 6 if voice else 0

    no_urls = URL_RE.sub("", raw)
    if AT_FILE_RE.search(raw) or CODE_FILE_RE.search(no_urls) or any(h in low for h in CODE_HINTS):
        return "high", "code or error"
    if _has_any(raw, CODING_VERBS) or (_has_any(raw, EDIT_VERBS) and _has_any(raw, CODE_WORDS)):
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

    # Without Model2Vec, hybrid is rules: the CRC32 n-gram fallback in dl_effort_scorer was never tuned for the 0.55
    # gate, and the notice tells the user "using rules" (is_available() queues it once).
    if (effective_mode == "hybrid" and dl_effort_scorer is not None
            and dl_router is not None and dl_router.is_available()):
        try:
            s_lvl, _s_conf = dl_effort_scorer.predict(raw)
            if s_lvl in ("none", "low", "medium"):
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


# What the user reads (Code tab, terminal): when and why the level was chosen or changed.  The reason codes above stay
# short and fixed (tests and the stats use them); these say the same in plain words.
LEVEL_WORDS = {"none": "off", "low": "low", "medium": "medium", "high": "high"}
PICK_WHY = {
    "plan mode": "Plan Mode is on",
    "code or error": "the prompt has code, an error message or a file in it",
    "picture only": "the prompt is an attached picture or file with no words to weigh",
    "coding task": "the prompt asks for coding work",
    "follow-up on a failed answer": "it follows up on an answer that did not work",
    "small talk": "it is small talk",
    "home command": "it is a smart-home command",
    "explanation": "it asks for an explanation",
    "short question": "it is a short question",
    "default": "no lighter level fits it",
}
RAISE_WHY = {
    "tool error": "a tool returned an error",
    "command failed": "a command ended with an error code",
    "repeated tool call": "the same tool call was made twice",
    "thinking loop": "the thinking was going in circles",
    "tool call sent as text": "a tool call came back as plain text",
    "sent back by the finish checks": "the finish checks sent the work back",
}


def pick_why(reason: str) -> str:
    if reason in PICK_WHY:
        return PICK_WHY[reason]
    if reason.startswith(("semantic ", "model2vec ")):
        return f"the prompt classifier rated it {reason.split()[-1]}"
    return reason


def describe_pick(level: str, reason: str, budget: int = 0) -> str:
    """'Thinking: low for this answer, because it is a short question (up to 1,024 thinking tokens).'"""
    why = pick_why(reason)
    cap = f" (up to {budget:,} thinking tokens)" if budget and level != "none" else ""
    msg = f"Thinking: {LEVEL_WORDS.get(level, level)} for this answer, because {why}{cap}."
    if dl_router is not None:
        fb = dl_router.consume_fallback_notice()
        if fb:
            msg = f"{fb}\n{msg}"
    return msg


def describe_raise(reason: str) -> str:
    """'Thinking raised to high for the rest of this answer, because a command ended with an error code.'"""
    return f"Thinking raised to high for the rest of this answer, because {RAISE_WHY.get(reason, reason)}."
