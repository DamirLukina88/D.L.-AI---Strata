"""Hidden checks for the intervals task: python check_intervals.py <workspace>.  Prints one JSON line."""
import copy
import importlib.util
import json
import random
import sys
from pathlib import Path


def reference(xs):
    for a, b in xs:
        if a > b:
            raise ValueError
    out = []
    for a, b in sorted((a, b) for a, b in xs if a < b):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


ws = Path(sys.argv[1])
results = {}
try:
    spec = importlib.util.spec_from_file_location("intervals", ws / "intervals.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rnd = random.Random(11)
    rand = [[(a, a + rnd.randrange(0, 6)) for a in (rnd.randrange(-20, 20) for _ in range(rnd.randrange(0, 9)))]
            for _ in range(300)]

    def same(xs):
        return [tuple(x) for x in m.merge(xs)] == reference(xs)

    def raises(xs):
        try:
            m.merge(xs)
        except ValueError:
            return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def not_mutated():
        xs = [(5, 7), (1, 3), (3, 4)]
        before = copy.deepcopy(xs)
        m.merge(xs)
        return xs == before

    cases = {
        "empty_list": lambda: list(m.merge([])) == [],
        "touching_merge": lambda: same([(1, 3), (3, 5)]),
        "overlap_unsorted": lambda: same([(6, 8), (1, 4), (2, 5)]),
        "empty_intervals_dropped": lambda: same([(2, 2), (4, 4), (1, 3)]),
        "contained": lambda: same([(1, 10), (2, 3), (4, 5)]),
        "negative_values": lambda: same([(-5, -1), (-1, 0), (3, 4)]),
        "start_after_end_raises": lambda: raises([(1, 2), (5, 3)]),
        "input_not_modified": not_mutated,
        "random_vs_reference": lambda: all(same(xs) for xs in rand),
    }
    for name, fn in cases.items():
        try:
            results[name] = bool(fn())
        except Exception as e:  # noqa: BLE001
            results[name] = False
            results[name + "_error"] = repr(e)[:200]
except Exception as e:  # noqa: BLE001
    results["import_error"] = repr(e)[:200]
print(json.dumps(results))
