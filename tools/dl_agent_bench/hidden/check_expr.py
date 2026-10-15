"""Hidden checks for the expr task: python check_expr.py <workspace>.  Prints one JSON line."""
import importlib.util
import json
import random
import re
import sys
from pathlib import Path


def gen(rnd, depth=0):
    """A random valid expression; Python evaluates it with the same rules the task asks for."""
    r = rnd.random()
    if depth > 3 or r < 0.3:
        n = rnd.choice([str(rnd.randrange(0, 50)), f"{rnd.randrange(0, 20)}.{rnd.randrange(0, 100)}"])
        return n
    if r < 0.4:
        return "-" + gen(rnd, depth + 1)
    if r < 0.55:
        return "(" + gen(rnd, depth + 1) + ")"
    sp = rnd.choice(["", " "])
    return gen(rnd, depth + 1) + sp + rnd.choice("+-*/") + sp + gen(rnd, depth + 1)


ws = Path(sys.argv[1])
results = {}
try:
    src = (ws / "calc.py").read_text()
    spec = importlib.util.spec_from_file_location("calc", ws / "calc.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def close(a, b):
        return abs(a - b) <= 1e-9 * max(1.0, abs(b))

    def raises(s, exc=ValueError):
        try:
            m.evaluate(s)
        except exc:
            return True
        except Exception:  # noqa: BLE001
            return False
        return False

    rnd = random.Random(7)
    rand = []
    while len(rand) < 400:
        e = gen(rnd)
        try:
            rand.append((e, eval(e)))  # noqa: S307 - the reference, on expressions this script made
        except ZeroDivisionError:
            pass
    cases = {
        "precedence": lambda: close(m.evaluate("2+3*4"), 14) and close(m.evaluate("2*3+4"), 10),
        "left_to_right": lambda: close(m.evaluate("10-4-3"), 3) and close(m.evaluate("16/4/2"), 2),
        "parentheses": lambda: close(m.evaluate("(2+3)*4"), 20) and close(m.evaluate("((1))"), 1),
        "unary_minus": lambda: close(m.evaluate("-3+5"), 2) and close(m.evaluate("2*-3"), -6)
        and close(m.evaluate("--4"), 4) and close(m.evaluate("-(2+3)"), -5),
        "decimals_and_spaces": lambda: close(m.evaluate("  1.5 * 2 "), 3) and close(m.evaluate("7/2"), 3.5),
        "division_by_zero": lambda: raises("1/0", ZeroDivisionError) and raises("3/(2-2)", ZeroDivisionError),
        "rejects_bad_input": lambda: all(raises(s) for s in
                                         ("", "1+", "(1", "1)", "2 3", "a", "1+*2", "()", "1..2", "3+(4", "*2")),
        "random_vs_reference": lambda: all(close(m.evaluate(e), v) for e, v in rand),
        "no_eval_or_exec": lambda: not re.search(r"(?<![\w.])(eval|exec|compile)\s*\(|^\s*(import|from)\s+ast\b", src, re.M),
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
