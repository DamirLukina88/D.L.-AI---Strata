#!/usr/bin/env python3
"""Automatic thinking-level (reasoning_effort) selection and mid-turn escalation for D.L.

Implements the opt-in `/effort auto` policy documented in `wiki/decisions/auto-thinking-level.md`:
  1. Per-turn initial classification (`resolve_turn`) in sub-millisecond deterministic Python,
     biased upward toward `high` whenever a prompt touches code, files, errors, workspace tools,
     or multi-step instructions.
  2. One-way mid-turn escalation (`check_tool_result_failure`, `should_escalate`) inside
     `execute_agent_loop` so any turn that starts below `high` escalates to `high` for the
     remaining iterations if a tool call fails, repeats, or triggers a retry guard.
"""

from __future__ import annotations

import re

VALID_EFFORTS = ("none", "low", "medium", "high", "auto")
CONCRETE_EFFORTS = ("none", "low", "medium", "high")

# Wake words / assistant names (including common Whisper STT transcriptions of "Ray")
_WAKE_WORDS = r"(?:ray|rey|rae|wray|ring|assistant|ai)"

# Rule 1: Explicit deep-thinking cues
_EXPLICIT_HIGH_RE = re.compile(
    r"\b(?:"
    r"think\s+(?:hard|carefully|deeply|through|step\s+by\s+step)|"
    r"step[-\s]by[-\s]step|"
    r"careful(?:ly)?\s+plan|"
    r"in\s+detail|"
    r"thorough(?:ly)?\s+(?:analyze|analize|check|review|investigate)|"
    r"deep\s+dive"
    r")\b",
    re.IGNORECASE,
)

# Rule 2: Explicit no-thinking cues
_EXPLICIT_NONE_RE = re.compile(
    r"(?:^|\s)/no_?think\b|\b(?:no\s+thinking|without\s+thinking|don'?t\s+think|skip\s+thinking)\b",
    re.IGNORECASE,
)

# Rule 3a: Code fences, stack traces, diffs, @file mentions, and file paths / extensions
_CODE_OR_PATH_RE = re.compile(
    r"```|"
    r"Traceback\s+\(most\s+recent\s+call\s+last\):|"
    r"\b(?:SyntaxError|TypeError|ValueError|RuntimeError|KeyError|AttributeError|ImportError|OSError|Segmentation\s+fault)\b|"
    r"^diff\s+--git\b|^@@\s+-\d+|"
    r"(?:^|\s)@[A-Za-z0-9_./-]+|"
    r"(?:^|[\s`'\"(])(?:\./|\.\./|~/|/home/|/mnt/|/etc/|/tmp/|/var/|src/|serve/|tools/|include/|docs/|wiki/|bench/|tests?/)[A-Za-z0-9_./-]+|"
    r"\b[A-Za-z0-9_-]+\.(?:py|cpp|cc|c|cu|h|hpp|cuh|js|ts|tsx|jsx|css|html|json|jsonl|yaml|yml|toml|sh|bat|ps1|md|sql|rs|go|java| solidcraft)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Rule 3b: Engineering, coding, debugging, and workspace action verbs/phrases
_ENGINEERING_RE = re.compile(
    r"\b(?:"
    r"implement(?:ing|ed|s)?|"
    r"refactor(?:ing|ed|s)?|"
    r"debug(?:ging|ged|s)?|"
    r"fix(?:ing|ed|es)?|"
    r"optimi[zs](?:e|ing|ed|ation)|"
    r"benchmark(?:ing|ed|s)?|"
    r"compil(?:e|ing|ed)|"
    r"build(?:ing)?|"
    r"port(?:ing|ed)?|"
    r"patch(?:ing|ed)?|"
    r"unit\s+tests?|"
    r"write\s+(?:a\s+)?(?:test|script|function|class|module|code|program|tool)|"
    r"create\s+(?:a\s+)?(?:file|script|function|class|module|plan|test|tool)|"
    r"edit(?:ing)?|modify(?:ing)?|update\s+the\s+(?:code|file|repo|wiki|server|engine|config|test)|"
    r"investigat(?:e|ing)|"
    r"audit(?:ing)?|"
    r"analy[zs](?:e|ing)|"
    r"review\s+(?:the\s+)?(?:code|pr|commit|diff|changes|repo)|"
    r"commit|cherry-pick|merge|rebase|git\s+(?:status|diff|log|show|apply|checkout|branch)|"
    r"cmake|systemctl|journalctl|pytest|unittest|"
    r"check\s+the\s+(?:repo|code|wiki|logs|server|files?|tests?|status)|"
    r"search\s+the\s+(?:repo|code|wiki|files?|web)|"
    r"read\s+the\s+(?:file|code|wiki|docs|logs)"
    r")\b",
    re.IGNORECASE,
)

# Rule 4: Short follow-up correction / complaint after an assistant or tool turn
_FOLLOWUP_COMPLAINT_RE = re.compile(
    r"^(?:no\b|wait\b|hold\s+on\b|actually\b)?[,:\s]*(?:"
    r"why\b|"
    r"try\s+again\b|"
    r"still\s+(?:broken|failing|wrong|not\s+working|doesn'?t\s+work|does\s+not\s+work)|"
    r"(?:that\s+|it\s+)?(?:didn'?t|did\s+not|doesn'?t|does\s+not)\s+work|"
    r"(?:that'?s|it'?s|this\s+is)\s+(?:wrong|incorrect|broken|not\s+right|not\s+what\s+i\s+asked)|"
    r"that\s+failed|"
    r"not\s+working|"
    r"fix\s+(?:that|it|this)"
    r")\b",
    re.IGNORECASE,
)

# Rule 5a: Pure greetings, small talk, wake-word checks, and brief acknowledgements
_GREETING_ATOM = (
    r"(?:"
    rf"{_WAKE_WORDS}|"
    r"hi|hello|hey|yo|sup|howdy|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"how\s+are\s+you(?:\s+doing)?(?:\s+today)?|"
    r"how'?s\s+it\s+going|"
    r"what'?s\s+up|"
    r"are\s+you\s+(?:there|awake|ready|listening)|"
    r"can\s+you\s+hear\s+me|"
    r"test(?:ing)?(?:\s+1\s*2\s*3)?|ping|"
    r"thanks(?:\s+a\s+lot|\s+so\s+much)?|thank\s+you(?:\s+very\s+much|\s+so\s+much)?|thx|ty|"
    r"ok|okay|k|kk|got\s+it|understood|makes\s+sense|cool|nice|great|awesome|perfect|sounds\s+good|all\s+good|"
    r"yes|yep|yeah|nope|nah|"
    r"bye|goodbye|see\s+(?:ya|you)(?:\s+later)?|good\s*night|"
    r"stop|cancel|never\s*mind|forget\s+it"
    r")"
)
_GREETING_OR_ACK_RE = re.compile(
    rf"^{_GREETING_ATOM}(?:[,!?.:\s]+{_GREETING_ATOM})*[.!?\s]*$",
    re.IGNORECASE,
)

# Bare wake word alone (e.g. "Ray?", "Hey Ray!")
_BARE_WAKE_RE = re.compile(
    rf"^(?:hey|hi|hello|yo|ok|okay)?[,!.\s]*{_WAKE_WORDS}[.!?\s]*$",
    re.IGNORECASE,
)

# Rule 5b: Direct smart-home, device, media, clock, or timer one-liners
_SMART_HOME_OR_CLOCK_RE = re.compile(
    r"\b(?:"
    r"turn\s+(?:on|off)|switch\s+(?:on|off)|toggle|"
    r"(?:dim|brighten)\s+the\s+lights?|"
    r"set\s+(?:the\s+)?(?:brightness|temperature|thermostat|ac|air\s+conditioner|heat|heater|fan|volume)|"
    r"(?:open|close)\s+the\s+(?:blinds|curtains|shades|garage)|"
    r"(?:lock|unlock)\s+the\s+(?:door|front\s+door|back\s+door)|"
    r"(?:living\s+room|bedroom|kitchen|bathroom|hallway|desk|office|ceiling|strip)\s+(?:lights?|lamps?|bulbs?|ac|fan|tv|plug|switch)|"
    r"all\s+(?:the\s+)?lights?\s+(?:on|off)|"
    r"lights?\s+(?:on|off)|"
    r"set\s+(?:a\s+|an\s+)?(?:timer|alarm|reminder)\s+for|"
    r"wake\s+me\s+up\s+at|"
    r"what\s+time\s+is\s+it|what'?s\s+the\s+time|"
    r"what\s+(?:is\s+today'?s\s+date|day\s+is\s+it|is\s+the\s+date)|"
    r"(?:pause|resume|mute|unmute|stop|skip)\s+(?:the\s+)?(?:music|song|track|playback|tv|media)|"
    r"volume\s+(?:up|down|to\s+\d+)"
    r")\b",
    re.IGNORECASE,
)

# Rule 6: Conceptual explanation / comparison / overview queries
_CONCEPTUAL_RE = re.compile(
    r"\b(?:"
    r"explain(?:\s+to\s+me|\s+briefly|\s+simply)?|"
    r"how\s+does\s+.+\s+work|"
    r"how\s+do\s+.+\s+work|"
    r"why\s+does\s+|why\s+do\s+|why\s+is\s+|"
    r"what\s+is\s+the\s+difference\s+between|"
    r"what'?s\s+the\s+difference\s+between|"
    r"compare\s+.+\s+(?:and|vs\.?|versus|with)|"
    r"pros\s+and\s+cons\s+of|"
    r"trade-?offs?\s+(?:of|between)|"
    r"summarize|summary\s+of|overview\s+of|"
    r"walk\s+me\s+through|teach\s+me\s+about"
    r")\b",
    re.IGNORECASE,
)

# Rule 7: Short factual / definition / conversion queries
_FACTUAL_STARTER_RE = re.compile(
    rf"^(?:{_WAKE_WORDS}[,!.\s]+)*"
    r"(?:"
    r"what\s+(?:is|are|was|were)\b|"
    r"what'?s\b|"
    r"who\s+(?:is|are|was|were|wrote|invented|discovered|painted|directed)\b|"
    r"when\s+(?:is|was|did|were)\b|"
    r"where\s+(?:is|are|was)\b|"
    r"how\s+(?:many|much|old|tall|far|long|big|fast|high|deep)\b|"
    r"which\s+(?:country|city|planet|language|element|animal|year)\b|"
    r"convert\s+\d+|"
    r"define\s+\w+|"
    r"capital\s+of\b|"
    r"meaning\s+of\b|"
    r"translate\b"
    r")",
    re.IGNORECASE,
)

_NONZERO_EXIT_RE = re.compile(r"\[Command exited with code (-?\d+)\]")


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _has_prior_turn(messages: list[dict] | None) -> bool:
    if not messages:
        return False
    for m in messages:
        if isinstance(m, dict) and m.get("role") in ("assistant", "tool"):
            return True
    return False


def resolve_turn(
    text: str,
    *,
    voice: bool = False,
    mode: str = "act",
    plan_file: str | None = None,
    messages: list[dict] | None = None,
) -> tuple[str, str]:
    """Classify a user prompt into ('none' | 'low' | 'medium' | 'high', reason).

    Biased upward toward 'high' whenever the prompt involves code, files, errors,
    engineering verbs, plan mode, or multi-step / ambiguous instructions.
    """
    raw = (text or "").strip()

    # 1. Plan mode always uses high thinking
    if mode == "plan" or plan_file:
        return "high", "plan mode"

    if not raw:
        return "none", "empty prompt"

    # 2. Explicit user thinking / no-thinking cues win immediately
    if _EXPLICIT_NONE_RE.search(raw):
        return "none", "explicit no-think cue"
    if _EXPLICIT_HIGH_RE.search(raw):
        return "high", "explicit thinking cue"

    words = _word_count(raw)

    # 3. Code fences, stack traces, file paths, @file references, or engineering verbs -> high
    if _CODE_OR_PATH_RE.search(raw):
        return "high", "code or file reference"
    if _ENGINEERING_RE.search(raw):
        return "high", "engineering task"

    # 4. Short follow-up correction / complaint after a prior turn -> high
    if words <= 25 and _has_prior_turn(messages) and _FOLLOWUP_COMPLAINT_RE.search(raw):
        return "high", "follow-up correction"

    # 5. Greetings, small talk, wake-word checks, or acknowledgements -> none
    if words <= 12 and (_GREETING_OR_ACK_RE.match(raw) or _BARE_WAKE_RE.match(raw)):
        return "none", "greeting or acknowledgement"

    # 6. Direct smart-home / device / media / timer / clock one-liner -> none
    if words <= 20 and _SMART_HOME_OR_CLOCK_RE.search(raw):
        return "none", "direct command"

    # 7. Conceptual explanations and trade-off comparisons -> medium
    if words <= 60 and _CONCEPTUAL_RE.search(raw):
        return "medium", "conceptual explanation"

    # 8. Short plain factual questions -> low
    if words <= 25 and "\n" not in raw:
        if _FACTUAL_STARTER_RE.search(raw) or (raw.endswith("?") and words <= 18):
            return "low", "short factual query"

    # 9. Upward fallback -> high
    return "high", "default upward fallback"


def should_escalate(
    *,
    bad_args: bool = False,
    tool_error: bool = False,
    non_zero_exit: bool = False,
    repeated_call: bool = False,
    loop_guard: bool = False,
    text_tool_retry: bool = False,
    finish_check_back: bool = False,
) -> str | None:
    """Return a human-readable escalation reason if any mid-turn failure signal is active."""
    if bad_args:
        return "malformed tool arguments"
    if repeated_call:
        return "repeated identical tool call"
    if tool_error:
        return "tool execution error"
    if non_zero_exit:
        return "non-zero command exit"
    if loop_guard:
        return "loop guard retry"
    if text_tool_retry:
        return "tool call written in text"
    if finish_check_back:
        return "incomplete work check"
    return None


def check_tool_result_failure(
    fn_name: str,
    args: dict | None,
    raw_args: str | None,
    result_text: str | None,
    seen_calls: set[tuple[str, str]],
    *,
    bad_args: bool = False,
) -> str | None:
    """Inspect a completed tool invocation and return an escalation reason on failure or repeat."""
    sig = (str(fn_name or ""), str(raw_args or "").strip())
    repeated = sig in seen_calls
    seen_calls.add(sig)

    has_bad_args = bool(bad_args) or (isinstance(args, dict) and "_raw" in args)
    txt = str(result_text or "").lstrip()
    tool_error = txt.startswith(("Error:", "Tool execution error"))

    non_zero_exit = False
    m = _NONZERO_EXIT_RE.search(txt)
    if m:
        try:
            non_zero_exit = int(m.group(1)) != 0
        except ValueError:
            non_zero_exit = True

    return should_escalate(
        bad_args=has_bad_args,
        repeated_call=repeated,
        tool_error=tool_error,
        non_zero_exit=non_zero_exit,
    )
