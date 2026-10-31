"""Hidden checks for the cron task: python check_cron.py <workspace>.  Prints one JSON line.  The expected values come
from the reference below (a brute-force minute walk), so cases with new inputs catch answers special-cased to the
visible tests."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _field(text, lo, hi):
    out = set()
    for part in text.split(","):
        rng, _, step = part.partition("/")
        step = int(step) if step else 1
        if step < 1:
            raise ValueError(part)
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-"))
        else:
            a = b = int(rng)
        if not lo <= a <= b <= hi:
            raise ValueError(part)
        out.update(range(a, b + 1, step))
    return out


def reference(expr, after):
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(expr)
    mins, hours, doms, months, dows = (_field(f, lo, hi) for f, (lo, hi) in zip(fields, RANGES))
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366 * 5):
        dom_ok, dow_ok = t.day in doms, (t.weekday() + 1) % 7 in dows
        day = (dom_ok or dow_ok) if fields[2] != "*" and fields[4] != "*" else (dom_ok and dow_ok)
        if t.minute in mins and t.hour in hours and t.month in months and day:
            return t
        t += timedelta(minutes=1)
    raise ValueError("no run in 5 years")


CASES = {
    "visible_every_minute": ("* * * * *", datetime(2026, 3, 1, 10, 0, 30)),
    "visible_leap_day": ("0 12 29 2 *", datetime(2026, 3, 1)),
    "new_fixed_time": ("45 23 * * *", datetime(2026, 7, 4, 23, 50)),
    "new_step_minutes": ("*/7 * * * *", datetime(2026, 7, 4, 10, 58)),
    "new_month_rollover": ("0 0 1 * *", datetime(2026, 12, 15, 8, 0)),
    "new_list": ("5,35 2,14 * * *", datetime(2026, 7, 4, 14, 35)),
    "new_range_step": ("0 1-23/6 * * *", datetime(2026, 7, 4, 13, 0)),
    "new_weekend": ("30 9 * * 0,6", datetime(2026, 7, 6, 12, 0)),
    "new_dom_or_dow": ("0 6 1 * 1", datetime(2026, 7, 2, 0, 0)),
    "new_month_and_dom": ("15 10 31 4,6,7 *", datetime(2026, 4, 2)),
    "new_year_end": ("59 23 31 12 *", datetime(2026, 12, 31, 23, 59)),
}
BAD = ["* * * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 7", "5-1 * * * *", "*/0 * * * *", "x * * * *"]

if __name__ == "__main__":
    results = {}
    try:
        spec = importlib.util.spec_from_file_location("schedule", Path(sys.argv[1]) / "schedule.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        for name, (expr, after) in CASES.items():
            try:
                results[name] = m.next_run(expr, after) == reference(expr, after)
            except Exception as e:  # noqa: BLE001
                results[name] = False
                results[name + "_error"] = repr(e)[:200]
        rejected = 0
        for bad in BAD:
            try:
                m.next_run(bad, datetime(2026, 3, 1))
            except ValueError:
                rejected += 1
            except Exception:  # noqa: BLE001
                pass
        results["rejects_bad_expressions"] = rejected == len(BAD)
    except Exception as e:  # noqa: BLE001
        results["import_error"] = repr(e)[:200]
    print(json.dumps(results))
