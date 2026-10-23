"""tools/dl_effort_scorer.py - Lightweight CPU semantic difficulty router (<2 ms latency).

Employs deterministic n-gram/token feature hashing with Cosine Similarity k-Nearest
Neighbors (kNN) trained on empirical benchmark cohorts. Provides upward-biased
difficulty routing for ambiguous middle-band prompts where simple keywords fall short.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

HERE = Path(__file__).resolve().parent
DIMENSION = 256
CONFIDENCE_THRESHOLD = 0.65
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


class EffortScorer:
    def __init__(self, dim: int = DIMENSION, threshold: float = CONFIDENCE_THRESHOLD):
        self.dim = dim
        self.threshold = threshold
        self.vectors = None
        self.labels = []
        self._load_seed_data()

    def _load_seed_data(self):
        """Load training prototypes from saved benchmark records or built-in cohorts."""
        samples = []

        # 1. Try loading cached empirical benchmark file
        cached_path = Path.home() / ".local" / "state" / "dl-ai" / "benchmarks" / "effort_matrix.json"
        if cached_path.is_file():
            try:
                data = json.loads(cached_path.read_text(encoding="utf-8"))
                for rec in data.get("records", []):
                    samples.append((rec["prompt"], rec["target"]))
            except Exception:
                samples = []

        # 2. Fallback to built-in cohort items in bench_effort_matrix
        if not samples:
            try:
                import bench_effort_matrix as bem
                for it in bem.VOICE_HOUSEHOLD:
                    samples.append((it["prompt"], it["target"]))
                for it in bem.CHAT_EXPLAIN:
                    samples.append((it["prompt"], it["target"]))
                for it in bem.CODING_AGENT:
                    samples.append((it["prompt"], it["target"]))
            except Exception:
                pass

        if not samples or np is None:
            return

        vec_list = []
        label_list = []
        for prompt, target in samples:
            v = vectorize(prompt, self.dim)
            if v is not None:
                vec_list.append(v)
                label_list.append(target)

        if vec_list:
            self.vectors = np.vstack(vec_list)
            self.labels = label_list

    def predict(self, prompt: str, k: int = 3) -> tuple[str, float]:
        """Classify prompt difficulty into (level, confidence).

        If confidence < threshold (0.65), defaults to 'high' (safety upward bias).
        """
        if np is None or self.vectors is None or len(self.labels) == 0:
            return "high", 0.0

        q = vectorize(prompt, self.dim)
        if q is None:
            return "high", 0.0

        # Cosine similarities
        sims = np.dot(self.vectors, q)
        top_indices = np.argsort(sims)[::-1][:k]

        weights: dict[str, float] = {"none": 0.0, "low": 0.0, "medium": 0.0, "high": 0.0}
        total_weight = 0.0
        for idx in top_indices:
            s = float(sims[idx])
            if s > 0:
                lvl = self.labels[idx]
                weights[lvl] = weights.get(lvl, 0.0) + s
                total_weight += s

        if total_weight <= 1e-6:
            return "high", 0.0

        best_lvl = max(weights.items(), key=lambda kv: kv[1])[0]
        confidence = round(weights[best_lvl] / total_weight, 3)

        # Safety upward bias guarantee: ambiguous or low confidence queries default to high
        if confidence < self.threshold:
            return "high", confidence
        return best_lvl, confidence

    def score_difficulty(self, prompt: str) -> tuple[str, float]:
        """Alias for predict."""
        return self.predict(prompt)


# Module-level singleton
_SCORER: EffortScorer | None = None


def get_scorer() -> EffortScorer:
    global _SCORER
    if _SCORER is None:
        _SCORER = EffortScorer()
    return _SCORER


def predict(prompt: str) -> tuple[str, float]:
    return get_scorer().predict(prompt)


def score_difficulty(prompt: str) -> tuple[str, float]:
    return get_scorer().score_difficulty(prompt)
