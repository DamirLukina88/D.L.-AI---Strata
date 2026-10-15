"""Hidden checks for the bugfix task: python check_bugfix.py <workspace>.  Prints one JSON line."""
import importlib.util
import json
import sys
from pathlib import Path

ws = Path(sys.argv[1])
results = {}
try:
    spec = importlib.util.spec_from_file_location("textstats", ws / "textstats.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    cases = {
        "empty_is_0": lambda: m.word_count("") == 0,
        "spaces_only_is_0": lambda: m.word_count("   ") == 0,
        "mixed_whitespace": lambda: m.word_count("a  b\nc\td") == 4,
        "plain_count": lambda: m.word_count("the quick brown fox") == 4,
        "ties_alphabetical": lambda: m.top_words("pear apple fig", 3) == ["apple", "fig", "pear"],
        "count_then_alpha": lambda: m.top_words("c b a c b", 3) == ["b", "c", "a"],
        "keeps_punct_and_case": lambda: m.top_words("Dog. dog, CAT cat! dog", 2) == ["dog", "cat"],
        "n_respected": lambda: m.top_words("x y z", 2) == ["x", "y"],
    }
    for name, fn in cases.items():
        try:
            results[name] = bool(fn())
        except Exception as e:  # noqa: BLE001 - any failure is a failed case
            results[name] = False
            results[name + "_error"] = repr(e)[:200]
except Exception as e:  # noqa: BLE001
    results["import_error"] = repr(e)[:200]
print(json.dumps(results))
