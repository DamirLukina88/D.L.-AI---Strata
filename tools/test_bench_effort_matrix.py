"""tools/test_bench_effort_matrix.py - Unit tests for tools/bench_effort_matrix.py."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bench_effort_matrix as bem


class TestBenchEffortMatrix(unittest.TestCase):
    def test_cohort_item_counts(self):
        self.assertEqual(len(bem.VOICE_HOUSEHOLD), 25)
        self.assertEqual(len(bem.CHAT_EXPLAIN), 25)
        self.assertEqual(len(bem.CODING_AGENT), 25)

    def test_offline_benchmark_computation(self):
        bench = bem.EffortMatrixBench(mode="offline")
        cohorts = {
            "Voice": bem.VOICE_HOUSEHOLD[:5],
            "Chat": bem.CHAT_EXPLAIN[:5],
            "Coding": bem.CODING_AGENT[:5],
        }
        records = bench.run_all(cohorts)
        self.assertEqual(len(records), 15)

        summary = bench.compute_summary()
        self.assertEqual(summary["total_prompts"], 15)
        self.assertGreaterEqual(summary["sufficiency_pct"], 90.0)
        self.assertGreaterEqual(summary["savings_vs_fixed_high_pct"], 20.0)

        report = bench.render_report()
        self.assertIn("# Empirical Reasoning Effort Matrix Benchmark Report", report)
        self.assertIn("Voice", report)
        self.assertIn("Coding", report)

    def test_main_cli_offline_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out_matrix.json"
            ret = bem.main(["--offline", "--out", str(out_file), "--quiet"])
            self.assertEqual(ret, 0)
            self.assertTrue(out_file.is_file())
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["mode"], "offline")
            self.assertEqual(len(data["records"]), 75)
            self.assertEqual(data["summary"]["sufficiency_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
