"""API latency report: reads data/requests.csv (one row per request, column `ms`) and prints p50, p95 and p99."""
import csv
import sys


def percentile(values: list[float], p: float) -> float:
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main(path: str = "data/requests.csv") -> None:
    with open(path, newline="") as f:
        ms = [float(row["ms"]) for row in csv.DictReader(f)]
    print(f"{len(ms)} requests")
    for p in (50, 95, 99):
        print(f"p{p}: {percentile(ms, p):.1f} ms")


if __name__ == "__main__":
    main(*sys.argv[1:])
