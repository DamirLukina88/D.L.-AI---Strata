"""The web app is one program in several classic scripts (serve/web/app-01-util.js ... app.js, loaded in this order
by index.html).  Tests that check its source read it through here."""
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


def app_js_paths() -> list[Path]:
    """The app's scripts in load order: app-NN-*.js by number, then app.js."""
    return sorted(WEB.glob("app-[0-9][0-9]-*.js")) + [WEB / "app.js"]


def app_js_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in app_js_paths())
