"""serve/test_available_models.py - the web app's model dropdown lists engine configs only: not the saved Chat
settings (strata-<model>.shared-settings.json, which sit next to them) or any other strata-*.json that isn't one.

    python serve/test_available_models.py
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402


class ModelList(unittest.TestCase):
    def test_only_engine_configs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            engine = {"exe": "/x/strata", "args": ["--pack", "p"], "model_name": "coder", "display_name": "Coder"}
            (root / "strata-coder.json").write_text(json.dumps(engine))
            (root / "strata-general.json").write_text(json.dumps({**engine, "model_name": "general"}))
            (root / "strata-coder.shared-settings.json").write_text(json.dumps({"temperature": 0.6}))
            (root / "strata-notes.json").write_text(json.dumps({"hello": 1}))          # not an engine config
            (root / "strata-broken.json").write_text("{")
            old, server.ROOT = server.ROOT, root
            try:
                svc = types.SimpleNamespace(model="coder", loaded=lambda: True)
                models = server.Service.available_models(svc)
            finally:
                server.ROOT = old
        self.assertEqual([m["id"] for m in models], ["coder", "general"])
        self.assertEqual([m["active"] for m in models], [True, False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
