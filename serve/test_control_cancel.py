"""#879: a Stop that arrives while the engine reads the prompt (PP lines, no tokens yet) is sent at once, not after the
first token."""
import os
import queue
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serve import server  # noqa: E402


class ControlCancelTest(unittest.TestCase):
    def _engine(self, lines):
        eng = object.__new__(server.StrataEngine)
        eng.lines = queue.Queue()
        for l in lines:
            eng.lines.put(l)
        eng.sent = []
        eng._send = eng.sent.append
        eng._ctl_mode = "solo"
        eng._ctl_result = None
        eng.progress = None
        eng.prefill_tok_s_mean = None
        eng._last_done = None
        eng._parse_done = lambda line: None
        return eng

    def test_stop_during_prompt_read(self):
        cancel = threading.Event()
        eng = self._engine(["PP 256 4096 1 100.0", "PP 512 4096 2 100.0", "PP 768 4096 3 100.0", "DONE 0"])
        gen = eng._control(cancel, lambda t: None)
        self.assertIsNone(next(gen))               # first PP line, nothing cancelled yet
        self.assertEqual(eng.sent, [])
        cancel.set()
        self.assertIsNone(next(gen))               # the next PP line: STOP goes out now
        self.assertEqual(eng.sent, ["STOP"])
        self.assertIsNone(next(gen))
        self.assertEqual(eng.sent, ["STOP"])       # once

    def test_no_stop_without_cancel(self):
        eng = self._engine(["PP 256 4096 1 100.0", "DONE 0"])
        for _ in eng._control(threading.Event(), lambda t: None):
            pass
        self.assertEqual(eng.sent, [])


class FakeProc:
    def __init__(self):
        self.killed = False
        self.pid = os.getpid()
        self.stdin = self
        self.written = []

    def write(self, s):
        self.written.append(s)

    def flush(self):
        pass

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


class StopThatDoesNotEndTest(unittest.TestCase):
    """2026-11-15: an engine that does not end a stopped request (reading its prompt from disk) is ended after
    ENGINE_CANCEL_S, so the prompt sent again does not wait behind it."""

    def test_ended_after_the_cancel_limit(self):
        import time
        eng = object.__new__(server.StrataEngine)
        eng.lines = queue.Queue()
        for l in ("PP 256 4096 1 100.0", "PP 512 4096 2 100.0"):
            eng.lines.put(l)
        eng.proc, eng.batch, eng.can_stop, eng.silence_s = FakeProc(), 0, True, 300.0
        eng.alive = lambda: True
        eng.sampling_keys = lambda s: ""
        cancel = threading.Event()
        old = server.ENGINE_CANCEL_S
        server.ENGINE_CANCEL_S = 0.3
        try:
            gen = eng.generate([1, 2, 3], 16, {}, cancel)
            self.assertIsNone(next(gen))
            cancel.set()
            t0 = time.monotonic()
            with self.assertRaises(server.EngineSilent):
                for _ in gen:
                    pass
            self.assertLess(time.monotonic() - t0, 5.0)
        finally:
            server.ENGINE_CANCEL_S = old
        self.assertIn("STOP\n", eng.proc.written)
        self.assertTrue(eng.proc.killed)


if __name__ == "__main__":
    unittest.main()
