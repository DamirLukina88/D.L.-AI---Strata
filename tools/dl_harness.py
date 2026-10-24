"""tools/dl_harness.py - Modular Harness Assembler & Skill Loader for Ray (D.L. CLI).

Loads editable harness components (system identity, guardrails, tool guidance, on-demand skills)
from `harness/` with sub-millisecond mtime caching and automatic fallbacks to guarantee zero breakage.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HARNESS_DIR = REPO_ROOT / "harness"

_mtime_cache: dict[str, tuple[float, str]] = {}


def get_harness_dir() -> Path:
    override = os.environ.get("DL_HARNESS_DIR")
    if override:
        return Path(override)
    return DEFAULT_HARNESS_DIR


def read_cached(path: Path, fallback: str = "") -> str:
    """Read file with st_mtime cache; returns fallback if missing or unreadable."""
    try:
        st = path.stat()
        mtime = st.st_mtime
        key = str(path.resolve())
        cached = _mtime_cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        _mtime_cache[key] = (mtime, text)
        return text
    except (OSError, FileNotFoundError):
        return fallback


def get_guardrails(harness_dir: Path | None = None) -> str:
    h_dir = harness_dir or get_harness_dir()
    p = h_dir / "guardrails.md"
    return read_cached(p, fallback="")


def get_tool_guidance(harness_dir: Path | None = None) -> str:
    h_dir = harness_dir or get_harness_dir()
    p = h_dir / "tool_guidance.md"
    return read_cached(p, fallback="")


def get_system_prompt_text(harness_dir: Path | None = None) -> str:
    h_dir = harness_dir or get_harness_dir()
    p = h_dir / "systemprompt.md"
    return read_cached(p, fallback="")


def list_skills(harness_dir: Path | None = None) -> list[str]:
    """Return available specialist skill names."""
    h_dir = harness_dir or get_harness_dir()
    skills_dir = h_dir / "skills"
    if not skills_dir.is_dir():
        return []
    try:
        return [
            d.name
            for d in sorted(skills_dir.iterdir())
            if d.is_dir() and (d / "SKILL.md").is_file()
        ]
    except OSError:
        return []


def load_skill(skill_name: str, harness_dir: Path | None = None) -> str | None:
    """Load a specific skill's SKILL.md content."""
    h_dir = harness_dir or get_harness_dir()
    p = h_dir / "skills" / skill_name / "SKILL.md"
    if not p.is_file():
        return None
    return read_cached(p, fallback="")


def build_modular_guidelines(harness_dir: Path | None = None, mode: str = "act") -> str:
    """Build the guidelines block by composing guardrails and tool guidance."""
    h_dir = harness_dir or get_harness_dir()
    guardrails = get_guardrails(h_dir)
    guidance = get_tool_guidance(h_dir)

    sections = []
    if guardrails:
        sections.append(f"<guardrails>\n{guardrails}\n</guardrails>")
    if guidance:
        sections.append(f"<tool_guidance>\n{guidance}\n</tool_guidance>")

    skills = list_skills(h_dir)
    if skills:
        skills_str = ", ".join(f"`{s}`" for s in skills)
        sections.append(f"<available_skills>\nSpecialist playbooks available: {skills_str}.\n</available_skills>")

    return "\n\n".join(sections)
