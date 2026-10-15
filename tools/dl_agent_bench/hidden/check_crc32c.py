"""Hidden checks for the crc32c task: python check_crc32c.py <workspace>.  Prints one JSON line."""
import importlib.util
import json
import random
import sys
from pathlib import Path


def reference(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


ws = Path(sys.argv[1])
results = {}
try:
    spec = importlib.util.spec_from_file_location("checksum", ws / "checksum.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rnd = random.Random(7)
    samples = [bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 300))) for _ in range(50)]
    cases = {
        "check_value_123456789": lambda: m.crc32c(b"123456789") == 0xE3069283,
        "empty_is_0": lambda: m.crc32c(b"") == 0,
        "32_zero_bytes": lambda: m.crc32c(bytes(32)) == 0x8A9136AA,      # RFC 3720 B.4
        "32_ff_bytes": lambda: m.crc32c(b"\xff" * 32) == 0x62A8AB43,     # RFC 3720 B.4
        "random_vs_reference": lambda: all(m.crc32c(s) == reference(s) for s in samples),
        "accepts_bytearray": lambda: m.crc32c(bytearray(b"abc")) == reference(b"abc"),
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
