"""Splitting a bill between people, in cents."""


def split(total_cents: int, n: int) -> list[int]:
    """Split total_cents into n parts that differ by at most one cent and add up to exactly total_cents,
    larger parts first.  n < 1 or a negative total raises ValueError."""
    if n < 1:
        raise ValueError("n must be at least 1")
    if total_cents < 0:
        raise ValueError("total_cents must not be negative")
    base, extra = divmod(total_cents, n)
    return [base + 1] * extra + [base] * (n - extra)
