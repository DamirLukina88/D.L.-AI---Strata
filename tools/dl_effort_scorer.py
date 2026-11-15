"""tools/dl_effort_scorer.py - Lightweight CPU semantic difficulty router (<2 ms latency).

Uses local Model2Vec embeddings via tools/dl_router when available, falling back
to deterministic n-gram/token CRC32 feature hashing otherwise. Learns from
dl_router_prototypes.json plus the private gold tuning split (never effort_matrix.json
and never the held-out test split).
"""
from __future__ import annotations

import json
import os
import re
import threading
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

if __package__ == "tools":
    from tools import dl_router
else:
    try:
        import dl_router
    except ImportError:
        from tools import dl_router

HERE = Path(__file__).resolve().parent
DIMENSION = 256
CONFIDENCE_THRESHOLD = 0.55
MIN_SIMILARITY = 0.25
DEFAULT_GOLD_PATH = Path.home() / ".local" / "state" / "dl-ai" / "benchmarks" / "router_gold" / "gold.json"
TOKEN_RE = re.compile(r"\b\w+\b")


def _deterministic_hash(s: str, dim: int = DIMENSION) -> int:
    """Deterministic CRC32 hash to guarantee cross-process feature index stability."""
    return zlib.crc32(s.encode("utf-8")) % dim


def vectorize(text: str, dim: int = DIMENSION):
    """Vectorize text using word tokens and character 3-grams/4-grams with L2 normalization."""
    if np is None:
        return None

    vec = np.zeros(dim, dtype=np.float32)
    raw = (text or "").lower().strip()
    if not raw:
        return vec

    # Word unigrams and bigrams
    words = TOKEN_RE.findall(raw)
    for w in words:
        vec[_deterministic_hash(f"w_{w}", dim)] += 1.5
    for i in range(len(words) - 1):
        vec[_deterministic_hash(f"bi_{words[i]}_{words[i+1]}", dim)] += 2.0

    # Character 3-grams & 4-grams (captures morphological & verb stems)
    padded = f"^{raw}$"
    for n in (3, 4):
        for i in range(len(padded) - n + 1):
            ngram = padded[i : i + n]
            vec[_deterministic_hash(f"c_{ngram}", dim)] += 1.0

    norm = float(np.linalg.norm(vec))
    if norm > 1e-6:
        vec /= norm
    return vec


def gold_file_path(gold_path: Path | str | None = None) -> Path:
    if gold_path:
        return Path(gold_path).expanduser()
    env_g = os.environ.get("DL_ROUTER_GOLD", "").strip()
    return Path(env_g).expanduser() if env_g else DEFAULT_GOLD_PATH


def _file_stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return None


class EffortScorer:
    def __init__(
        self,
        dim: int = DIMENSION,
        threshold: float = CONFIDENCE_THRESHOLD,
        min_sim: float = MIN_SIMILARITY,
        model_dir: Path | str | None = None,
        prototypes_file: Path | str | None = None,
        gold_path: Path | str | None = None,
        include_gold_tune: bool = True,
        use_unreviewed_tune: bool = False,
        backend: str = "auto",
    ):
        self.dim = dim
        self.threshold = threshold
        self.min_sim = min_sim
        self.model_dir = model_dir
        self.prototypes_file = prototypes_file
        self.gold_path = gold_file_path(gold_path)
        self.include_gold_tune = include_gold_tune
        self.use_unreviewed_tune = use_unreviewed_tune or os.environ.get("DL_ROUTER_USE_UNREVIEWED_TUNE") == "1"
        self.backend = backend
        self.use_model2vec = False
        self.vectors = None
        self.labels: list[str] = []
        self.prompts: list[str] = []
        self.prepared_prompts: list[str] = []
        self.sources: list[str] = []
        self._load_seed_data()

    def _collect_samples(self) -> list[tuple[str, str, str]]:
        samples: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        # 1. Built-in made-up EN/HR prototypes
        proto = dl_router.load_prototypes(self.prototypes_file)
        eff_proto = proto.get("effort") if isinstance(proto.get("effort"), dict) else {}
        for lvl in ("none", "low", "medium", "high"):
            for item in eff_proto.get(lvl) or []:
                p = str(item).strip()
                if p and (p, lvl) not in seen:
                    seen.add((p, lvl))
                    samples.append((p, lvl, "prototype"))

        # 2. Private gold tuning half ONLY (never test half, never effort_matrix.json)
        if self.include_gold_tune and self.gold_path.is_file():
            try:
                data = json.loads(self.gold_path.read_text(encoding="utf-8"))
                if not data.get("reviewed", False) and not self.use_unreviewed_tune:
                    return samples
                for rec in data.get("records", []):
                    if rec.get("split") != "tune":
                        continue
                    lvl = rec.get("gold_effort")
                    if lvl not in ("none", "low", "medium", "high") and self.use_unreviewed_tune and rec.get("effort_sample"):
                        lvl = rec.get("effort_proposed")
                    p = (rec.get("text") or "").strip()
                    if lvl in ("none", "low", "medium", "high") and p and (p, lvl) not in seen:
                        seen.add((p, lvl))
                        samples.append((p, lvl, "gold_tune"))
            except (OSError, ValueError):
                pass

        return samples

    def _load_seed_data(self) -> None:
        samples = self._collect_samples()
        if not samples or np is None:
            return

        if self.backend in ("auto", "model2vec") and dl_router.is_available(self.model_dir):
            prompts = [p for p, _, _ in samples]
            mat = dl_router.encode(prompts, model_dir=self.model_dir, preprocess=True)
            if mat is not None and len(mat) == len(samples):
                self.vectors = mat
                self.labels = [lvl for _, lvl, _ in samples]
                self.prompts = prompts
                self.prepared_prompts = [dl_router.prepare(p) for p in prompts]
                self.sources = [src for _, _, src in samples]
                self.use_model2vec = True
                return

        if self.backend == "model2vec":
            return

        vec_list = []
        label_list = []
        prompt_list = []
        prep_list = []
        source_list = []
        for prompt, target, src in samples:
            v = vectorize(prompt, self.dim)
            if v is not None:
                vec_list.append(v)
                label_list.append(target)
                prompt_list.append(prompt)
                prep_list.append(dl_router.prepare(prompt))
                source_list.append(src)

        if vec_list:
            self.vectors = np.vstack(vec_list)
            self.labels = label_list
            self.prompts = prompt_list
            self.prepared_prompts = prep_list
            self.sources = source_list
            self.use_model2vec = False

    def predict(self, prompt: str, k: int = 3, *, exclude_text: str | None = None) -> tuple[str, float]:
        """Classify prompt difficulty into (level, confidence).

        If confidence < threshold (or similarity < min_sim in Model2Vec mode),
        defaults to 'high' (safety upward bias).
        """
        if np is None or self.vectors is None or len(self.labels) == 0:
            return "high", 0.0

        if self.use_model2vec:
            q = dl_router.encode(prompt, model_dir=self.model_dir, preprocess=True)
            if q is None:
                return "high", 0.0
            sims = dl_router.cosine_scores(q, self.vectors)
        else:
            q = vectorize(prompt, self.dim)
            if q is None:
                return "high", 0.0
            sims = np.dot(self.vectors, q)

        if len(sims) == 0:
            return "high", 0.0

        if exclude_text is not None:
            ex_raw = exclude_text.strip()
            ex_prep = dl_router.prepare(ex_raw)
            sims = sims.copy()
            for i, src in enumerate(self.sources):
                if src == "gold_tune" and (
                    self.prompts[i] == ex_raw or (ex_prep and self.prepared_prompts[i] == ex_prep)
                ):
                    sims[i] = -1.0

        k_eff = min(k, len(self.labels))
        top_indices = np.argsort(sims)[::-1][:k_eff]
        max_sim = float(sims[top_indices[0]]) if len(top_indices) > 0 else 0.0
        if self.use_model2vec and self.min_sim > 0 and max_sim < self.min_sim:
            return "high", round(max(0.0, max_sim), 3)
        if self.use_model2vec and max_sim >= 0.96:
            return self.labels[top_indices[0]], round(min(1.0, max_sim), 3)

        weights: dict[str, float] = {"none": 0.0, "low": 0.0, "medium": 0.0, "high": 0.0}
        total_weight = 0.0
        for idx in top_indices:
            s = float(sims[idx])
            if s > 0:
                w = (s ** 4) if self.use_model2vec else s
                lvl = self.labels[idx]
                weights[lvl] = weights.get(lvl, 0.0) + w
                total_weight += w

        if total_weight <= 1e-6:
            return "high", 0.0

        best_lvl = max(weights.items(), key=lambda kv: kv[1])[0]
        vote_share = weights[best_lvl] / total_weight
        if self.use_model2vec and self.min_sim > 0:
            sim_scale = min(1.0, max(0.0, max_sim) / self.min_sim)
            confidence = round(vote_share * sim_scale, 3)
        else:
            confidence = round(vote_share, 3)

        if confidence < self.threshold:
            return "high", confidence
        return best_lvl, confidence

    def score_difficulty(self, prompt: str, *, exclude_text: str | None = None) -> tuple[str, float]:
        """Alias for predict."""
        return self.predict(prompt, exclude_text=exclude_text)


# Module-level cache keyed by resolved model_dir, gold/prototypes paths + mtime stamps, and unreviewed flag
_SCORER_LOCK = threading.RLock()
_SCORERS: dict[tuple, EffortScorer] = {}


def reset_scorer() -> None:
    with _SCORER_LOCK:
        _SCORERS.clear()


def get_scorer(
    model_dir: Path | str | None = None,
    *,
    prototypes_file: Path | str | None = None,
    gold_path: Path | str | None = None,
    use_unreviewed_tune: bool = False,
) -> EffortScorer:
    m_key = str(dl_router.model_dir_path(model_dir))
    g_path = gold_file_path(gold_path)
    p_path = dl_router.prototypes_path(prototypes_file)
    unreviewed = bool(use_unreviewed_tune or os.environ.get("DL_ROUTER_USE_UNREVIEWED_TUNE") == "1")
    key = (
        m_key,
        str(g_path),
        _file_stamp(g_path),
        str(p_path),
        _file_stamp(p_path),
        unreviewed,
    )
    with _SCORER_LOCK:
        sc = _SCORERS.get(key)
        if sc is None:
            stale = [
                k for k in _SCORERS
                if k[0] == m_key and k[1] == str(g_path) and k[3] == str(p_path) and k[5] == unreviewed
            ]
            for k in stale:
                _SCORERS.pop(k, None)
            sc = EffortScorer(
                model_dir=model_dir,
                prototypes_file=prototypes_file,
                gold_path=gold_path,
                use_unreviewed_tune=use_unreviewed_tune,
            )
            _SCORERS[key] = sc
        return sc


def predict(prompt: str, model_dir: Path | str | None = None) -> tuple[str, float]:
    return get_scorer(model_dir=model_dir).predict(prompt)


def score_difficulty(prompt: str, model_dir: Path | str | None = None) -> tuple[str, float]:
    return get_scorer(model_dir=model_dir).score_difficulty(prompt)
