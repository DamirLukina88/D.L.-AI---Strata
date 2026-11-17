"""force_restart (/restart, /v1/restart, /switch_model) must not reset the queued counter under requests that are
still waiting: each waiter takes itself off when it gets its turn, so a reset left it at -1, and unload() (idle
unload, /unload, /v1/load) answered "busy" from then on.

Run from the repo root: python -m unittest serve.test_force_restart_queue
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ForceRestartKeepsTheQueue(unittest.TestCase):
    def test_a_waiting_request_is_counted_once(self):
        tok = ByteTokenizer()
        svc = Service(MockEngine(tok, "ok", max_context=4096), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        svc.lazy = True
        with mock.patch.object(svc, "loaded", return_value=False), mock.patch.object(svc, "ensure_loaded"):
            svc.fifo.acquire()                               # a request is running
            waiter = threading.Thread(target=svc.load)       # another waits for the engine
            waiter.start()
            for _ in range(200):
                if svc.status["queued"] == 1:
                    break
                time.sleep(0.01)
            self.assertEqual(svc.status["queued"], 1)
            svc.force_restart()
            svc.fifo.release()
            waiter.join(5)
        self.assertEqual(svc.status["queued"], 0)


if __name__ == "__main__":
    unittest.main()
