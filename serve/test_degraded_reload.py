"""2026-11-15: an engine that started short of memory (the memory guard kept part of the experts in RAM and reads the
rest from disk) says so in /health and is started again when it is idle and the memory is free."""
import os
import tempfile
import threading
import time
import types
import unittest

from serve.server import Service, degraded_start

WARN = ("strata generate: WARNING: the whole resident RAM mode does not fit (FileExpertSource: resident complement "
        "16.41 GiB exceeds available RAM (18.09 GiB) minus the 4 GiB safety headroom; 16.6 GiB of the RAM is file "
        "cache (earlier runs' model files ... (or start strata serve with X=1 so it releases them)); 13.84 GiB of the "
        "experts the GPU does not hold, the hottest by the expert profile, are kept in RAM and the rest are read from "
        "the model folder through the OS file cache\n")


class DegradedStart(unittest.TestCase):
    def test_reads_only_this_start(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write("[strata] engine started\n" + WARN)
            first = f.tell()
            f.write("[strata] engine started\nstrata serve: READY\n")
        try:
            d = degraded_start(f.name, 0)
            self.assertEqual((d["wanted_gib"], d["kept_gib"]), (16.41, 13.84))
            self.assertIsNone(degraded_start(f.name, first))
            self.assertIsNone(degraded_start(None, 0))
        finally:
            os.unlink(f.name)


class FakeEngine:
    def __init__(self, degraded):
        self.degraded, self.restarts = degraded, 0

    def alive(self):
        return True

    def restart(self):
        self.restarts += 1
        self.degraded = None


def service(degraded, last_request_ago=600.0, busy=False):
    svc = types.SimpleNamespace(engine=FakeEngine(degraded), fifo=threading.Lock(), status_lock=threading.Lock(),
                                status={"busy": busy, "queued": 0}, last_request_at=time.time() - last_request_ago,
                                started_at=0.0)
    return svc


class ReloadDegraded(unittest.TestCase):
    D = {"wanted_gib": 16.41, "kept_gib": 13.84, "since": 1.0}

    def run_(self, svc, avail):
        return Service.reload_degraded(svc, avail=lambda: avail)

    def test_reloads_when_idle_and_memory_is_free(self):
        svc = service(dict(self.D))
        self.assertEqual(self.run_(svc, 8.0), "reloaded")          # 8 + 13.84 >= 16.41 + 5
        self.assertEqual(svc.engine.restarts, 1)
        self.assertEqual(self.run_(svc, 8.0), "fine")

    def test_waits_for_memory_requests_and_the_gap(self):
        self.assertEqual(self.run_(service(dict(self.D)), 2.0), "no memory")
        self.assertEqual(self.run_(service(dict(self.D), busy=True), 8.0), "busy")
        self.assertEqual(self.run_(service(dict(self.D), last_request_ago=5.0), 8.0), "busy")
        svc = service(dict(self.D))
        svc._degraded_try = time.time()
        self.assertEqual(self.run_(svc, 8.0), "waiting")
        self.assertEqual(svc.engine.restarts, 0)

    def test_a_held_fifo_is_busy(self):
        svc = service(dict(self.D))
        svc.fifo.acquire()
        self.assertEqual(self.run_(svc, 8.0), "busy")


class StallLog(unittest.TestCase):
    def test_one_line_per_stall_with_the_image_flag(self):
        import json
        from serve import server
        with tempfile.TemporaryDirectory() as tmp:
            old = server.STALL_LOG
            server.STALL_LOG = server.Path(tmp) / "stalls.jsonl"
            try:
                eng = types.SimpleNamespace(progress=(800, 1200), cur_image=True, degraded=None)
                server.log_stall("ERR verify: timed out at layer 2\n", eng)
                rec = json.loads(server.STALL_LOG.read_text())
            finally:
                server.STALL_LOG = old
        self.assertEqual((rec["layer"], rec["prompt_tokens"], rec["image"], rec["degraded"]), (2, 1200, True, False))


if __name__ == "__main__":
    unittest.main()
