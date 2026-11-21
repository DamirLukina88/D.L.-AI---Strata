"""Per-model settings profiles for Ray: the DL_* behaviour settings of the model the server runs.

Settings tuned on one model (the thinking-level router, the edit-first watchdog's rounds, the lean thinking, the result
caps, the finish checks ...) are kept per model, so tuning one model does not force the change on the others.

    ~/.config/dl-ai/models/_default.json       settings for every model (the base layer)
    ~/.config/dl-ai/models/<model name>.json   settings for one model, over the base layer

The model name is the one the server's /health reports ("qwen3.8-flash-next-coder-iq1_m", "hy4-flash-sq-64"); a
character outside [A-Za-z0-9._-] is "_" in the file name.  A file is {"settings": {"DL_NUDGE_AT": 12, ...}} (any other
top-level key, such as "note", is ignored; a key that does not start with DL_ is ignored).  DL_MODEL_PROFILES names
another folder.

The order, last wins: the code's default, _default.json, <model>.json, the process environment.  The environment stays
on top so a test, a benchmark or a one-off run can still force a value.  No module here imports another dl_* module, so
every one of them (dl_advisor and dl_router included, which dl_common imports) can read through it.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_NAME = "_default"

# The model whose profile is in use (None: none known yet, only the code's defaults and _default.json), its merged
# settings, the files they came from with their mtimes (an edited file is read again), and the last problem with a file.
_STATE: dict = {"model": None, "settings": {}, "files": {}, "error": None, "loaded": False}
# This file is imported as `dl_profile` (flat) and as `tools.dl_profile` (package) in the same process: both copies
# share one state, so a model loaded through one is the model every reader sees.
_twin = sys.modules.get("tools.dl_profile" if __name__ == "dl_profile" else "dl_profile")
if _twin is not None and isinstance(getattr(_twin, "_STATE", None), dict):
    _STATE = _twin._STATE


_DIR_AT_IMPORT = os.environ.get("DL_MODEL_PROFILES")    # kept: a test that clears os.environ must not fall back to ~


def profiles_dir() -> Path:
    return Path(os.environ.get("DL_MODEL_PROFILES") or _DIR_AT_IMPORT
                or Path.home() / ".config" / "dl-ai" / "models").expanduser()


def file_for(model: str | None) -> Path:
    name = DEFAULT_NAME if not model else re.sub(r"[^A-Za-z0-9._-]", "_", str(model))
    return profiles_dir() / f"{name}.json"


def _value(v) -> str:
    """A profile's value as the text the environment would hold: true/false are 1/0."""
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def _read(path: Path) -> tuple[dict, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, ValueError) as e:
        return {}, f"{path.name}: {e}"
    settings = data.get("settings") if isinstance(data, dict) else None
    if not isinstance(settings, dict):
        return {}, f"{path.name}: no \"settings\" object"
    return {str(k): _value(v) for k, v in settings.items() if str(k).startswith("DL_") and v is not None}, None


def _mtimes(model: str | None) -> dict:
    out = {}
    for p in (file_for(None),) + ((file_for(model),) if model else ()):
        try:
            out[str(p)] = p.stat().st_mtime_ns
        except OSError:
            out[str(p)] = None
    return out


def use_model(model: str | None) -> bool:
    """Make `model`'s profile the one in use (read again when a file changed).  True when the settings changed."""
    model = str(model).strip() if model else None
    files = _mtimes(model)
    if _STATE["loaded"] and model == _STATE["model"] and files == _STATE["files"]:
        return False
    base, err1 = _read(file_for(None))
    own, err2 = _read(file_for(model)) if model else ({}, None)
    settings = {**base, **own}
    changed = settings != _STATE["settings"] or model != _STATE["model"]
    _STATE.update(model=model, settings=settings, files=files, error=err2 or err1, loaded=True)
    return changed


def _ensure() -> None:
    if not _STATE["loaded"]:
        use_model(None)


def env(name: str, default: str | None = None) -> str | None:
    """os.environ.get(name, default), with the model's profile between the two."""
    if name in os.environ:
        return os.environ[name]
    _ensure()
    v = _STATE["settings"].get(name)
    return default if v is None else v


def from_env_then_profile(names) -> tuple[str, str] | None:
    """(name, value) of the first of `names` the environment sets, else of the first the profile sets; None when
    neither does.  For a setting with several spellings (DL_MCP_ROUTER_MODE, DL_ROUTER_MODE ...): the environment, at
    any spelling, goes over the profile."""
    for n in names:
        if os.environ.get(n, "").strip():
            return n, os.environ[n].strip()
    _ensure()
    for n in names:
        if (_STATE["settings"].get(n) or "").strip():
            return n, _STATE["settings"][n].strip()
    return None


def switch(name: str) -> bool:
    """An on/off setting that is on unless it says 0, off, false or no."""
    return (env(name, "1") or "1").strip().lower() not in ("0", "off", "false", "no")


def tuned(name: str, current, cast=int):
    """A module constant read at import (`NUDGE_AT = int(os.environ.get("DL_NUDGE_AT") or 12)`) at the moment it is
    used: `current` when the environment sets the name (the constant already holds it) or the profile does not; the
    profile's value otherwise.  `current` is the constant as the caller sees it, so a test that patches it still wins
    when no profile is in use."""
    if name in os.environ:
        return current
    _ensure()
    v = _STATE["settings"].get(name)
    if v is None:
        return current
    try:
        return cast(v)
    except (TypeError, ValueError):
        pass
    if cast is int:                                       # "12.0" (a JSON number written as 12.0) is 12
        try:
            f = float(v)
            if f.is_integer():
                return int(f)
        except (TypeError, ValueError):
            pass
    return current


def active() -> dict:
    """The profile in use: {"model", "settings", "file", "error"} (file: the model's own file, None when it has none)."""
    _ensure()
    own = file_for(_STATE["model"]) if _STATE["model"] else None
    return {"model": _STATE["model"], "settings": dict(_STATE["settings"]),
            "file": str(own) if own is not None and own.is_file() else None, "error": _STATE["error"]}


def describe(model: str | None = None) -> str:
    """One line for the change notice (the profile in use) or for /status (`model`: the profile that model gets, read
    from the files without making it the one in use, so the next request's sync still sees a model swap)."""
    if model is None:
        a = active()
        model, settings, err, own = a["model"], a["settings"], a["error"], a["file"]
    else:
        base, err1 = _read(file_for(None))
        mine, err2 = _read(file_for(model))
        settings, err = {**base, **mine}, err2 or err1
        own = str(file_for(model)) if file_for(model).is_file() else None
    own_text = Path(own).name if own else "no profile of its own"
    base_text = " + _default.json" if file_for(None).is_file() else ""
    line = f"Settings profile: {model or 'unknown model'} ({own_text}{base_text}, {len(settings)} settings)"
    return line + (f"; could not read {err}" if err else "")


def reset() -> None:
    """Forget the profile in use (tests)."""
    _STATE.clear()
    _STATE.update(model=None, settings={}, files={}, error=None, loaded=False)
