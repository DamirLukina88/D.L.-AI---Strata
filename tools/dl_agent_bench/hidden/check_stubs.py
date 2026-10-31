"""Hidden checks for the stubs task: python check_stubs.py <workspace>.  Prints one JSON line."""
import importlib.util
import json
import sys
from pathlib import Path

results = {}
try:
    spec = importlib.util.spec_from_file_location("textkit", Path(sys.argv[1]) / "textkit.py")
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)

    def raises(fn, *a):
        try:
            fn(*a)
        except ValueError:
            return True
        return False

    cases = {
        "slugify": lambda: t.slugify("--A  b__C 9--") == "a-b-c-9" and t.slugify("!!!") == "",
        "is_anagram": lambda: t.is_anagram("Listen", "Silent") and not t.is_anagram("aab", "abb"),
        "caesar": lambda: t.caesar("abc XYZ", -1) == "zab WXY" and t.caesar("Hi!", 52) == "Hi!",
        "rle_encode": lambda: t.rle_encode("") == "" and t.rle_encode("abbcccccccccccc") == "1a2b12c",
        "rle_decode": lambda: t.rle_decode("12a1b") == "a" * 12 + "b" and raises(t.rle_decode, "a3")
                              and raises(t.rle_decode, "3"),
        "word_freq": lambda: t.word_freq("Don't stop, don't! 3 cats") == {"don't": 2, "stop": 1, "cats": 1},
        "truncate": lambda: t.truncate("abc", 3) == "abc" and t.truncate("abcd", 1) == "…" and raises(t.truncate, "a", 0),
        "camel_to_snake": lambda: t.camel_to_snake("parseHTTPResponse") == "parse_http_response"
                                  and t.camel_to_snake("simple") == "simple",
        "snake_to_camel": lambda: t.snake_to_camel("__get__user_id_") == "getUserId",
        "common_prefix": lambda: t.common_prefix([]) == "" and t.common_prefix(["same", "same"]) == "same"
                                 and t.common_prefix(["a", "b"]) == "",
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
