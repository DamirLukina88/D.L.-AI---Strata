"""Request timings, token counts and speed figures reported with a response.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from serve.tunables import RATE_MIN_SPAN_S


def prompt_tokens_seen(prompt_tokens: int, last: dict) -> int:
    """#471: the prompt tokens a request got through - all of them, unless the engine's DONE line says a cancel stopped
    its prompt read part-way (then the reused ones plus those read).  /metrics' history and totals count these, so a
    cancelled read is neither recorded as the whole prompt nor given a rate from tokens it never read.  An engine
    before 0.1.36 does not say (no `prompt_read`): the whole prompt, as before."""
    read = last.get("prompt_read")
    if read is None or last.get("finish") != "cancel":
        return prompt_tokens
    return min(prompt_tokens, int(last.get("reused") or 0) + int(read))


def carry_leg(carry: dict, leg: dict) -> None:
    """#1869: a request that decoded in a batch slot and went back to the solo path ends with the solo path's DONE, which
    replaces the engine's figures: keep the slot leg's decode time, tokens and prompt figures to add to it."""
    carry["decode_ms"] = carry.get("decode_ms", 0.0) + float(leg.get("decode_ms") or 0.0)
    carry["generated"] = carry.get("generated", 0) + int(leg.get("generated") or 0)
    carry.setdefault("prompt_ms", float(leg.get("prompt_ms") or 0.0))
    if leg.get("prompt_read") is not None:
        carry.setdefault("prompt_read", int(leg["prompt_read"]))


def add_carry(carry: dict, last: dict) -> dict:
    """The request's totals: the earlier legs' decode time and tokens plus the final one's; the prompt figures of the leg
    that read the prompt (the solo continuation reads next to nothing)."""
    out = {**last, "decode_ms": float(last.get("decode_ms") or 0.0) + carry.get("decode_ms", 0.0),
           "generated": int(last.get("generated") or 0) + carry.get("generated", 0),
           "prompt_ms": max(float(last.get("prompt_ms") or 0.0), carry.get("prompt_ms", 0.0))}
    if "prompt_read" in carry:
        out["prompt_read"] = carry["prompt_read"]
    return out


def answer_speed(last: dict, generated: int, wall_s: float | None = None) -> float | None:
    """The one definition of "answer speed" (upstream 0.2.2, fccfd343): every token the model produced (thinking and answer,
    the tokens it kept - not the MTP drafts it threw away) over the engine's decode time.  Only an engine that sent no DONE
    falls back to the server's clock from the first token, and a clock younger than RATE_MIN_SPAN_S says nothing (it printed
    1000000 tok/s for a one-token reply).  Prompt reading is never in it."""
    produced, decode_ms = last.get("generated"), last.get("decode_ms")
    if produced and produced >= 2 and decode_ms and decode_ms > 0:       # one token has no first-to-last span (a 1-token probe printed 1,250 tok/s)
        return round(produced / (decode_ms / 1000), 1)
    if generated and wall_s is not None and wall_s >= RATE_MIN_SPAN_S:
        return round(generated / wall_s, 1)
    return None


def request_timings(prompt_tokens: int, generated: int, last: dict) -> dict | None:
    """One request's `timings` in llama.cpp's names (what its clients show as speed), from the engine's own clock
    (StrataEngine.last): prompt_n is what was read, cache_n what the conversation cache already held.  None when the
    engine keeps no clock (MockEngine)."""
    if last.get("prompt_ms") is None:
        return None
    cache_n = int(last.get("reused") or 0)
    if last.get("prompt_read") is not None and last.get("finish") != "cancel":
        # #1870: the engine says how many prompt tokens it read: the slot's own session may have held the rest
        # (not the conversation cache), so the rate is not made of tokens it never read
        cache_n = max(cache_n, max(0, prompt_tokens - int(last["prompt_read"])))
    prompt_n, prompt_ms, decode_ms = max(0, prompt_tokens - cache_n), float(last["prompt_ms"]), last.get("decode_ms")
    decoded = last.get("generated")          # explicit zero and missing native work are not the API's output count
    return {"cache_n": cache_n, "prompt_n": prompt_n, "prompt_ms": round(prompt_ms, 1),
            "prompt_per_token_ms": round(prompt_ms / prompt_n, 3) if prompt_n else None,
            "prompt_per_second": round(prompt_n / (prompt_ms / 1000), 1) if prompt_n and prompt_ms > 0 else None,
            "predicted_n": generated, "predicted_ms": round(decode_ms, 1) if decode_ms is not None else None,
            "predicted_per_token_ms": round(decode_ms / decoded, 3) if decoded else None,
            "predicted_per_second": round(decoded / (decode_ms / 1000), 1) if decoded and decode_ms and decode_ms > 0 else None,
            # the speculative drafts, as llama.cpp names them (from PR #83, @mikicvi): only when the engine reported them
            **({"draft_n": int(last["drafts_offered"]), "draft_n_accepted": int(last["drafts_accepted"])}
               if last.get("drafts_offered") is not None else {})}


def request_stats(segments: list[dict]) -> dict:
    """Keep input/cache accounting at the original API boundary and total native work across continuations."""
    if not segments:
        return {}
    result = dict(segments[-1])
    for key in ("reused", "prompt_read"):
        if key in segments[0]:
            result[key] = segments[0][key]
        else:
            result.pop(key, None)
    for key in ("prompt_ms", "decode_ms", "generated", "drafts_offered", "drafts_accepted",
                "hits", "lookups", "offloaded", "ram_blobs", "file_blobs", "file_mb", "experts_streamed"):
        if key in ("decode_ms", "generated") and any(segment.get(key) is None for segment in segments):
            result[key] = None
        elif any(segment.get(key) is not None for segment in segments):
            result[key] = sum(segment.get(key) or 0 for segment in segments)
    return result


def prefill_leg_stats(earlier: list[dict], last: dict, prompt_tokens: int) -> dict:
    """Total yielded reads once, retaining only reuse from before this API request."""
    legs = [*earlier, last]
    total = request_stats(legs)
    if all(leg.get("prompt_read") is not None for leg in legs):
        fresh = max(0, prompt_tokens - int(total.get("reused") or 0))
        total["prompt_read"] = min(fresh, sum(int(leg["prompt_read"]) for leg in legs))
    return total
