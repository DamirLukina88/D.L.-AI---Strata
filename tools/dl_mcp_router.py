"""tools/dl_mcp_router.py - Embedding-based MCP server router using dl_router (Model2Vec).

Scores catalogue servers against prototype examples (and a '_none' no-server group),
cached by a hash of the catalogue and prototypes file.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

if __package__ == "tools":
    from tools import dl_router
else:
    try:
        import dl_router
    except ImportError:
        from tools import dl_router

MIN_SCORE = 0.55
NONE_MARGIN = 0.05
MAX_SERVERS = 2

_LOCK = threading.RLock()
_INDEX_CACHE: dict[tuple[str, str, str], dict] = {}


def _catalog_hash(catalog: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(catalog):
        entry = catalog[name]
        desc = getattr(entry, "description", "") if not isinstance(entry, dict) else entry.get("description", "")
        h.update(f"{name}\0{desc}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def _prototypes_hash(path: Path) -> tuple[str, dict]:
    try:
        raw = path.read_bytes()
        h = hashlib.sha256(raw).hexdigest()[:16]
        data = json.loads(raw.decode("utf-8"))
        return h, data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return "missing", {}


def _build_index(
    catalog: dict,
    *,
    model_dir: Path | str | None = None,
    prototypes_file: Path | str | None = None,
) -> dict | None:
    if np is None or not dl_router.is_available(model_dir):
        return None

    m_key = str(dl_router.model_dir_path(model_dir))
    p_path = dl_router.prototypes_path(prototypes_file)
    p_hash, proto_data = _prototypes_hash(p_path)
    c_hash = _catalog_hash(catalog)
    cache_key = (m_key, c_hash, p_hash)

    with _LOCK:
        if cache_key in _INDEX_CACHE:
            return _INDEX_CACHE[cache_key]

    mcp_proto = proto_data.get("mcp") if isinstance(proto_data.get("mcp"), dict) else {}
    none_examples = [str(x) for x in (mcp_proto.get("_none") or []) if str(x).strip()]

    phrases: list[str] = []
    slices: dict[str, tuple[int, int]] = {}

    if none_examples:
        start = len(phrases)
        phrases.extend(none_examples)
        slices["_none"] = (start, len(phrases))

    for name, entry in catalog.items():
        if name.startswith("_"):
            continue
        examples = [str(x) for x in (mcp_proto.get(name) or []) if str(x).strip()]
        if not examples:
            desc = getattr(entry, "description", "") if not isinstance(entry, dict) else entry.get("description", "")
            desc = str(desc or "").strip()
            if desc and desc.lower() != "a fake server":
                examples = [desc]
        if examples:
            start = len(phrases)
            phrases.extend(examples)
            slices[name] = (start, len(phrases))

    if not phrases:
        idx = {"none_vecs": np.zeros((0, 0), dtype=np.float32), "server_vecs": {}}
    else:
        mat = dl_router.encode(phrases, model_dir=model_dir, preprocess=False)
        if mat is None:
            return None
        none_vecs = mat[slices["_none"][0] : slices["_none"][1]] if "_none" in slices else np.zeros((0, mat.shape[1]), dtype=np.float32)
        server_vecs = {
            name: mat[a:b]
            for name, (a, b) in slices.items()
            if name != "_none"
        }
        idx = {"none_vecs": none_vecs, "server_vecs": server_vecs}

    with _LOCK:
        _INDEX_CACHE[cache_key] = idx
    return idx


def clear_cache() -> None:
    with _LOCK:
        _INDEX_CACHE.clear()


def score_servers(
    text: str,
    catalog: dict,
    *,
    surface: str = "code",
    enabled: dict | set | None = None,
    model_dir: Path | str | None = None,
    prototypes_file: Path | str | None = None,
) -> tuple[list[tuple[str, float]], float, bool]:
    """Return ([(server_name, score), ...], none_score, used_model) sorted by descending score."""
    idx = _build_index(catalog, model_dir=model_dir, prototypes_file=prototypes_file)
    if idx is None:
        return [], 0.0, False

    raw = (text or "").strip()
    if not raw:
        return [], 0.0, True

    q = dl_router.encode(raw, model_dir=model_dir, preprocess=True)
    if q is None:
        return [], 0.0, False

    none_vecs = idx["none_vecs"]
    none_score = float(np.max(dl_router.cosine_scores(q, none_vecs))) if len(none_vecs) > 0 else 0.0

    enabled_set = set(enabled) if enabled else set()
    scored: list[tuple[float, str]] = []
    for name, entry in catalog.items():
        if name in enabled_set:
            continue
        unavail = entry.unavailable(surface) if hasattr(entry, "unavailable") else None
        if unavail:
            continue
        unless_rxs = getattr(entry, "unless", ()) or ()
        if any(rx.search(raw) for rx in unless_rxs):
            continue
        vecs = idx["server_vecs"].get(name)
        if vecs is None or len(vecs) == 0:
            continue
        s = float(np.max(dl_router.cosine_scores(q, vecs)))
        scored.append((s, name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(name, score) for score, name in scored], none_score, True


def route(
    text: str,
    catalog: dict,
    *,
    surface: str = "code",
    enabled: dict | set | None = None,
    model_dir: Path | str | None = None,
    prototypes_file: Path | str | None = None,
    min_score: float = MIN_SCORE,
    none_margin: float = NONE_MARGIN,
    max_servers: int = MAX_SERVERS,
) -> tuple[list[tuple[str, float]], bool]:
    """Select up to `max_servers` MCP servers above `min_score` and `none_score + none_margin`.

    Returns ([(name, score), ...], used_model).
    """
    scored, none_score, used_model = score_servers(
        text,
        catalog,
        surface=surface,
        enabled=enabled,
        model_dir=model_dir,
        prototypes_file=prototypes_file,
    )
    if not used_model:
        return [], False

    picked: list[tuple[str, float]] = []
    for name, score in scored:
        if score >= min_score and (score - none_score) >= none_margin:
            picked.append((name, round(score, 4)))
            if len(picked) >= max_servers:
                break
    return picked, True
