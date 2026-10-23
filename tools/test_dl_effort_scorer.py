"""tools/test_dl_effort_scorer.py - Unit tests for CPU semantic difficulty router."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dl_effort
import dl_effort_scorer


class TestDlEffortScorer(unittest.TestCase):
    def test_feature_vectorizer(self):
        v1 = dl_effort_scorer.vectorize("explain how speculative decoding works")
        v2 = dl_effort_scorer.vectorize("explain how speculative decoding works")
        self.assertIsNotNone(v1)
        self.assertIsNotNone(v2)
        # Deterministic vector equality
        self.assertTrue((v1 == v2).all())
        # L2 norm is ~1.0
        self.assertAlmostEqual(float(dl_effort_scorer.np.linalg.norm(v1)), 1.0, places=4)

    def test_scorer_predict_classes(self):
        cases = [
            ("turn on the kitchen light", "none"),
            ("pause the living room speaker", "none"),
            ("explain how speculative decoding works in LLMs", "medium"),
            ("debug why the socket connection times out on shutdown", "high"),
            ("fix race condition between Session.cancel and worker thread", "high"),
        ]
        for prompt, expected in cases:
            lvl, conf = dl_effort_scorer.predict(prompt)
            self.assertEqual(lvl, expected, f"Failed on {prompt!r} (got {lvl}, conf {conf})")
            self.assertGreaterEqual(conf, 0.65)

    def test_safety_upward_bias_for_ambiguous_prompts(self):
        ambiguous = "xyz qwerty random tokens 12345"
        lvl, conf = dl_effort_scorer.predict(ambiguous)
        self.assertEqual(lvl, "high")

    def test_inference_latency_under_two_milliseconds(self):
        # Warmup
        dl_effort_scorer.predict("warmup query")
        prompts = [
            "turn off the lights",
            "explain quantum entanglement",
            "fix the failing test in dl_effort",
            "who was the first president of the United States?",
        ]
        t0 = time.perf_counter()
        n = 100
        for i in range(n):
            dl_effort_scorer.predict(prompts[i % len(prompts)])
        t1 = time.perf_counter()
        avg_ms = ((t1 - t0) * 1000.0) / n
        self.assertLess(avg_ms, 2.0, f"Average latency too high: {avg_ms:.3f} ms")

    def test_semantic_flag_in_dl_effort_pick(self):
        prompt = "pause the living room speaker"
        # Without semantic: not in HOME_NOUNS, words=5, falls back to default high
        res_no_sem = dl_effort.pick(prompt, semantic=False)
        self.assertEqual(res_no_sem, ("high", "default"))

        # With semantic=True: routes to none via semantic scorer
        res_sem = dl_effort.pick(prompt, semantic=True)
        self.assertEqual(res_sem, ("none", "semantic none"))


if __name__ == "__main__":
    unittest.main()
