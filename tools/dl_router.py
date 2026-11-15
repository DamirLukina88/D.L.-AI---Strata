"""tools/dl_router.py - Shared CPU Model2Vec router for thinking effort and MCP server selection.

Loads a local int8 Model2Vec directory offline on first use behind a lock.
If model2vec or the local model directory is unavailable, every call returns None / False
and records a one-time fallback notice so callers cleanly fall back to rules.
"""
from __future__ import annotations

import ctypes
import gc
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Sequence

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy missing fallback
    np = None

VALID_MODES = ("rules", "model2vec", "hybrid")
FALLBACK_NOTICE = "Router: Model2Vec not available, using rules"

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = Path.home() / ".local" / "share" / "dl-ai" / "models" / "potion-base-32M-int8"
DEFAULT_PROTOTYPES_PATH = HERE / "dl_router_prototypes.json"

_FENCE_RE = re.compile(r"```[\s\S]*?(?:```|$)")
_TRACEBACK_RE = re.compile(
    r"Traceback \(most recent call last\):(?:\r?\n[ \t]+[^\r\n]*|\r?\nFile [^\r\n]*)+(?:\r?\n[^\s\r\n][^\r\n]*)?",
)

_twin = sys.modules.get("tools.dl_router" if __name__ == "dl_router" else "dl_router")
_STATE = getattr(_twin, "_STATE", None)
if _STATE is None:
    _STATE = {
        "lock": threading.RLock(),
        "models": {},
        "failed": {},
        "stats": {},
        "fallback_emitted": False,
        "fallback_pending": False,
    }
_LOCK = _STATE["lock"]
_MODELS: dict[str, object] = _STATE["models"]
_FAILED: dict[str, str] = _STATE["failed"]
_STATS: dict[str, dict] = _STATE["stats"]


def router_mode(mode: str | None = None, *, subsystem: str | None = None) -> str:
    """Resolve active router mode: 'rules' (default), 'model2vec', or 'hybrid'.

    DL_<SUBSYSTEM>_ROUTER_MODE (e.g. DL_EFFORT_ROUTER_MODE, DL_MCP_ROUTER_MODE)
    overrides DL_ROUTER_MODE; legacy DL_SEMANTIC_ROUTER=1 maps to 'hybrid'.
    """
    if mode is not None:
        m = str(mode).strip().lower()
        return m if m in VALID_MODES else "rules"
    if subsystem:
        sub_key = f"DL_{str(subsystem).strip().upper()}_ROUTER_MODE"
        sub_mode = os.environ.get(sub_key, "").strip().lower()
        if sub_mode:
            return sub_mode if sub_mode in VALID_MODES else "rules"
    env_mode = os.environ.get("DL_ROUTER_MODE", "").strip().lower()
    if env_mode:
        return env_mode if env_mode in VALID_MODES else "rules"
    legacy = os.environ.get("DL_SEMANTIC_ROUTER", "").strip().lower()
    if legacy in ("1", "true", "yes", "on"):
        return "hybrid"
    return "rules"


def model_dir_path(model_dir: Path | str | None = None) -> Path:
    if model_dir is not None:
        return Path(model_dir).expanduser()
    env_dir = os.environ.get("DL_ROUTER_MODEL_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return DEFAULT_MODEL_DIR


def prototypes_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_p = os.environ.get("DL_ROUTER_PROTOTYPES", "").strip()
    if env_p:
        return Path(env_p).expanduser()
    return DEFAULT_PROTOTYPES_PATH


def load_prototypes(path: Path | str | None = None) -> dict:
    p = prototypes_path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def prepare(text: str, max_chars: int = 512) -> str:
    """Strip fenced code and long pasted blocks, collapse whitespace, and cap length."""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if not s:
        return ""

    # Replace fenced code blocks with a compact marker so prose intent stays dominant.
    s = _FENCE_RE.sub(" [code] ", s)
    # Trim oversized tracebacks.
    s = _TRACEBACK_RE.sub(" [traceback] ", s)

    # Collapse long multi-line pastes (e.g. logs, dumps, files pasted inline).
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) > 8:
        kept = lines[:3] + ["[pasted block]"] + lines[-1:]
        s = " ".join(kept)
    elif len(s) > max_chars and len(lines) > 3:
        kept = lines[:2] + ["[pasted block]"] + lines[-1:]
        s = " ".join(kept)

    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_chars:
        cut = s[:max_chars].rsplit(" ", 1)[0].strip()
        s = cut if len(cut) >= max_chars // 2 else s[:max_chars].strip()
    return s


def _release_transient_heap() -> None:
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def _rss_mib() -> float:
    try:
        statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
        pages = int(statm[1])
        page_sz = os.sysconf("SC_PAGE_SIZE")
        return round((pages * page_sz) / (1024.0 * 1024.0), 2)
    except (OSError, ValueError, IndexError, AttributeError):
        return 0.0


def _note_fallback() -> None:
    if not _STATE["fallback_emitted"]:
        _STATE["fallback_pending"] = True


def consume_fallback_notice() -> str | None:
    """Return the one-time fallback notice if Model2Vec failed, else None."""
    with _LOCK:
        if _STATE["fallback_pending"] and not _STATE["fallback_emitted"]:
            _STATE["fallback_pending"] = False
            _STATE["fallback_emitted"] = True
            return FALLBACK_NOTICE
        return None


def reset_state() -> None:
    """Clear cached models, errors, and one-time notice flags (for tests)."""
    with _LOCK:
        _MODELS.clear()
        _FAILED.clear()
        _STATS.clear()
        _STATE["fallback_emitted"] = False
        _STATE["fallback_pending"] = False


def get_model(model_dir: Path | str | None = None):
    """Load and cache the offline Model2Vec model, or return None if unavailable."""
    if np is None:
        with _LOCK:
            _note_fallback()
        return None

    p = model_dir_path(model_dir)
    key = str(p)
    with _LOCK:
        if key in _MODELS:
            return _MODELS[key]
        if key in _FAILED:
            _note_fallback()
            return None

        if not p.is_dir() or not ((p / "model.safetensors").is_file() or (p / "embeddings.npy").is_file()):
            _FAILED[key] = f"model directory not found: {p}"
            _STATS[key] = {
                "available": False,
                "model_dir": key,
                "error": _FAILED[key],
                "load_time_ms": 0.0,
                "rss_before_mib": _rss_mib(),
                "rss_after_mib": _rss_mib(),
                "rss_delta_mib": 0.0,
            }
            _note_fallback()
            return None

        try:
            from model2vec import StaticModel  # type: ignore
        except ImportError as e:
            _FAILED[key] = f"model2vec import failed: {e}"
            _STATS[key] = {
                "available": False,
                "model_dir": key,
                "error": _FAILED[key],
                "load_time_ms": 0.0,
                "rss_before_mib": _rss_mib(),
                "rss_after_mib": _rss_mib(),
                "rss_delta_mib": 0.0,
            }
            _note_fallback()
            return None

        prev_offline = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        rss_before = _rss_mib()
        t0 = time.perf_counter()
        try:
            try:
                model = StaticModel.from_pretrained(str(p), force_download=False)
            except TypeError:
                model = StaticModel.from_pretrained(str(p))
        except Exception as e:
            _FAILED[key] = f"model load failed: {e}"
            rss_after = _rss_mib()
            _STATS[key] = {
                "available": False,
                "model_dir": key,
                "error": _FAILED[key],
                "load_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "rss_before_mib": rss_before,
                "rss_after_mib": rss_after,
                "rss_delta_mib": round(max(0.0, rss_after - rss_before), 2),
            }
            _note_fallback()
            return None
        finally:
            if prev_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prev_offline

        load_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        rss_peak_after = _rss_mib()
        _release_transient_heap()
        rss_after = _rss_mib()
        _MODELS[key] = model
        _STATS[key] = {
            "available": True,
            "model_dir": key,
            "error": "",
            "load_time_ms": load_ms,
            "rss_before_mib": rss_before,
            "rss_after_mib": rss_after,
            "rss_delta_mib": round(max(0.0, rss_after - rss_before), 2),
            "rss_peak_delta_mib": round(max(0.0, rss_peak_after - rss_before), 2),
        }
        return model


def is_available(model_dir: Path | str | None = None) -> bool:
    return get_model(model_dir) is not None


def stats(model_dir: Path | str | None = None) -> dict:
    p = model_dir_path(model_dir)
    key = str(p)
    with _LOCK:
        if key not in _STATS:
            get_model(p)
        return dict(_STATS.get(key, {"available": False, "model_dir": key, "error": "not loaded"}))


def _l2_normalize(arr):
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 1:
        norm = float(np.linalg.norm(arr))
        return arr / norm if norm > 1e-8 else np.zeros_like(arr, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    safe_norms = np.where(norms > 1e-8, norms, 1.0)
    out = arr / safe_norms
    out = np.where(norms > 1e-8, out, 0.0)
    return out.astype(np.float32, copy=False)


def encode(
    texts: str | Sequence[str],
    *,
    model_dir: Path | str | None = None,
    preprocess: bool = True,
):
    """Encode a string or sequence of strings into L2-normalized float32 embeddings.

    Returns None if Model2Vec or the model directory is unavailable.
    """
    model = get_model(model_dir)
    if model is None or np is None:
        return None

    single = isinstance(texts, str)
    raw_list = [texts] if single else list(texts)
    if not raw_list:
        return np.zeros((0, 0), dtype=np.float32)

    cleaned = [prepare(t) if preprocess else (t or "").strip() for t in raw_list]
    try:
        vecs = model.encode(cleaned)
    except Exception:
        with _LOCK:
            _note_fallback()
        return None

    normed = _l2_normalize(vecs)
    return normed[0] if single else normed


def cosine_scores(query_vec, matrix):
    """Compute cosine similarity between an L2-normalized query vector and matrix rows."""
    if np is None or query_vec is None or matrix is None or len(matrix) == 0:
        return np.zeros((0,), dtype=np.float32) if np is not None else []
    return np.dot(matrix, query_vec).astype(np.float32, copy=False)
