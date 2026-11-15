"""Shared by the D.L. CLI modules: optional imports, colours, env loading, defaults, small helpers.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import os


# The shared memory store (jj + SQLite FTS5 + Model2Vec), shared with Claude Code and Antigravity; with it off
# (RAY_MEMORY_DIR=off, or no ~/.config/dl-ai/memory.json) the per-project wiki/ path below is used as before.
try:
    from tools import dl_memory
except ImportError:
    try:
        import dl_memory
    except ImportError:
        dl_memory = None


try:
    import dl_advisor
except ImportError:
    dl_advisor = None


def memory_store() -> Path | None:
    """The shared memory store's root, or None when it is off."""
    return dl_memory.resolve_memory_root() if dl_memory is not None else None


# Auditing & Debugging Suite Integration
try:
    from tools.dl_auditing import (
        format_health_card,
        get_system_health,
        scan_secrets_in_text,
        tool_git_diff_audit,
        tool_scan_secrets,
        tool_smart_test_runner,
        tool_syntax_guard,
        validate_syntax,
        classify_command,
        classify_write,
    )
except ImportError:
    from dl_auditing import (
        format_health_card,
        get_system_health,
        scan_secrets_in_text,
        tool_git_diff_audit,
        tool_scan_secrets,
        tool_smart_test_runner,
        tool_syntax_guard,
        validate_syntax,
        classify_command,
        classify_write,
    )


# On-demand MCP servers (~/.config/dl-ai/mcp.json); without the file, nothing changes
try:
    from tools import dl_mcp
except ImportError:
    try:
        import dl_mcp
    except ImportError:          # serve/ not next to tools/: MCP servers are simply not offered
        dl_mcp = None


try:
    from tools import dl_effort
except ImportError:
    try:
        import dl_effort
    except ImportError:
        dl_effort = None


# ANSI colors & formatting (Strata Dark & Orange Aesthetic)
C_RESET = "\033[0m"


C_BOLD = "\033[1m"


C_DIM = "\033[2m"


C_ACCENT = "\033[38;5;208m"       # Strata Orange (#f97316)


C_ACCENT_BOLD = "\033[1;38;5;208m"


C_ACCENT_SOFT = "\033[38;5;215m"  # Warm peach (#fb923c)


C_INK = "\033[38;5;255m"          # Crisp text (#f3f4f6)


C_INK_SOFT = "\033[38;5;250m"     # Soft text (#cbd5e1)


C_MUTED = "\033[38;5;244m"        # Slate muted (#94a3b8)


C_LINE = "\033[38;5;238m"         # Border line (#222933)


C_GREEN = "\033[38;5;78m"         # Success green


C_YELLOW = "\033[38;5;221m"       # Amber


C_RED = "\033[38;5;203m"          # Soft error red


C_BLUE = "\033[38;5;111m"         # Info soft blue


C_CYAN = "\033[38;5;80m"          # Cyan



def load_env_file(path: Path = Path.home() / ".config" / "dl-ai" / "secrets.env") -> None:
    """Load KEY=VALUE lines from the local secrets file; variables already in the environment win."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env_file()


DEFAULT_URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8080").removesuffix("/v1")


DEFAULT_API_KEY = os.environ.get("STRATA_API_KEY", "")


DEFAULT_EXA_KEY = os.environ.get("EXA_API_KEY", "")


DEFAULT_CONTEXT7_KEY = os.environ.get("CONTEXT7_API_KEY", "")


DEFAULT_CLIENT_IP_KEY = os.environ.get("CLIENT_IP_ENCRYPTION_KEY", "")


# ---------------------------------------------------------------------------------------------------- finish checks
# Before an Act-mode reply is taken as the end of the task, D.L. CLI checks it (items 2, 3, 5 of
# wiki/artifacts/dl-cli-agent-quality-plan.md plus the plan done check).  Each one can be turned off: DL_DONE_CHECK=0,
# DL_BROWSER_CHECK=0, DL_EVIDENCE=0, DL_REVIEW=0.  Each sends the agent back at most once per request, except the
# done check, which in YOLO keeps sending it back until the plan is done, blocked, or nothing changes 3 times in a row.
def _switch(name: str) -> bool:
    return os.environ.get(name, "1").strip() not in ("0", "off", "false", "no")


def _note(emit, text: str, level: str = "info") -> None:
    if emit:
        emit({"type": "notice", "level": level, "text": text})
    else:
        print(f"{C_YELLOW if level == 'warn' else C_MUTED}{text}{C_RESET}")


def cli():
    """The dl_cli module this package instance belongs to (flat `dl_cli`, or `tools.dl_cli`): names that tests patch
    on dl_cli, and code that stays there, are looked up through it at call time."""
    import importlib
    return importlib.import_module((__package__ + "." if __package__ else "") + "dl_cli")
