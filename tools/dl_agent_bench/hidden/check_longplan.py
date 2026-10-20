"""Hidden checks for the longplan task: python check_longplan.py <workspace>.  Prints one JSON line.

One case per function of the 12-step plan, so the score says how far the agent got, not only whether it finished."""
import importlib.util
import json
import sys
from pathlib import Path

ws = Path(sys.argv[1])
results = {}


def raises(fn, *a, exc=ValueError):
    try:
        fn(*a)
    except exc:
        return True
    except Exception:  # noqa: BLE001 - the wrong exception is a failure
        return False
    return False


try:
    spec = importlib.util.spec_from_file_location("mathkit", ws / "mathkit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
except Exception as e:  # noqa: BLE001
    print(json.dumps({"import": f"{type(e).__name__}: {e}"}))
    sys.exit(0)

CASES = {
    "is_prime": lambda: [m.is_prime(n) for n in (-7, 0, 1, 2, 3, 4, 17, 25, 97, 7919)]
    == [False, False, False, True, True, False, True, False, True, True],
    "gcd": lambda: (m.gcd(12, 18), m.gcd(0, 5), m.gcd(-4, 6), m.gcd(0, 0)) == (6, 5, 2, 0),
    "lcm": lambda: (m.lcm(4, 6), m.lcm(0, 5), m.lcm(-3, 5)) == (12, 0, 15),
    "fib": lambda: [m.fib(n) for n in (0, 1, 2, 10, 50)] == [0, 1, 1, 55, 12586269025] and raises(m.fib, -1),
    "factorial": lambda: (m.factorial(0), m.factorial(5), m.factorial(20)) == (1, 120, 2432902008176640000)
    and raises(m.factorial, -1),
    "digit_sum": lambda: (m.digit_sum(0), m.digit_sum(12345), m.digit_sum(-987)) == (0, 15, 24),
    "is_palindrome": lambda: (m.is_palindrome("A man, a plan, a canal: Panama"), m.is_palindrome(""),
                              m.is_palindrome("ab"), m.is_palindrome("No 'x' in Nixon")) == (True, True, False, True),
    "count_vowels": lambda: (m.count_vowels("Hello World"), m.count_vowels(""), m.count_vowels("AEIOUy"))
    == (3, 0, 5),
    "rle_encode": lambda: (m.rle_encode(""), m.rle_encode("aaab"), m.rle_encode("abc"),
                           m.rle_encode("zzzzzzzzzzzz")) == ("", "3a1b", "1a1b1c", "12z"),
    "rle_decode": lambda: (m.rle_decode(""), m.rle_decode("3a1b"), m.rle_decode("12z"), m.rle_decode("1a1b1c"))
    == ("", "aaab", "z" * 12, "abc") and raises(m.rle_decode, "a3"),
    "chunk": lambda: (m.chunk([1, 2, 3, 4, 5], 2), m.chunk([], 3), m.chunk([1, 2], 5))
    == ([[1, 2], [3, 4], [5]], [], [[1, 2]]) and raises(m.chunk, [1], 0),
    "flatten": lambda: (m.flatten([1, [2, [3, [4]], 5], []]), m.flatten([]), m.flatten([[[]]]))
    == ([1, 2, 3, 4, 5], [], []),
}
for name, case in CASES.items():
    try:
        results[name] = bool(getattr(m, name, None)) and bool(case())
    except Exception:  # noqa: BLE001
        results[name] = False
print(json.dumps(results))
