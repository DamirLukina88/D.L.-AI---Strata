"""tools/test_dl_router.py - Unit tests for shared CPU router (dl_router, dl_mcp_router, modes, fallback)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dl_effort  # noqa: E402
import dl_effort_scorer  # noqa: E402
import dl_mcp  # noqa: E402
import dl_mcp_router  # noqa: E402
import dl_router  # noqa: E402
import bench_router_ab  # noqa: E402
import router_gold  # noqa: E402

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

FAKE_MCP = str(HERE.parent / "serve" / "mcp_fake_server.py")


def _fake_server(**extra):
    return {"command": sys.executable, "args": [FAKE_MCP], "description": "a fake server", **extra}


class TestRouterModeAndPrepare(unittest.TestCase):
    def test_router_mode_resolution(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(dl_router.router_mode(), "rules")
            self.assertEqual(dl_router.router_mode("model2vec"), "model2vec")
            self.assertEqual(dl_router.router_mode("hybrid"), "hybrid")
            self.assertEqual(dl_router.router_mode("invalid"), "rules")

        with mock.patch.dict(os.environ, {"DL_SEMANTIC_ROUTER": "1"}, clear=True):
            self.assertEqual(dl_router.router_mode(), "hybrid")

        with mock.patch.dict(os.environ, {"DL_SEMANTIC_ROUTER": "1", "DL_ROUTER_MODE": "rules"}, clear=True):
            self.assertEqual(dl_router.router_mode(), "rules")

        with mock.patch.dict(os.environ, {"DL_ROUTER_MODE": "model2vec"}, clear=True):
            self.assertEqual(dl_router.router_mode(), "model2vec")
            self.assertEqual(dl_router.router_mode(subsystem="effort"), "model2vec")
            self.assertEqual(dl_router.router_mode(subsystem="mcp"), "model2vec")

        with mock.patch.dict(
            os.environ,
            {
                "DL_ROUTER_MODE": "model2vec",
                "DL_EFFORT_ROUTER_MODE": "hybrid",
                "DL_MCP_ROUTER_MODE": "rules",
            },
            clear=True,
        ):
            self.assertEqual(dl_router.router_mode(subsystem="effort"), "hybrid")
            self.assertEqual(dl_router.router_mode(subsystem="mcp"), "rules")
            self.assertEqual(dl_effort._resolve_router_mode(), "hybrid")

    def test_prepare_strips_code_and_long_pastes(self):
        self.assertEqual(dl_router.prepare(""), "")
        self.assertEqual(dl_router.prepare(None), "")  # type: ignore[arg-type]

        with_code = "please explain why this fails:\n```python\n" + "\n".join(f"x_{i} = {i}" for i in range(40)) + "\n```"
        cleaned = dl_router.prepare(with_code)
        self.assertIn("please explain why this fails:", cleaned)
        self.assertIn("[code]", cleaned)
        self.assertNotIn("x_39", cleaned)

        long_paste = "check this log please\n" + "\n".join(f"line {i}: ok" for i in range(25)) + "\nwhat happened?"
        cleaned_paste = dl_router.prepare(long_paste)
        self.assertIn("[pasted block]", cleaned_paste)
        self.assertIn("what happened?", cleaned_paste)
        self.assertNotIn("line 15: ok", cleaned_paste)

        very_long = "word " * 300
        self.assertLessEqual(len(dl_router.prepare(very_long, max_chars=120)), 120)

        tb_with_question = (
            "Traceback (most recent call last):\n"
            "  File \"/tmp/app.py\", line 10, in main\n"
            "    run_step()\n"
            "  File \"/tmp/app.py\", line 20, in run_step\n"
            "    raise ValueError('bad input data for test case')\n"
            "ValueError: bad input data for test case\n\n"
            "Please explain why this fails"
        )
        cleaned_tb = dl_router.prepare(tb_with_question)
        self.assertIn("[traceback]", cleaned_tb)
        self.assertIn("Please explain why this fails", cleaned_tb)
        self.assertNotIn("run_step()", cleaned_tb)


class TestMissingModelFallbackAndNotice(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()
        dl_mcp_router.clear_cache()

    def tearDown(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()
        dl_mcp_router.clear_cache()

    def test_missing_model_falls_back_to_rules_with_one_time_effort_notice(self):
        with mock.patch.dict(os.environ, {"DL_ROUTER_MODEL_DIR": "/nonexistent/m2v-model-dir"}):
            lvl1, rsn1 = dl_effort.pick("hello Ray", router_mode="model2vec")
            self.assertEqual((lvl1, rsn1), ("none", "small talk"))
            msg1 = dl_effort.describe_pick(lvl1, rsn1, 0)
            self.assertIn(dl_router.FALLBACK_NOTICE, msg1)

            lvl2, rsn2 = dl_effort.pick("turn off the kitchen lights", router_mode="model2vec")
            self.assertEqual((lvl2, rsn2), ("none", "home command"))
            msg2 = dl_effort.describe_pick(lvl2, rsn2, 0)
            self.assertNotIn(dl_router.FALLBACK_NOTICE, msg2)

    def test_missing_model_falls_back_to_rules_with_one_time_mcp_notice(self):
        notices: list[tuple[str, str]] = []
        cat = {
            "servers": {
                "weather": _fake_server(description="Weather forecast", triggers=[r"\bweather\b"]),
            },
            "settings": {"max_tools": 10, "idle_turns": 2, "timeout_s": 10},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cat, f)
            cpath = Path(f.name)
        try:
            reg = dl_mcp.McpRegistry(
                surface="code",
                notify=lambda t, level="info": notices.append((t, level)),
                catalog=dl_mcp.load_catalog(cpath),
            )
            try:
                with mock.patch.dict(os.environ, {"DL_ROUTER_MODEL_DIR": "/nonexistent/m2v-model-dir"}):
                    # rules mode never checks model and emits no fallback notice
                    hits_rules = reg.route("check the weather", mode="rules")
                    self.assertEqual([n for n, _ in hits_rules], ["weather"])
                    self.assertFalse(any(dl_router.FALLBACK_NOTICE in t for t, _ in notices))

                    reg.disable("weather")
                    hits_m2v = reg.route("check the weather", mode="model2vec")
                    self.assertEqual([n for n, _ in hits_m2v], ["weather"])
                    fb_notices = [t for t, _ in notices if dl_router.FALLBACK_NOTICE in t]
                    self.assertEqual(len(fb_notices), 1)

                    reg.disable("weather")
                    reg.route("check the weather", mode="model2vec")
                    fb_notices_after = [t for t, _ in notices if dl_router.FALLBACK_NOTICE in t]
                    self.assertEqual(len(fb_notices_after), 1)
            finally:
                reg.close()
        finally:
            os.unlink(cpath)


class TestEffortModes(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def tearDown(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def test_plan_mode_and_small_talk_guard_in_model2vec_mode(self):
        with mock.patch.object(dl_router, "is_available", return_value=True), \
                mock.patch.object(dl_effort_scorer, "predict", return_value=("none", 0.99)):
            self.assertEqual(dl_effort.pick("hello Ray", mode="plan", router_mode="model2vec"), ("high", "plan mode"))
            self.assertEqual(dl_effort.pick("fix the parser bug", router_mode="model2vec"), ("none", "model2vec none"))
            # is_small_talk remains rules-only in every mode
            with mock.patch.dict(os.environ, {"DL_ROUTER_MODE": "model2vec"}):
                self.assertFalse(dl_effort.is_small_talk("fix the parser bug"))
                self.assertTrue(dl_effort.is_small_talk("hello Ray"))

    def test_hybrid_only_calls_scorer_on_default_fallthrough(self):
        with mock.patch.object(dl_router, "is_available", return_value=True), \
                mock.patch.object(dl_effort_scorer, "predict", return_value=("low", 0.90)) as pred:
            self.assertEqual(dl_effort.pick("explain what ROCm is", router_mode="hybrid"), ("medium", "explanation"))
            pred.assert_not_called()

            self.assertEqual(dl_effort.pick("pause the living room speaker", router_mode="hybrid"), ("low", "semantic low"))
            pred.assert_called_once()

    def test_hybrid_without_model2vec_is_rules(self):
        """No Model2Vec: hybrid gives the rules' answer (not the CRC32 fallback) and the notice says so once."""
        dl_router.reset_state()
        try:
            with mock.patch.object(dl_router, "is_available", side_effect=lambda *a, **k: dl_router._note_fallback() or False), \
                    mock.patch.object(dl_effort_scorer, "predict", return_value=("none", 0.99)) as pred:
                lvl, why = dl_effort.pick("pause the living room speaker", router_mode="hybrid")
                self.assertEqual((lvl, why), ("high", "default"))
                pred.assert_not_called()
                msg = dl_effort.describe_pick(lvl, why, 4096)
                self.assertTrue(msg.startswith(dl_router.FALLBACK_NOTICE))
                self.assertNotIn(dl_router.FALLBACK_NOTICE, dl_effort.describe_pick(lvl, why, 4096))
        finally:
            dl_router.reset_state()


@unittest.skipIf(np is None, "numpy required for vector routing tests")
class TestMcpRouterUnit(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_mcp_router.clear_cache()

        # Deterministic 4-D orthogonal embedding space:
        # dim 0 = weather, dim 1 = proton/email, dim 2 = music, dim 3 = _none (coding/chat)
        self.basis = {
            "weather": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "proton": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            "music": np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
            "_none": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        }

        self.proto = {
            "mcp": {
                "_none": ["refactor this python class", "hello friend"],
                "weather": ["is it going to rain tomorrow"],
                "proton": ["check my email inbox"],
                "music": ["play a relaxing song"],
            }
        }
        self.proto_file = Path(tempfile.mkstemp(suffix=".json")[1])
        self.proto_file.write_text(json.dumps(self.proto), encoding="utf-8")

        self.cat_dict = {
            "servers": {
                "weather": _fake_server(description="Weather", allow=["echo"], triggers=[r"\bweather\b"]),
                "proton": _fake_server(description="Proton Mail", allow=["echo", "add"], triggers=[r"\be-?mail\b"], unless=[r"\bgmail\b"]),
                "music": _fake_server(description="Music", allow=["echo", "add"], triggers=[r"\bsong\b"]),
                "phone": _fake_server(description="Phone", allow=["echo"], origins=["ray-android"], triggers=[r"\bphone\b"]),
                "terminal_only": _fake_server(description="Terminal", allow=["echo"], surfaces=["terminal"], triggers=[r"\bterm\b"]),
            },
            "settings": {"max_tools": 3, "idle_turns": 2, "timeout_s": 10},
        }
        self.cat_file = Path(tempfile.mkstemp(suffix=".json")[1])
        self.cat_file.write_text(json.dumps(self.cat_dict), encoding="utf-8")

    def tearDown(self):
        dl_router.reset_state()
        dl_mcp_router.clear_cache()
        self.proto_file.unlink(missing_ok=True)
        self.cat_file.unlink(missing_ok=True)

    def _fake_encode(self, texts, *, model_dir=None, preprocess=True):
        def vec_for(t: str):
            low = (t or "").lower()
            if "rainy_and_inbox_and_playlist" in low:
                v = np.array([0.85, 0.80, 0.75, 0.0], dtype=np.float32)
                return v / np.linalg.norm(v)
            if "rain" in low or "forecast" in low or "weather" in low:
                return self.basis["weather"]
            if "inbox" in low or "email" in low or "gmail" in low or "message" in low:
                return self.basis["proton"]
            if "song" in low or "playlist" in low or "play" in low:
                return self.basis["music"]
            return self.basis["_none"]

        if isinstance(texts, str):
            return vec_for(texts)
        return np.vstack([vec_for(t) for t in texts])

    def test_mcp_router_unless_none_margin_cap_and_unavailable(self):
        reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(self.cat_file))
        try:
            with mock.patch.object(dl_router, "is_available", return_value=True), \
                    mock.patch.object(dl_router, "encode", side_effect=self._fake_encode), \
                    mock.patch.object(dl_router, "prototypes_path", return_value=self.proto_file):
                # 1. No-server prompt matches _none, turns nothing on
                self.assertEqual(reg.route("refactor this python class", mode="model2vec"), [])

                # 2. 'unless' blocks proton even when embedding points to proton
                self.assertEqual(reg.route("check my gmail inbox", mode="model2vec"), [])

                # 3. 'origins' still runs in model2vec mode
                hits_orig = reg.route("refactor this python class", origin="ray-android", mode="model2vec")
                self.assertEqual([n for n, _ in hits_orig], ["phone"])
                reg.disable("phone")

                # 4. At most 2 servers enabled + reason shows 'similar: X.XX'
                hits_multi = reg.route("rainy_and_inbox_and_playlist", mode="model2vec")
                self.assertEqual(len(hits_multi), 2)
                self.assertEqual([n for n, _ in hits_multi], ["weather", "proton"])
                self.assertTrue(hits_multi[0][1].startswith("similar: "))
                # max_tools=3: weather (1) + proton (2) = 3 tools
                self.assertLessEqual(len(reg.routes), 3)

                # 5. Next turn enables music (2 tools), which exceeds max_tools=3 and evicts oldest (weather)
                hits_music = reg.route("play a relaxing playlist", mode="model2vec")
                self.assertEqual([n for n, _ in hits_music], ["music"])
                self.assertLessEqual(len(reg.routes), 3)
                self.assertNotIn("weather", reg.enabled)
        finally:
            reg.close()

    def test_hybrid_skips_embeddings_when_regex_matches(self):
        reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(self.cat_file))
        try:
            with mock.patch.object(dl_router, "is_available", return_value=True), \
                    mock.patch.object(dl_router, "encode", side_effect=self._fake_encode) as enc, \
                    mock.patch.object(dl_router, "prototypes_path", return_value=self.proto_file):
                # Regex matches 'weather' -> embeddings NOT called
                hits_rx = reg.route("weather forecast", mode="hybrid")
                self.assertEqual([n for n, _ in hits_rx], ["weather"])
                enc.assert_not_called()

                # Origin matches 'phone', no regex matches -> embeddings still run for 'forecast'
                reg.disable("weather")
                hits_hyb = reg.route("will it rain tomorrow?", origin="ray-android", mode="hybrid")
                names = [n for n, _ in hits_hyb]
                self.assertIn("phone", names)
                self.assertIn("weather", names)
                self.assertGreaterEqual(enc.call_count, 1)
        finally:
            reg.close()

    def test_rules_mode_preserves_catalog_order_between_triggers_and_origins(self):
        reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(self.cat_file))
        try:
            # 'weather' appears before 'phone' in self.cat_dict
            hits = reg.route("check the weather", origin="ray-android", mode="rules")
            self.assertEqual([n for n, _ in hits], ["weather", "phone"])
        finally:
            reg.close()


class TestScorerLeaveOneOutAndGate1(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def tearDown(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def test_exclude_text_masks_only_gold_tune_and_preserves_prototypes(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_p = Path(tmp) / "gold.json"
            proto_p = Path(tmp) / "proto.json"
            proto_p.write_text(json.dumps({
                "effort": {
                    "none": ["alpha greeting phrase"],
                    "low": ["beta lookup query"],
                    "medium": ["gamma explain topic"],
                    "high": ["delta debug crash"],
                }
            }), encoding="utf-8")
            gold_p.write_text(json.dumps({
                "reviewed": True,
                "records": [
                    {
                        "id": "g0001",
                        "split": "tune",
                        "text": "zeta custom tune prompt",
                        "effort_sample": True,
                        "gold_effort": "low",
                    }
                ],
            }), encoding="utf-8")
            sc = dl_effort_scorer.EffortScorer(
                prototypes_file=proto_p,
                gold_path=gold_p,
                include_gold_tune=True,
                backend="hash",
            )
            self.assertIn("gold_tune", sc.sources)
            # Excluding the gold_tune prompt masks it (falls back to high on low similarity / no match)
            lvl_masked, _ = sc.predict("zeta custom tune prompt", exclude_text="zeta custom tune prompt")
            self.assertNotEqual(lvl_masked, "low")
            # Built-in prototype is NOT masked even when exclude_text matches it
            lvl_proto, _ = sc.predict("alpha greeting phrase", exclude_text="alpha greeting phrase")
            self.assertEqual(lvl_proto, "none")

    def test_bench_refuses_unreviewed_test_split_gate1(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_p = Path(tmp) / "gold.json"
            gold_p.write_text(json.dumps({
                "reviewed": False,
                "records": [{"id": "g0001", "split": "test", "text": "hello"}],
            }), encoding="utf-8")
            rc = bench_router_ab.main(["--gold", str(gold_p), "--split", "test"])
            self.assertEqual(rc, 2)


_M32_DIR = Path.home() / ".local" / "share" / "dl-ai" / "models" / "potion-base-32M-int8"


@unittest.skipIf(np is None, "numpy required for vector routing tests")
class TestScorerCacheInvalidation(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def tearDown(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def _write_proto(self, path: Path, extra_low: list[str] | None = None) -> None:
        proto = {
            "effort": {
                "none": ["turn off the bedroom lamp"],
                "low": ["what is the current time"] + (extra_low or []),
                "medium": ["summarize the meeting notes"],
                "high": ["fix the deadlock in the worker thread"],
            },
            "mcp": {"_none": ["hello friend"]},
        }
        path.write_text(json.dumps(proto), encoding="utf-8")

    def _write_gold(self, path: Path, *, reviewed: bool, records: list[dict]) -> None:
        payload = {"reviewed": reviewed, "summary": {}, "records": records}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_get_scorer_invalidates_on_gold_env_mtime_unreviewed_and_prototypes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proto_a = tmp / "proto_a.json"
            proto_b = tmp / "proto_b.json"
            gold_a = tmp / "gold_a.json"
            gold_b = tmp / "gold_b.json"

            self._write_proto(proto_a)
            self._write_proto(proto_b, extra_low=["xylophone barometer telemetry check"])

            # Unique phrase not present in proto_a
            probe = "glockenspiel kaleidoscope quasar telemetry"
            self._write_gold(gold_a, reviewed=False, records=[])
            self._write_gold(
                gold_b,
                reviewed=True,
                records=[{
                    "id": "g0001",
                    "split": "tune",
                    "text": probe,
                    "gold_effort": "low",
                    "effort_sample": True,
                    "effort_proposed": "low",
                }],
            )

            env = {
                "DL_ROUTER_MODEL_DIR": "/nonexistent/m2v-model-dir",
                "DL_ROUTER_PROTOTYPES": str(proto_a),
                "DL_ROUTER_GOLD": str(gold_a),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("DL_ROUTER_USE_UNREVIEWED_TUNE", None)
                sc1 = dl_effort_scorer.get_scorer()
                sc1_again = dl_effort_scorer.get_scorer()
                self.assertIs(sc1, sc1_again)
                self.assertNotIn(probe, [p for p in sc1.labels])
                lvl_before, _ = dl_effort_scorer.predict(probe)
                self.assertNotEqual(lvl_before, "low")

                # 1. Override DL_ROUTER_GOLD -> new scorer, reflects gold_b tune record
                os.environ["DL_ROUTER_GOLD"] = str(gold_b)
                sc2 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc2, sc1)
                self.assertIs(sc2, dl_effort_scorer.get_scorer())
                lvl_b, _ = dl_effort_scorer.predict(probe)
                self.assertEqual(lvl_b, "low")

                # 2. Update gold_b.json on disk (change gold_effort to "none") -> cache invalidated
                self._write_gold(
                    gold_b,
                    reviewed=True,
                    records=[{
                        "id": "g0001",
                        "split": "tune",
                        "text": probe,
                        "gold_effort": "none",
                        "effort_sample": True,
                        "effort_proposed": "low",
                    }],
                )
                sc3 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc3, sc2)
                lvl_updated, _ = dl_effort_scorer.predict(probe)
                self.assertEqual(lvl_updated, "none")

                # 3. Toggle DL_ROUTER_USE_UNREVIEWED_TUNE on unreviewed gold_a
                self._write_gold(
                    gold_a,
                    reviewed=False,
                    records=[{
                        "id": "g0001",
                        "split": "tune",
                        "text": probe,
                        "gold_effort": None,
                        "effort_sample": True,
                        "effort_proposed": "medium",
                    }],
                )
                os.environ["DL_ROUTER_GOLD"] = str(gold_a)
                sc4 = dl_effort_scorer.get_scorer()
                self.assertNotEqual(dl_effort_scorer.predict(probe)[0], "medium")

                os.environ["DL_ROUTER_USE_UNREVIEWED_TUNE"] = "1"
                sc5 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc5, sc4)
                self.assertEqual(dl_effort_scorer.predict(probe)[0], "medium")

                # 4. Override DL_ROUTER_PROTOTYPES and update prototypes file on disk
                os.environ.pop("DL_ROUTER_USE_UNREVIEWED_TUNE", None)
                os.environ["DL_ROUTER_PROTOTYPES"] = str(proto_b)
                sc6 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc6, sc5)
                self.assertEqual(dl_effort_scorer.predict("xylophone barometer telemetry check")[0], "low")

                self._write_proto(proto_b, extra_low=[])
                sc7 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc7, sc6)

                # 5. Removing gold_a invalidates cache cleanly
                gold_a.unlink()
                sc8 = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc8, sc7)


class TestRouterGoldImportReview(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    def tearDown(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()

    @staticmethod
    def _tune_prompt(prefix: str) -> str:
        for i in range(100):
            cand = f"{prefix} {i}"
            if router_gold.stable_split(cand) == "tune":
                return cand
        raise AssertionError("could not find tune prompt")

    def test_import_review_atomic_private_roundtrip_and_scorer_refresh(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            tdir = tmp / "transcripts"
            keep_dir = tdir / "dl-ai-code"
            drop_dir = tdir / "bench-run"
            keep_dir.mkdir(parents=True)
            drop_dir.mkdir(parents=True)
            out_dir = tmp / "out"

            cat_path = tmp / "catalog.json"
            cat_path.write_text(
                json.dumps({
                    "servers": {
                        "weather": _fake_server(description="Weather forecast", triggers=[r"\bweather\b"]),
                        "proton": _fake_server(description="Proton Mail", triggers=[r"\be-?mail\b"]),
                    },
                    "settings": {"max_tools": 4, "idle_turns": 2, "timeout_s": 10},
                }),
                encoding="utf-8",
            )

            p1 = self._tune_prompt("check the weather forecast outside tomorrow")
            p2 = self._tune_prompt("quartz nebula diffraction protocol")
            p3 = self._tune_prompt("check my inbox messages from yesterday")

            events = [
                {"type": "user", "ts": 1.0, "text": p1, "origin": "web", "voice": False},
                {"type": "notice", "text": "Thinking: high for this answer, because no lighter level fits it."},
                {"type": "text", "text": "It might rain."},
                {"type": "user", "ts": 2.0, "text": p2, "origin": "web", "voice": False},
                {"type": "notice", "text": "Thinking: high for this answer, because no lighter level fits it."},
                {"type": "text", "text": "Done."},
                {"type": "user", "ts": 3.0, "text": p3, "origin": "web", "voice": False},
                {"type": "tool_call", "name": "proton__list", "args": {}},
                {"type": "text", "text": "Two unread messages."},
                # Should be ignored by origin filter
                {"type": "user", "ts": 4.0, "text": "benchmark prompt", "origin": "bench", "voice": False},
            ]
            (keep_dir / "2026-11-01.jsonl").write_text(
                "\n".join(json.dumps(e) for e in events) + "\n",
                encoding="utf-8",
            )
            (drop_dir / "2026-11-01.jsonl").write_text(
                json.dumps({"type": "user", "ts": 5.0, "text": "bench session prompt", "origin": "web"}) + "\n",
                encoding="utf-8",
            )

            rc = router_gold.main([
                "--transcripts-dir", str(tdir),
                "--out-dir", str(out_dir),
                "--catalog", str(cat_path),
            ])
            self.assertEqual(rc, 0)

            gold_path = out_dir / "gold.json"
            review_path = out_dir / "review.md"
            self.assertEqual(out_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(gold_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(review_path.stat().st_mode & 0o777, 0o600)

            # Broaden gold.json mode beforehand to verify import_review restores 0600 atomically via os.replace
            os.chmod(gold_path, 0o644)

            initial = json.loads(gold_path.read_text(encoding="utf-8"))
            self.assertFalse(initial["reviewed"])
            self.assertEqual(len(initial["records"]), 3)

            proto_path = tmp / "prototypes.json"
            proto_path.write_text(
                json.dumps({
                    "effort": {
                        "none": ["turn off the bedroom lamp"],
                        "low": ["what is the current time"],
                        "medium": ["summarize the meeting notes"],
                        "high": ["fix the deadlock in the worker thread"],
                    },
                    "mcp": {"_none": ["hello friend"]},
                }),
                encoding="utf-8",
            )

            # Cache scorer while unreviewed; p2 should not yet be learned as "none"
            env = {
                "DL_ROUTER_MODEL_DIR": "/nonexistent/m2v-model-dir",
                "DL_ROUTER_GOLD": str(gold_path),
                "DL_ROUTER_PROTOTYPES": str(proto_path),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("DL_ROUTER_USE_UNREVIEWED_TUNE", None)
                sc_before = dl_effort_scorer.get_scorer()
                self.assertNotEqual(dl_effort_scorer.predict(p2)[0], "none")

                # Edit review.md verdicts:
                # - g0001 effort: ✓, uncertain MCP: ✓ (should resolve to ["weather"])
                # - g0002 effort: none (explicit override), clear-none MCP: weather, proton
                # - g0003 effort: low, used MCP: none (explicit override clearing proton)
                edited_lines = []
                section = ""
                for line in review_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("## 1. Thinking Level"):
                        section = "effort"
                    elif line.startswith("## 2"):
                        section = "mcp"
                    elif line.startswith("| g"):
                        rid = line.split("|", 2)[1].strip()
                        if section == "effort":
                            verdict = {"g0001": "✓", "g0002": "none", "g0003": "low"}.get(rid, "")
                        elif section == "mcp":
                            verdict = {"g0001": "✓", "g0002": "weather, proton", "g0003": "none"}.get(rid, "")
                        else:
                            verdict = ""
                        if verdict:
                            line = line[:-1] + f" {verdict} |"
                    edited_lines.append(line)
                review_path.write_text("\n".join(edited_lines) + "\n", encoding="utf-8")

                rc2 = router_gold.main(["--out-dir", str(out_dir), "--import-review"])
                self.assertEqual(rc2, 0)

                # Atomic 0600 permissions restored, no leftover temp files
                self.assertEqual(gold_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual([p.name for p in out_dir.iterdir() if p.name.endswith(".tmp")], [])

                updated = json.loads(gold_path.read_text(encoding="utf-8"))
                self.assertTrue(updated["reviewed"])
                by_id = {r["id"]: r for r in updated["records"]}
                self.assertEqual(by_id["g0001"]["gold_effort"], by_id["g0001"]["effort_proposed"])
                self.assertEqual(by_id["g0001"]["gold_mcp"], ["weather"])
                self.assertFalse(by_id["g0001"]["mcp_uncertain"])
                self.assertEqual(by_id["g0002"]["gold_effort"], "none")
                self.assertEqual(by_id["g0002"]["gold_mcp"], ["proton", "weather"])
                self.assertEqual(by_id["g0003"]["gold_effort"], "low")
                self.assertEqual(by_id["g0003"]["gold_mcp"], [])

                # Scorer cache automatically invalidates on updated gold.json without reset_scorer()
                sc_after = dl_effort_scorer.get_scorer()
                self.assertIsNot(sc_after, sc_before)
                self.assertIn((p2, "none", "gold_tune"), sc_after._collect_samples())
                self.assertEqual(sc_after.predict(p2, k=1), ("none", 1.0))


@unittest.skipUnless(
    importlib.util.find_spec("model2vec") is not None and dl_router.DEFAULT_MODEL_DIR.is_dir(),
    "local Model2Vec model directory not installed in this environment",
)
class TestRealModel2VecIntegration(unittest.TestCase):
    def setUp(self):
        dl_router.reset_state()
        dl_effort_scorer.reset_scorer()
        dl_mcp_router.clear_cache()

    def test_real_model2vec_stats_and_basic_routing(self):
        # potion-multilingual-128M-int8 uses ~1.3 GiB RSS (exceeds the 300 MiB RAM gate;
        # tracked for Gate 1). Keep the < 300 MiB assertion on potion-base-32M-int8 below
        # and verify telemetry + functional routing here.
        st = dl_router.stats()
        self.assertTrue(st["available"])
        self.assertEqual(st["model_dir"], str(dl_router.DEFAULT_MODEL_DIR))
        self.assertGreater(st["load_time_ms"], 0.0)
        self.assertIsInstance(st["rss_delta_mib"], float)
        self.assertGreaterEqual(st["rss_delta_mib"], 0.0)
        lvl, _ = dl_effort.pick("turn off the bedroom lamp", router_mode="model2vec")
        self.assertEqual(lvl, "none")
        lvl2, _ = dl_effort.pick("fix the deadlock in the worker thread", router_mode="model2vec")
        self.assertEqual(lvl2, "high")

    @unittest.skipUnless(_M32_DIR.is_dir(), "potion-base-32M-int8 not installed")
    def test_real_model2vec_32m_ram_gate_and_routing(self):
        import subprocess
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{HERE}:{env.get('PYTHONPATH', '')}".rstrip(":")
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, sys, dl_router; print(json.dumps(dl_router.stats(sys.argv[1])))",
                str(_M32_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        st = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(st["available"])
        self.assertLess(st["rss_delta_mib"], 300.0)

        sc = dl_effort_scorer.EffortScorer(model_dir=_M32_DIR)
        lvl, _ = sc.predict("turn off the bedroom lamp")
        self.assertEqual(lvl, "none")
        lvl2, _ = sc.predict("fix the deadlock in the worker thread")
        self.assertEqual(lvl2, "high")


if __name__ == "__main__":
    unittest.main()
