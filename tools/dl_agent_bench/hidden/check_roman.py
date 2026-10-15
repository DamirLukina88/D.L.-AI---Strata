"""Hidden checks for the roman task: python check_roman.py <workspace>.  Prints one JSON line."""
import importlib.util
import itertools
import json
import sys
from pathlib import Path

VALS = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def to_roman(n):
    out = ""
    for v, s in VALS:
        while n >= v:
            out, n = out + s, n - v
    return out


CANON = {to_roman(n): n for n in range(1, 4000)}
ws = Path(sys.argv[1])
results = {}
try:
    spec = importlib.util.spec_from_file_location("roman", ws / "roman.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def rejects(s):
        try:
            m.to_int(s)
        except ValueError:
            return True
        except Exception:  # noqa: BLE001 - the wrong exception is a failure
            return False
        return False

    # every string over IVXLCDM up to 4 letters that is not the standard form of a number must be refused
    bad = ["".join(p) for k in range(1, 5) for p in itertools.product("IVXLCDM", repeat=k)
           if "".join(p) not in CANON]
    cases = {
        "all_1_to_3999": lambda: all(m.to_int(s) == n for s, n in CANON.items()),
        "rejects_empty": lambda: rejects(""),
        "rejects_lowercase": lambda: rejects("xiv"),
        "rejects_IIII": lambda: rejects("IIII"),
        "rejects_VX_IC_XM": lambda: all(rejects(s) for s in ("VX", "IC", "XM", "VV", "LL", "DD")),
        "rejects_MMMM": lambda: rejects("MMMM"),
        "rejects_other_letters": lambda: rejects("XIZ") and rejects(" X") and rejects("X "),
        "rejects_all_noncanonical_up_to_4": lambda: all(rejects(s) for s in bad),
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
