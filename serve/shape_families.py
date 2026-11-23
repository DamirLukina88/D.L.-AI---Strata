"""What serve needs from upstream's strata_control/hy4_family.py and inkling_family.py (this fork has no strata_control):
the default drafter of each shape engine and Inkling-2-Mini's most parallel requests.  Same names as upstream."""
from __future__ import annotations


class _Family:
    def __init__(self, default_drafter: str, max_parallel: int = 1):
        self.DEFAULT_DRAFTER = default_drafter
        self.MAX_PARALLEL = max_parallel


hy4_family = _Family("dfly2")            # strata_control/hy4_family.py DEFAULT_DRAFTER
inkling_family = _Family("dspark", 64)   # strata_control/inkling_family.py DEFAULT_DRAFTER, inkling_fit.MAX_PARALLEL


def top_logprobs(req: dict):
    """serve/server_parts/core.py top_logprobs, as far as this fork goes: it has no logprobs support, so any ask counts."""
    if not isinstance(req, dict):
        return None
    if req.get("logprobs") not in (None, False):
        return req.get("top_logprobs") or 0
    return None
