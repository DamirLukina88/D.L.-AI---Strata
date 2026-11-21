"""Ray's tests never read the user's per-model settings profiles (~/.config/dl-ai/models): each test gets an empty
profile folder and no profile in use (tools/dl_profile.py)."""
import sys

import pytest


@pytest.fixture(autouse=True)
def _no_user_model_profiles(tmp_path_factory, monkeypatch):
    folder = tmp_path_factory.mktemp("model-profiles")
    for name in ("dl_profile", "tools.dl_profile"):
        mod = sys.modules.get(name)
        if mod is None:
            try:
                mod = __import__(name, fromlist=["_"])
            except ImportError:
                continue
        monkeypatch.setattr(mod, "profiles_dir", lambda folder=folder: folder)
        mod.reset()
    yield
    for name in ("dl_profile", "tools.dl_profile"):
        mod = sys.modules.get(name)
        if mod is not None:
            mod.reset()
