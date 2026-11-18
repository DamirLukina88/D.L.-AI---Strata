"""The benches' --timeout was checked only when no event came for a second, and a model that thinks or writes sends
one every chunk: a long turn was never interrupted and was recorded as a normal one (no timed_out).

    python -m unittest tools.test_bench_timeouts   (from the repo root, with tools/ on PYTHONPATH)
"""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ray_toolchoice_bench  # noqa: E402


class StreamingLive:
    """A session that thinks forever (an event every 20 ms) until it is interrupted."""

    def __init__(self):
        self.q, self.sent, self.stop = queue.Queue(), [], threading.Event()
        threading.Thread(target=self.stream, daemon=True).start()

    def stream(self):
        while not self.stop.is_set():
            self.q.put({"type": "thinking", "text": "hmm "})
            time.sleep(0.02)
        self.q.put({"type": "turn_end"})

    def send(self, **op):
        self.sent.append(op)
        if op.get("op") == "interrupt":
            self.stop.set()


class BenchTimeouts(unittest.TestCase):
    def test_a_streaming_turn_is_interrupted_at_the_limit(self):
        live = StreamingLive()
        t0 = time.monotonic()
        rec = ray_toolchoice_bench.one_turn(live, "17 times 23", timeout=0.5)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertTrue(rec.get("timed_out"))
        self.assertIn({"op": "interrupt"}, live.sent)


if __name__ == "__main__":
    unittest.main()
