#!/usr/bin/env python3
"""dl_mcp.py - MCP servers for D.L. CLI, started only while a request needs them.

Every tool schema D.L. CLI offers is sent again with every turn, and the local model pays for it in prefill time.  So
the servers in ~/.config/dl-ai/mcp.json (DL_MCP_CONFIG overrides the path) are not loaded up front:

- a router turns a server on before the model call when the user's message matches one of its `triggers` (regexes;
  English, Croatian and German words) or comes from a client in its `origins` (e.g. "ray-android"), and the model can turn one on itself with the small `mcp` tool, whose
  description lists the catalogue in one line per server;
- a server whose tools went unused for `idle_turns` user turns is turned off again (and one with `idle_s`, such as a
  browser, after that many idle seconds); `"default": "on"` servers stay;
- only the tools in a server's `allow` list reach the model, at most `max_tools` at once (the server used longest
  ago is turned off first).

The MCP client is serve/mcp.py's McpServer (stdio and Streamable HTTP, restart after a crash).  A server gets only
PATH, HOME and a few more of our variables (`env_inherit`) plus the keys it names in `env_from_secrets`, never the
whole secrets file.  `surfaces` limits where a server may run ("code": the shared session daemon, the web Code tab
and `dl_cli.py --attach`; "terminal": the stand-alone REPL).  Outside YOLO, tools in `ask` need the user's approval
and `ask_always` tools (sending email, sharing) show the whole message on the card; a YOLO session asks nothing.

No catalogue file: no `mcp` tool, and D.L. CLI offers exactly the tools it did before.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.mcp import DEFAULTS, McpCancelled, McpError, McpServer, _check_server, _clean, result_text  # noqa: E402
try:
    from tools.dl_auditing import find_known_secrets, scan_secrets_in_text  # noqa: E402
except ImportError:
    from dl_auditing import find_known_secrets, scan_secrets_in_text  # noqa: E402
if __package__ == "tools":
    from tools import dl_router, dl_mcp_router  # noqa: E402
else:
    try:
        import dl_router  # noqa: E402
        import dl_mcp_router  # noqa: E402
    except ImportError:
        try:
            from tools import dl_router, dl_mcp_router  # noqa: E402
        except ImportError:
            dl_router = None
            dl_mcp_router = None

# D.L. CLI's own tools that are not in the catalogue; /mcp lists them so every outside service shows in one place
BUILT_IN = [("exa", "Web search (Exa web API, not MCP): exa_web_search, /exa <query>"),
            ("context7", "Library docs (Context7 MCP, started for each lookup): resolve_library_id, get_library_docs, /context7 <lib>")]
CATALOG_PATH = Path(os.environ.get("DL_MCP_CONFIG") or Path.home() / ".config" / "dl-ai" / "mcp.json")
ENV_INHERIT = ["PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
               "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR", "STRATA_WORKSPACE_DIR"]
SETTINGS = {"max_tools": 25, "idle_turns": 3, "timeout_s": 120.0, "start_timeout_s": 180.0,
            "max_result_chars": DEFAULTS["max_result_chars"]}
META_NAME = "mcp"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RECIPIENT_KEY = re.compile(r"^(to|cc|bcc|recipients?|send_?to|share_?with|new_owner_email)$", re.I)
BODY_KEY = re.compile(r"^(body|text|content|message|html_?body|plain_?body)$", re.I)



# A picture attached to the prompt ("@phone-photos/x.jpg", "[Image: ...]"): the words "photo", "picture", "slika",
# "what do you see" are about it, not a request to use the phone's camera or gallery (audit 2026-11-15).
HAS_ATTACHMENT = re.compile(r"(?:^|\s)@[\w./-]+\.(?:jpe?g|png|webp|gif|bmp|heic|heif|tiff?|avif)\b|\[(?:Attached image|Image|Photo)\b",
                            re.I)
PICTURE_WORDS = re.compile(r"(?:photos?|pictures?|images?|slik\w*|fotk\w*|pogledaj|look at (?:this|that|it)|"
                           r"what (?:do|can) you see|what(?:'s| is) (?:this|that|in front)\w*|[šs]ta vidi[šs]|[šs]to vidi[šs])",
                           re.I)
# Phone actions that run only when the user's words ask for them, in YOLO too (the user's choice, 2026-11-15: Ray played
# music, overwrote the clipboard and took a camera snapshot nobody asked for).  "words" always count; "plain" count only
# when no picture is attached.  An entry's "ask_words" in mcp.json adds to or replaces these, per tool.
DEFAULT_ASK_WORDS: dict[str, dict] = {
    "phone_camera_snap": {
        "words": [r"\bcamera\b", r"\bkamer\w*", r"\bu?slikaj\w*", r"\bsnap\b", r"\btake (?:a |another )?(?:photo|picture|pic)\b",
                  r"\bfotkaj\w*", r"\bphoto of\b"],
        "plain": [r"\bwhat (?:do|can) you see\b", r"\blook at (?:this|that|it)\b", r"\bwhat(?:'s| is) in front\b",
                  r"\b[šs]ta vidi[šs]\b", r"\b[šs]to vidi[šs]\b", r"\bpogledaj\b"],
    },
    # it takes a photo when Ray took none in the last 2 minutes (live 2026-11-15: a snapshot nobody asked for)
    "phone_get_last_photo": {"words": [r"\bcamera\b", r"\bkamer\w*", r"\bu?slikaj\w*", r"\bsnap\w*",
                                       r"\b(?:last|that|the) (?:photo|picture|snap\w*) you took\b", r"\bfotkaj\w*",
                                       r"\btake (?:a |another )?(?:photo|picture|pic)\b"]},
    "phone_get_gallery_image": {"words": [r"\bgaller(?:y|ies)\b", r"\bgalerij\w*", r"\bscreen ?shots?\b",
                                          r"\bsnimk\w* zaslona\b", r"\bon (?:my|the) phone\b", r"\bna mobitelu\b"],
                                "plain": [r"\b(?:last|latest|newest|recent) (?:photo|picture|pic|image)\b",
                                          r"\bzadnj\w* slik\w*", r"\bposljednj\w* slik\w*"]},
    "phone_control_media": {"words": [r"\bplay(?:s|ing)?\b", r"\bpause[ds]?\b", r"\bresume\b", r"\bskip\b", r"\bnext\b", r"\bprevious\b",
                                      r"\bstop\b", r"\bmusic\b", r"\bsong\b", r"\btrack\b", r"\bspotify\b", r"\byoutube\b",
                                      r"\bpjesm\w*", r"\bpusti\w*", r"\bglazb\w*", r"\bmuzik\w*", r"\bpauziraj\w*",
                                      r"\bzaustavi\w*", r"\bstani\b", r"\bsljede[cć]\w*", r"\bprethodn\w*"]},
    "phone_play_music": {"words": [r"\bplay(?:s|ing)?\b", r"\bput on\b", r"\bmusic\b", r"\bsong\b", r"\balbum\b", r"\bartist\b",
                                   r"\bspotify\b", r"\byoutube\b", r"\bpjesm\w*", r"\bpusti\w*", r"\bglazb\w*", r"\bmuzik\w*"]},
    # only setting the clipboard (action "set"); reading it is harmless
    "phone_clipboard": {"words": [r"\bclipboard\b", r"\bcopy\b", r"\bkopiraj\w*", r"\bme[dđ]uspremnik\w*", r"\bpaste\b"],
                        "args": {"action": ["set"]}},
}


def _compile_words(spec) -> dict:
    """{"words": [rx], "plain": [rx], "args": {key: [values]}} from a list (words only) or such a dict."""
    if isinstance(spec, (list, tuple)):
        spec = {"words": list(spec)}
    spec = spec or {}
    return {"words": [re.compile(w, re.I) for w in spec.get("words") or []],
            "plain": [re.compile(w, re.I) for w in spec.get("plain") or []],
            "args": {str(k): [str(x) for x in v] for k, v in (spec.get("args") or {}).items()}}


DEFAULT_ASK_WORDS_RX = {k: _compile_words(v) for k, v in DEFAULT_ASK_WORDS.items()}


def asked_in_words(rule: dict, args: dict | None, text: str) -> bool:
    """Whether a words-gated call may run: its arguments are outside the rule (e.g. reading the clipboard), or the
    user's words ask for it.  A picture word does not count while a picture is attached; an attached path is no word."""
    for key, values in (rule.get("args") or {}).items():
        if str((args or {}).get(key, "") or "").lower() not in values:
            return True
    attached = bool(HAS_ATTACHMENT.search(text or ""))
    text = ATTACHED_REF.sub(" ", text or "")
    pools = rule["words"] + ([] if attached else rule["plain"])
    for rx in pools:
        for m in rx.finditer(text or ""):
            if not (attached and PICTURE_WORDS.fullmatch(m.group(0))):
                return True
    return False


ATTACHED_REF = re.compile(r"(?:^|(?<=\s))@[\w./-]+")


def trigger_hit(entry, text: str):
    """The first trigger of `entry` that matches, skipping picture words while a picture is attached; None if none.
    An attached file's path is not the user's words ("@phone-photos/x.jpg" turned the phone on, live 2026-11-15)."""
    attached = bool(HAS_ATTACHMENT.search(text or ""))
    text = ATTACHED_REF.sub(" ", text or "")
    for rx in entry.triggers:
        for m in rx.finditer(text):
            if attached and PICTURE_WORDS.fullmatch(m.group(0).strip()):
                continue
            return m
    return None

SHORT_MAX = 48


def short_description(text: str, name: str = "") -> str:
    """The few words of a server's description that the `mcp` tool lists with every request, at most SHORT_MAX
    characters cut at a word.  "Title: what it does": the title, unless the title only repeats the server's name
    ("arXiv: search preprints ..." under `arxiv`), then what it does.  Without a title: up to the first comma or
    full stop.  The whole description stays in `mcp(action="list")`.  40 full descriptions were 5.2k characters of
    every prompt (2026-11-16)."""
    text = " ".join(str(text).split())
    head, colon, tail = text.partition(": ")
    if colon:
        bare = re.sub(r"\([^)]*\)|\byour\b", " ", head, flags=re.I)
        words = re.findall(r"[A-Za-z0-9.]+", bare)
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        flat = re.sub(r"[^a-z0-9]", "", bare.lower())
        repeats = bool(key) and len(words) <= 2 and key in flat and len(flat) - len(key) <= 6
        text = tail if repeats else head
    else:
        for sep in (", ", ". "):
            first = text.split(sep, 1)[0]
            if first != text and len(first) >= 12:
                text = first
                break
    if len(text) > SHORT_MAX:
        text = text[:SHORT_MAX + 1].rsplit(" ", 1)[0]
    return text.rstrip(" .,;:(&/-")


class Entry:
    """One catalogue server: the MCP config for McpServer and D.L. CLI's own fields."""

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.description = str(raw.get("description") or name)
        # what the `mcp` tool's own description says about it; "short" in the catalogue wins over the cut
        self.short = " ".join(str(raw.get("short") or "").split()) or short_description(self.description, name)
        self.default_on = raw.get("default") == "on"
        self.allow = list(raw.get("allow") or [])            # empty: every tool the server lists
        self.readonly = raw.get("readonly") is True
        self.readonly_tools = set(raw.get("readonly_tools") or [])
        self.ask = set(raw.get("ask") or [])
        self.ask_always = set(raw.get("ask_always") or [])
        # {"tool": ["arg", ...]}: outside YOLO the call shows the full card when one of these is set (e.g. trashed=true)
        self.ask_always_args = {str(k): list(v) for k, v in (raw.get("ask_always_args") or {}).items()}
        # "ask" tools run without asking while the server's page is local (file://, localhost): the agent testing
        # its own work in a browser.  Opt-in per server; anything else, or a page not known yet, still asks.
        self.trust_local_pages = raw.get("trust_local_pages") is True
        # why its `ask` tools ask (shown on the card), e.g. "sends your text to DeepSeek's cloud"
        self.ask_reason = str(raw.get("ask_reason") or "acts in the browser / outside D.L. CLI")
        # the card shows these arguments in full, not cut at 60 characters (e.g. the prompt that leaves the PC)
        self.ask_full_args = [str(a) for a in raw.get("ask_full_args") or []]
        self.surfaces = list(raw.get("surfaces") or [])      # empty: everywhere
        self.idle_s = float(raw.get("idle_s") or 0)
        # how long one call may take (0: the global timeout_s); DeepSeek's reasoning needs more than the default 120 s
        self.timeout_s = float(raw.get("timeout_s") or 0)
        # arguments set here, hidden from the model and added to every call (e.g. the Google account)
        self.fixed_args = {str(k): v for k, v in (raw.get("fixed_args") or {}).items()}
        # a short plain word must start a word: "lan" turned networking on for "plan" (2026-11-14); "lans" still counts
        self.triggers = [re.compile(rf"\b{t}" if re.fullmatch(r"[A-Za-z]{1,3}", str(t)) else t, re.I)
                         for t in raw.get("triggers") or []]
        # clients whose every prompt turns this server on (the phone's tools for prompts from the Ray Android app);
        # "ray-android" also covers "ray-android-app-<id>" (the app's chat page)
        self.origins = {str(o) for o in raw.get("origins") or []}
        # the router skips this entry when one of these matches (e.g. Proton's mail words, but the user named Gmail)
        self.unless = [re.compile(t, re.I) for t in raw.get("unless") or []]
        # per tool: the words the user's request must contain for the call to run (DEFAULT_ASK_WORDS adds the phone's)
        self.ask_words = {str(k): _compile_words(v) for k, v in (raw.get("ask_words") or {}).items()}
        self.missing = [k for k in raw.get("env_from_secrets") or [] if not os.environ.get(k)]
        # D.L. CLI's own tools this entry takes over: they leave the always-on list while the catalogue has it
        self.replaces = [str(x) for x in raw.get("replaces") or []]
        # "builtin": a tool D.L. CLI itself provides (register_builtin), loaded on demand like a server; no process
        self.builtin = str(raw["builtin"]) if raw.get("builtin") else ""
        if self.builtin:
            self.cfg = {}
            return
        cfg = {k: raw[k] for k in ("command", "args", "cwd", "url", "headers", "type") if k in raw}
        if "command" in cfg:
            cfg["command"] = os.path.expanduser(str(cfg["command"]))
            cfg["args"] = [os.path.expanduser(str(a)) for a in cfg.get("args") or []]
            cfg["env_inherit"] = list(raw.get("env_inherit") or ENV_INHERIT)
        env = {k: os.environ[k] for k in raw.get("env_from_secrets") or [] if os.environ.get(k)}
        env.update({str(k): str(v) for k, v in (raw.get("env") or {}).items()})
        cfg["env"] = env
        self.cfg = _check_server(name, cfg, "mcp.json")

    def unavailable(self, surface: str) -> str | None:
        if self.surfaces and surface not in self.surfaces:
            where = " or ".join({"code": "the Code tab / dl_cli.py --attach", "terminal": "the terminal"}.get(s, s)
                                for s in self.surfaces)
            return f"only available in {where}"
        if self.missing:
            return f"needs {', '.join(self.missing)} in ~/.config/dl-ai/secrets.env"
        if self.builtin and self.builtin not in BUILTINS:
            return f"built-in {self.builtin!r} is not provided by this program"
        return None


# name -> (MCP-style tool list, handler(tool, args) -> text); dl_cli.py registers its own tools here.  Shared with
# the module's other copy when it is loaded both as dl_mcp and tools.dl_mcp (the daemon and the tests do that)
_twin = sys.modules.get("tools.dl_mcp" if __name__ == "dl_mcp" else "dl_mcp")
BUILTINS: dict[str, tuple[list[dict], object]] = getattr(_twin, "BUILTINS", None)
if BUILTINS is None:
    BUILTINS = {}


# what the running turn is for (workspace, yolo, when the user asked, the registry); the session daemon sets it per
# turn, built-ins read it.  Per thread: each turn runs in its own thread, and built-ins run in the caller's thread
CALL = getattr(_twin, "CALL", None) or threading.local()


def _profile_email() -> str:
    try:
        return str(json.loads((Path.home() / ".config" / "dl-ai" / "profile.json").read_text()).get("email") or "").lower()
    except (OSError, ValueError, AttributeError):
        return ""


def _email_text(args: dict) -> str:
    """The readable text of an HTML email in a tool call (`html`, or a workspace `html_file`), for the approval card."""
    html = args.get("html") if isinstance(args.get("html"), str) else ""
    if not html and isinstance(args.get("html_file"), str):
        try:
            ws = Path(call_context().get("workspace") or os.getcwd())
            f = Path(os.path.expanduser(args["html_file"]))
            f = (f if f.is_absolute() else ws / f).resolve()
            html = f.read_text(encoding="utf-8", errors="replace")[:200_000] if f.is_file() else ""
        except OSError:
            html = ""
    if not html:
        return ""
    try:
        from tools.dl_proton import html_to_text
    except ImportError:
        try:
            from dl_proton import html_to_text
        except ImportError:
            return re.sub(r"<[^>]+>", " ", html)
    return html_to_text(html)


def call_context() -> dict:
    return getattr(CALL, "ctx", None) or {}


def register_builtin(name: str, tools: list[dict], handler) -> None:
    BUILTINS[name] = (tools, handler)


class BuiltinServer:
    """A built-in tool behind McpServer's interface, so the registry turns it on and off like a server."""

    def __init__(self, name: str):
        self.name, self.error = name, ""
        self.tools, self.handler = BUILTINS.get(name, ([], None))

    def start(self) -> bool:
        if self.handler is None:
            self.error = "not provided by this program"
        return self.handler is not None

    def call(self, tool: str, args: dict, timeout: float = 0, cancel=None) -> dict:
        try:
            text = str(self.handler(tool, args))
        except Exception as e:  # noqa: BLE001 - a tool error is text for the model
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "isError": text.startswith("Error")}

    def close(self) -> None:
        pass


def load_catalog(path: Path | None = None) -> tuple[dict[str, Entry], dict, list[str]]:
    """-> (servers, settings, problems).  A missing file is no servers; a broken entry is left out with a problem."""
    path = Path(path or CATALOG_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, dict(SETTINGS), []
    except (OSError, ValueError) as e:
        return {}, dict(SETTINGS), [f"{path}: {e}"]
    servers, problems = {}, []
    if not isinstance(data, dict):
        return {}, dict(SETTINGS), [f"{path}: expected a JSON object with \"servers\""]
    raw_servers = data.get("servers", {})
    if not isinstance(raw_servers, dict):
        problems.append(f"{path}: \"servers\" must be an object")
        raw_servers = {}
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict) or raw.get("disabled") is True:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or name == META_NAME:
            problems.append(f"{path}: server name {name!r} must be 1-32 letters, digits, - or _ (and not 'mcp')")
            continue
        try:
            servers[name] = Entry(name, raw)
        except (SystemExit, re.error, TypeError, ValueError, AttributeError) as e:
            problems.append(f"{path}: server {name!r}: {e}")
    settings = dict(SETTINGS)
    raw_settings = data.get("settings", {})
    for k, v in (raw_settings.items() if isinstance(raw_settings, dict) else []):
        if k in SETTINGS and type(v) in (int, float) and v >= 0:      # a typo keeps the default
            settings[k] = v
    if not isinstance(raw_settings, dict):
        problems.append(f"{path}: \"settings\" must be an object")
    return servers, settings, problems


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


# A local file a tool reads and sends on (a mail attachment's "path", a Drive upload's file_path / file:// URL)
FILE_KEY = re.compile(r"^(path|file|file_?path|file_?url|fileUrl|url|source|local_?path|\w+_file|attachments?)$", re.I)
PRIVATE_DIRS = [Path.home() / d for d in (
    ".config/dl-ai", ".ssh", ".gnupg", ".aws", ".kube", ".docker",
    ".config/protonmail", ".local/state/dl-ai",                       # Bridge's vault and keys; session histories
    ".local/share/keyrings", ".password-store",                       # the desktop keyring, pass
    ".mozilla", ".config/google-chrome", ".config/chromium", ".config/BraveSoftware")]   # browser cookies
MAX_SCAN_BYTES = 20 * 1024 * 1024


def _local_files(value, key=""):
    """The existing local files named in a tool's arguments (paths and file:// URLs, at any depth)."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _local_files(v, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _local_files(v, key)
    elif isinstance(value, str) and (value.startswith("file://") or (FILE_KEY.match(key) and "://" not in value)):
        s = value[7:] if value.startswith("file://") else value
        try:
            f = Path(s).expanduser().resolve()
            if f.is_file():
                yield f
        except (OSError, ValueError):
            pass


def file_leak(f: Path) -> str | None:
    """Why a local file must not leave this PC, or None."""
    if any(f.is_relative_to(d) for d in PRIVATE_DIRS) or "private" in f.parts and "wiki" in f.parts:
        return f"{f} is in a private folder (credentials)"
    if f.name in ("secrets.env", ".env") or f.suffix.lower() in (".env", ".pem", ".key", ".p12", ".pfx"):
        return f"{f} is a credentials file"
    try:
        with f.open("rb") as fh:
            data = fh.read(MAX_SCAN_BYTES).decode("utf-8", errors="ignore")
    except OSError:
        return None
    hits = find_known_secrets(data)
    return f"{f} contains {', '.join(hits)}" if hits else None


PAGE_URL = re.compile(r"Page URL:\s*(\S+)")
# A page fetched again within FETCH_REUSE_S is answered from the saved copy: on 2026-11-14 Ray fetched the same
# 30k-character wiki page twice across a handoff, and each copy filled its context.
FETCH_DIR = Path(os.environ.get("DL_FETCH_CACHE") or Path.home() / ".cache" / "dl-ai" / "fetch")
FETCH_REUSE_S = float(os.environ.get("DL_FETCH_REUSE_S") or 7200)
# where image blocks of tool results (screenshots) are saved for the model to see (2026-11-14: Ray had no way to look
# at the page it built, and its tests passed while every Tetris piece was upside down)
IMAGE_DIR = Path(os.environ.get("DL_MCP_IMAGE_DIR") or Path.home() / ".cache" / "dl-ai" / "mcp-images")
SHOT_LINK = re.compile(r"\[Screenshot[^\]]*\]\(([^)\s]+\.(?:png|jpe?g|webp))\)", re.I)
# Text a tool saved to a file instead of returning it (Playwright: "- [Console](./console-x.log)", "[Snapshot](./page.yml)").
# It is read back into the result (2026-11-14: Ray could not find console-selftest.log).
SAVED_LINK = re.compile(r"\[(?:Console|Snapshot|Network|Result|Logs?)[^\]]*\]\(([^)\s]+\.(?:log|ya?ml|txt|md|json))\)", re.I)
SAVED_CAP = 4000
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0")


def is_local_url(url: str) -> bool:
    """file:// or a loopback/.localhost web address: the user's own machine."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url or "")
    except ValueError:
        return False
    if u.scheme == "file":
        return True
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and (host in LOCAL_HOSTS or host.endswith(".localhost"))


class McpRegistry:
    """The MCP servers of one D.L. CLI session: which are on, their tools, routing, approvals, idle shutdown."""

    def __init__(self, surface: str = "code", notify=None, catalog=None):
        self.surface = surface
        self.notify = notify or (lambda text, level="info": None)
        self.catalog, self.settings, self.problems = catalog if catalog is not None else load_catalog()
        self.servers: dict[str, McpServer] = {}
        self.enabled: dict[str, dict] = {}                   # name -> {"turn", "used", "why", "tools"}
        self.routes: dict[str, tuple[str, str]] = {}         # name the model sees -> (server, tool)
        self.turn = 0
        self.trusted: set[str] = set()                       # /mcp trust NAME: its `ask` tools stop asking this session
        self.lock = threading.RLock()
        self.on_change = None                                # the daemon re-sends its state
        self._timer = None
        self._defaults_done = False
        self.said: list[str] = []                            # the user's own words, for the recipient check
        self.page: dict[str, str] = {}                       # server -> the URL its browser is on, as last seen
        self.fetched: dict[str, tuple[float, str, int]] = {}   # fetch url#start -> (when, saved copy, characters)

    # ------------------------------------------------------------------ on and off
    @property
    def active(self) -> bool:
        return bool(self.catalog)

    def replaced(self) -> set[str]:
        """Built-in tool names the catalogue takes over (loaded on demand instead of always offered)."""
        return {r for e in self.catalog.values() if not e.unavailable(self.surface) for r in e.replaces}

    def enable(self, name: str, why: str = "") -> str:
        entry = self.catalog.get(name)
        if entry is None:
            return f"error: no MCP server named {name!r}. Available: {', '.join(self.catalog) or 'none'}"
        bad = entry.unavailable(self.surface)
        if bad:
            return f"error: {name} is {bad}"
        # notify() is never called under self.lock: the session's notice takes Session.lock, and the daemon calls
        # state() -> status() (self.lock) while holding Session.lock, so the two threads waited on each other for good
        with self.lock:
            if name in self.enabled:
                self.enabled[name]["turn"] = self.turn
                return f"{name} is already on: " + ", ".join(self.enabled[name]["tools"])
        if not entry.builtin:
            self.notify(f"starting MCP server {name}…")
        with self.lock:
            if name in self.enabled:                         # another thread turned it on meanwhile
                self.enabled[name]["turn"] = self.turn
                return f"{name} is already on: " + ", ".join(self.enabled[name]["tools"])
            srv = self.servers.get(name)
            if srv is None:
                srv = self.servers[name] = (BuiltinServer(entry.builtin) if entry.builtin
                                            else McpServer(name, entry.cfg, self.settings))
            if not srv.start():
                return f"error: {name} did not start: {srv.error}"
            tools = [t for t in srv.tools if not entry.allow or t["name"] in entry.allow]
            self.enabled[name] = {"turn": self.turn, "used": time.monotonic(), "why": why,
                                  "tools": [t["name"] for t in tools]}
            evicted = self._evict(keep=name)
            self._rebuild()
            if entry.idle_s:
                self._start_timer()
        for gone in evicted:
            self.notify(f"-{gone} (tool limit {self.settings['max_tools']})", "info")
        self.notify(f"+{name}" + (f" ({why})" if why else ""), "info")
        self._changed()
        return f"{name} is on. Its tools are available from your next step: " + ", ".join(
            n for n, (s, _) in self.routes.items() if s == name)

    def disable(self, name: str, why: str = "") -> str:
        with self.lock:
            if name not in self.enabled:
                return f"{name} is not on"
            del self.enabled[name]
            self.page.pop(name, None)                        # a new browser starts on no page
            srv = self.servers.pop(name, None)
            if srv is not None:
                srv.close()
            self._rebuild()
        self.notify(f"-{name}" + (f" ({why})" if why else ""), "info")
        self._changed()
        return f"{name} is off"

    def _evict(self, keep: str) -> list[str]:
        """Turn off the oldest servers over max_tools (under self.lock); the names, for the caller to announce
        after the lock."""
        evicted = []
        while sum(len(v["tools"]) for v in self.enabled.values()) > int(self.settings["max_tools"]):
            others = [(self.catalog[n].default_on, v["turn"], v["used"], n)   # defaults go last
                      for n, v in self.enabled.items() if n != keep]
            if not others:
                break
            name = min(others)[3]
            del self.enabled[name]
            self.page.pop(name, None)                        # a new browser starts on no page
            srv = self.servers.pop(name, None)
            if srv is not None:
                srv.close()
            evicted.append(name)
        return evicted

    def _rebuild(self) -> None:
        routes = {}
        for name in self.enabled:
            for tool in self.enabled[name]["tools"]:
                routes[f"{_clean(name)}__{_clean(tool)}"[:64]] = (name, tool)
        self.routes = routes

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - a UI refresh never breaks a turn
                pass

    def ensure_defaults(self) -> None:
        if self._defaults_done:
            return
        self._defaults_done = True
        for name, entry in self.catalog.items():
            if entry.default_on and not entry.unavailable(self.surface) and name not in self.enabled:
                self.enable(name, "default")

    # ------------------------------------------------------------------ turns
    def route(self, text: str, origin: str = "", mode: str | None = None) -> list[tuple[str, str]]:
        """Start of a user turn: count it, turn on default servers, origin-matched servers, and
        turn-matched servers according to router mode ('rules', 'model2vec', or 'hybrid')."""
        self.turn += 1
        if text:
            self.said.append(text)
        self.ensure_defaults()
        hits: list[tuple[str, str]] = []
        active_mode = dl_router.router_mode(mode, subsystem="mcp") if dl_router is not None else "rules"

        if active_mode == "rules":
            for name, entry in self.catalog.items():
                if name in self.enabled or entry.unavailable(self.surface):
                    continue
                if origin and any(origin == o or origin.startswith(o + "-") for o in entry.origins):
                    if not self.enable(name, f"prompt from {origin}").startswith("error"):
                        hits.append((name, origin))
                    continue
                if any(rx.search(text or "") for rx in entry.unless):
                    continue
                m = trigger_hit(entry, text)
                if m:
                    word = m.group(0)[:40]
                    if not self.enable(name, f"matched '{word}'").startswith("error"):
                        hits.append((name, word))
            return hits

        for name, entry in self.catalog.items():
            if name in self.enabled or entry.unavailable(self.surface):
                continue
            if origin and any(origin == o or origin.startswith(o + "-") for o in entry.origins):
                if not self.enable(name, f"prompt from {origin}").startswith("error"):
                    hits.append((name, origin))

        if active_mode == "model2vec" and dl_mcp_router is not None:
            m_hits, used_model = dl_mcp_router.route(
                text or "",
                self.catalog,
                surface=self.surface,
                enabled=self.enabled,
            )
            if used_model:
                for name, score in m_hits:
                    why = f"similar: {score:.2f}"
                    if not self.enable(name, why).startswith("error"):
                        hits.append((name, why))
                return hits
            if dl_router is not None:
                fb = dl_router.consume_fallback_notice()
                if fb:
                    self.notify(fb, "warn")

        regex_matched = False
        for name, entry in self.catalog.items():
            if name in self.enabled or entry.unavailable(self.surface):
                continue
            if any(rx.search(text or "") for rx in entry.unless):
                continue
            m = trigger_hit(entry, text)
            if m:
                word = m.group(0)[:40]
                regex_matched = True
                if not self.enable(name, f"matched '{word}'").startswith("error"):
                    hits.append((name, word))

        if active_mode == "hybrid" and not regex_matched and dl_mcp_router is not None:
            m_hits, used_model = dl_mcp_router.route(
                text or "",
                self.catalog,
                surface=self.surface,
                enabled=self.enabled,
            )
            if used_model:
                for name, score in m_hits:
                    why = f"similar: {score:.2f}"
                    if not self.enable(name, why).startswith("error"):
                        hits.append((name, why))
            elif dl_router is not None:
                fb = dl_router.consume_fallback_notice()
                if fb:
                    self.notify(fb, "warn")

        return hits

    def tick(self) -> None:
        """End of a user turn: turn off what went unused for idle_turns turns."""
        limit = int(self.settings["idle_turns"])
        with self.lock:                                      # the idle timer may switch one off meanwhile
            idle = [n for n, v in self.enabled.items()
                    if (e := self.catalog.get(n)) and not e.default_on and self.turn - v["turn"] >= limit]
        for name in idle:
            self.disable(name, f"unused for {limit} turns")

    def _start_timer(self) -> None:
        with self.lock:                                      # decided under the lock, as the loop's exit is
            if self._timer is not None and self._timer.is_alive():
                return

            def loop():
                while True:
                    time.sleep(15)
                    with self.lock:
                        idle = [n for n, v in self.enabled.items()
                                if self.catalog.get(n) and self.catalog[n].idle_s
                                and time.monotonic() - v["used"] > self.catalog[n].idle_s]
                        left = any(self.catalog[n].idle_s for n in self.enabled if n in self.catalog)
                        if not left and not idle:
                            self._timer = None               # a server enabled from now on starts a new timer
                            return
                    for n in idle:
                        self.disable(n, f"idle for {int(self.catalog[n].idle_s)} s")

            self._timer = threading.Thread(target=loop, daemon=True, name="dl-mcp-idle")
            self._timer.start()

    # ------------------------------------------------------------------ what the model sees
    def meta_tool(self) -> dict:
        lines = []
        for name, entry in self.catalog.items():
            bad = entry.unavailable(self.surface)
            lines.append(f"- {name}: {entry.short}" + (f" [{bad}]" if bad else ""))
        return {"type": "function", "function": {
            "name": META_NAME,
            "description": "Turn MCP tool servers on or off, when the user's request needs one (a greeting or a question "
                           "about yourself does not, and neither does one you can answer yourself: arithmetic, general "
                           "knowledge, wording). Their tools appear from your next step; action \"list\" says what "
                           "each server can do. Servers:\n"
                           + "\n".join(lines),
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "enable", "disable"]},
                "server": {"type": "string", "description": "Server name, or several comma-separated (\"drive,proton\")."},
                "reason": {"type": "string", "description": "Why the request needs the server (only when asked for it)."}},
                "required": ["action"]}}}

    def unasked_for(self, name: str, reason: str = "") -> str:
        """The answer to a model's `enable` of a server the user's request has no link to, or "" when it may go on.
        Only servers that act outside or start slowly are held (an `ask` tool or `idle_s`: the browser, mail, the
        smart home): the 2026-11-15 live check saw "17 times 23" turn on Playwright and wait on an approval card.  A
        link is one of the server's own triggers in the user's latest message; with none, the model is told to answer
        directly or to call again with `reason`, which then goes through (and is shown in the notice).  Off with
        "guard_model_enable": false in the settings."""
        if self.settings.get("guard_model_enable", True) is False or str(reason or "").strip():
            return ""
        entry = self.catalog.get(name)
        if entry is None or name in self.enabled or not (entry.ask or entry.idle_s):
            return ""
        text = self.said[-1] if self.said else ""
        if not text or trigger_hit(entry, text):
            return ""
        return (f"{name} was not turned on: the user's request does not seem to need it. Answer directly if you can; "
                f"if the request really needs {name}, call mcp again with reason=\"why\".")

    def _allowed_in(self, mode: str, name: str, tool: str) -> bool:
        if mode != "plan":
            return True
        entry = self.catalog[name]
        return entry.readonly or tool in entry.readonly_tools

    def tools(self, mode: str = "act") -> list[dict]:
        out = []
        with self.lock:
            for model_name, (name, tool) in self.routes.items():
                if not self._allowed_in(mode, name, tool):
                    continue
                srv = self.servers.get(name)
                t = next((x for x in (srv.tools if srv else []) if x["name"] == tool), None)
                if t is None:
                    continue
                schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
                fixed = self.catalog[name].fixed_args
                if fixed and schema:
                    schema = {**schema, "properties": {k: v for k, v in (schema.get("properties") or {}).items()
                                                       if k not in fixed},
                              "required": [k for k in schema.get("required") or [] if k not in fixed]}
                out.append({"type": "function", "function": {
                    "name": model_name, "description": str(t.get("description") or t.get("title") or "")[:1024],
                    "parameters": schema or {"type": "object", "properties": {}}}})
        return out

    def handle_meta(self, args: dict) -> str:
        action = str(args.get("action") or "list")
        raw = args.get("server") or ""
        names = [str(n).strip() for n in (raw if isinstance(raw, list) else str(raw).split(","))
                 if n is not None and str(n).strip()]
        if action in ("enable", "disable"):
            if not names:
                return f"error: say which server: mcp(action=\"{action}\", server=\"name\" or \"a,b\")"
            if action == "disable":
                return "\n".join(self.disable(n, "asked by the model") for n in names)
            reason = " ".join(str(args.get("reason") or "").split())[:120]
            why = "asked by the model" + (f": {reason}" if reason else "")
            return "\n".join(self.unasked_for(n, reason) or self.enable(n, why) for n in names)
        return "\n".join(f"{s['name']}: {'ON' if s['on'] else 'off'} - {s['description']}"
                         + (f" [{s['unavailable']}]" if s["unavailable"] else "") for s in self.status())

    def owns(self, model_name: str) -> bool:
        return model_name in self.routes

    def revive(self, model_name: str) -> bool:
        """A call to a tool of a server that was turned off (idle, evicted): turn the server back on.  True when
        the tool exists again."""
        server = model_name.split("__", 1)[0] if "__" in model_name else ""
        if server not in self.catalog or server in self.enabled:
            return False
        self.enable(server, "its tool was called after it was turned off")
        return self.owns(model_name)

    @staticmethod
    def _save_images(res: dict) -> list[str]:
        """Image blocks of a tool result (a Playwright screenshot) written to IMAGE_DIR, so the model can look at
        them; the paths."""
        import base64
        out = []
        for block in res.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "image" or not block.get("data"):
                continue
            ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(str(block.get("mimeType")), ".png")
            try:
                IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                path = IMAGE_DIR / f"shot-{time.strftime('%Y%m%d-%H%M%S')}-{len(out)}{ext}"
                path.write_bytes(base64.b64decode(block["data"]))
            except (OSError, ValueError):
                continue
            out.append(str(path))
        return out

    def _linked_images(self, name: str, text: str) -> list[str]:
        """A screenshot saved to a file instead of returned (Playwright with `filename`: '[Screenshot ...](./x.png)'),
        copied to IMAGE_DIR so the model sees it too (2026-11-14 18:18: Ray searched the whole disk for the file)."""
        links = SHOT_LINK.findall(text or "")
        if not links:
            return []
        import shutil
        base = self._out_dir(name)
        out = []
        for rel in links:
            src = (Path(os.path.expanduser(base)) / rel).resolve()
            if not src.is_file():
                continue
            try:
                IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                dst = IMAGE_DIR / f"shot-{time.strftime('%Y%m%d-%H%M%S')}-{len(out)}{src.suffix.lower()}"
                shutil.copyfile(src, dst)
            except OSError:
                continue
            out.append(str(dst))
        return out

    def _out_dir(self, name: str) -> str:
        """Where the server writes the files it names in results: its --output-dir, else its cwd."""
        args = [str(a) for a in (self.catalog[name].cfg.get("args") or [])] if name in self.catalog else []
        return (args[args.index("--output-dir") + 1] if "--output-dir" in args[:-1]
                else (self.catalog[name].cfg.get("cwd") if name in self.catalog else None) or os.getcwd())

    def _saved_text(self, name: str, text: str) -> str:
        """The text of files the result says it saved (console messages, page snapshots), up to SAVED_CAP characters
        in all, to append to the result; "" when there are none."""
        links = SAVED_LINK.findall(text or "")
        if not links:
            return ""
        base = Path(os.path.expanduser(self._out_dir(name))).resolve()
        out, left = [], SAVED_CAP
        for rel in dict.fromkeys(links):
            src = (base / rel).resolve()
            if left <= 0 or not src.is_file() or base not in src.parents:
                continue
            try:
                body = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            shown = body[:left]
            left -= len(shown)
            more = f"\n[... {len(body) - len(shown):,} more characters in {src}]" if len(shown) < len(body) else ""
            out.append(f"\n\n--- {rel} ({src}) ---\n{shown or '(empty)'}{more}")
        return "".join(out)

    def _save_fetch(self, key: str, text: str) -> None:
        import hashlib
        try:
            FETCH_DIR.mkdir(parents=True, exist_ok=True)
            path = FETCH_DIR / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".md")
            path.write_text(text, encoding="utf-8")
        except OSError:
            return
        self.fetched[key] = (time.time(), str(path), len(text))

    def _track_page(self, name: str, tool: str, args, text: str) -> None:
        """Remember which URL the server's browser shows: from a navigate call, then from the "Page URL:" line
        Playwright adds to its results (a click may have left the page)."""
        seen = PAGE_URL.findall(text or "")
        url = seen[-1] if seen else (args.get("url") if tool.endswith("navigate") and isinstance(args, dict) else None)
        if url:
            with self.lock:
                self.page[name] = str(url)

    def words_refusal(self, model_name: str, args: dict | None, text: str) -> str | None:
        """A refusal when the call is a words-gated action (DEFAULT_ASK_WORDS, an entry's ask_words) and the user's
        request (`text`: this turn's words plus the task it carries on) does not ask for it; None otherwise.  Applies
        in YOLO too: it is not a card."""
        name, tool = self.routes.get(model_name, (None, None))
        if name is None:
            return None
        entry = self.catalog.get(name)
        rule = (entry.ask_words.get(tool) if entry is not None else None) or DEFAULT_ASK_WORDS_RX.get(tool)
        if rule is None or asked_in_words(rule, args, text):
            return None
        return (f"Refused: {tool} runs only when the user asks for it in this request (their words do not). "
                "Do not retry it; answer without it, or ask the user whether they want it.")

    def leak(self, args) -> str | None:
        """An error text when the model's arguments carry a credential (an API key, the Google sign-in token, a value
        from secrets.env), or name a local file that holds one (an attachment, a Drive upload): nothing that leaves
        through an MCP server - an email, a Drive file, a fetch URL, typed text - may contain one."""
        strings = []

        def walk(v):
            if isinstance(v, str):
                strings.append(v)
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)
        walk(args)
        clean, detail = scan_secrets_in_text("\n".join(strings), "outgoing")
        found = [] if clean else [l for l in detail.splitlines() if l.lstrip().startswith("•")]
        found += [f"  • {why}" for why in filter(None, map(file_leak, _local_files(args)))]
        if not found:
            return None
        return ("error: BLOCKED - the arguments contain a credential, and it must never leave this PC:\n"
                + "\n".join(found)
                + "\nRemove it. Do not retry with the value encoded or split; tell the user instead.")

    def call(self, model_name: str, args: dict, mode: str = "act", cancel=None) -> str:
        name, tool = self.routes.get(model_name, (None, None))
        if name is None:
            return f"error: there is no tool named {model_name!r} (its server may have been turned off; use mcp)"
        blocked = self.leak(args)
        if blocked:
            return blocked
        if not self._allowed_in(mode, name, tool):
            return f"error: [PLAN MODE] {model_name} can change things and is disabled in Plan Mode"
        bad = self.unknown_args(model_name, args)
        if bad:
            return bad
        if tool in ("send_mail", "send_gmail_message"):
            try:
                import dl_translate
                err = dl_translate.check_email_language(
                    body=str(args.get("body") or ""),
                    html=str(args.get("html") or args.get("html_body") or ""),
                    html_file=args.get("html_file"),
                )
                if err:
                    return err
            except ImportError:
                pass
        # a page on this PC is one being built: it changes between fetches, so it is never answered from the copy
        fetch_key = (f"{args.get('url')}#{args.get('start_index') or 0}"
                     if name == "fetch" and tool == "fetch" and isinstance(args, dict) and args.get("url")
                     and not is_local_url(str(args.get("url"))) else None)
        seen = self.fetched.get(fetch_key) if fetch_key else None
        if seen and time.time() - seen[0] < FETCH_REUSE_S and Path(seen[1]).is_file():
            return (f"Already fetched at {time.strftime('%H:%M', time.localtime(seen[0]))} in this session; the "
                    f"text ({seen[2]:,} characters) is saved at {seen[1]}. Read the part you need with view_file "
                    f"(StartLine/EndLine) or grep it there instead of fetching the page again.")
        with self.lock:
            on, srv = self.enabled.get(name), self.servers.get(name)
            if on is None or srv is None:                    # turned off (idle, tool limit) since it was routed
                return f"error: {name} was just turned off; call the tool again"
            on["turn"], on["used"] = self.turn, time.monotonic()
        try:
            args = {**(args if isinstance(args, dict) else {}), **self.catalog[name].fixed_args}
            res = srv.call(tool, args, float(self.catalog[name].timeout_s or self.settings["timeout_s"]), cancel)
            text = result_text(res)
            shots = (self._save_images(res) or self._linked_images(name, text)) if not res.get("isError") else []
            if shots:                           # dl_cli shows these to the model as images (tool_result_images)
                text += "".join(f"\n[[image: {p}]]" for p in shots)
            if not res.get("isError"):
                text += self._saved_text(name, text)
            if res.get("isError"):
                text = "error: " + (text or "the tool reported an error")
            else:
                self._track_page(name, tool, args, text)
                if fetch_key and text:
                    self._save_fetch(fetch_key, text)
        except McpCancelled:
            return "error: stopped"
        except McpError as e:
            text = f"error: {e}"
        cap = int(self.settings["max_result_chars"])
        if cap > 0 and len(text) > cap:
            text = text[:cap] + f"\n\n[... truncated: {len(text):,} characters, only the first {cap:,} shown]"
        with self.lock:
            if name in self.enabled:
                self.enabled[name]["used"] = time.monotonic()
        return text

    def schema(self, model_name: str) -> dict | None:
        """The tool's input schema as the server listed it, or None while its server is off."""
        name, tool = self.routes.get(model_name, (None, None))
        srv = self.servers.get(name) if name else None
        t = next((x for x in (srv.tools if srv else []) if x["name"] == tool), None)
        return t.get("inputSchema") if t and isinstance(t.get("inputSchema"), dict) else None

    def unknown_args(self, model_name: str, args) -> str | None:
        """An error for parameters the tool does not have: a server would ignore them silently (an `html_body` that
        never reached the email), so the model learns the right names instead."""
        schema = self.schema(model_name) or {}
        props = schema.get("properties") or {}
        if not props or not isinstance(args, dict):
            return None
        name = self.routes.get(model_name, (None, None))[0]
        if name is None:                                     # turned off since schema() looked: call() reports it
            return None
        extra = [k for k in args if k not in props and k not in self.catalog[name].fixed_args]
        if not extra:
            return None
        allowed = ", ".join(k for k in props if k not in self.catalog[name].fixed_args)
        return (f"error: {model_name} has no parameter {', '.join(map(repr, extra))}; nothing was done. "
                f"Its parameters: {allowed}.")

    # ------------------------------------------------------------------ approvals
    def approval(self, model_name: str, args: dict, user_texts: list[str] | None = None) -> tuple[str, str, bool] | None:
        """(summary, reason, always) when a call needs the user's yes outside YOLO; `always`: an email or a share, shown
        in full (the card a /yolo session never sees).  `user_texts`: what
        the user typed (default: every message routed in this session) - a recipient not in it is flagged."""
        user_texts = self.said if user_texts is None else user_texts
        name, tool = self.routes.get(model_name, (None, None))
        if name is None:
            return None
        entry = self.catalog[name]
        args = {**(args or {}), **entry.fixed_args}         # the card shows what is really sent (e.g. the sender)
        act = args.get("action")
        if isinstance(act, dict) and isinstance(act.get("args"), dict):
            # a scheduled action: approved now, run later exactly so - the card shows its every argument
            args = {**{k: v for k, v in args.items() if k != "action"}, "action": str(act.get("tool")),
                    **act["args"]}
        if tool in entry.ask_always or any((args or {}).get(a) for a in entry.ask_always_args.get(tool, [])):
            rcpt, body = [], ""
            for k, v in (args or {}).items():
                if RECIPIENT_KEY.match(str(k)):
                    rcpt += [a for s in _strings(v) for a in EMAIL.findall(s)]
                elif BODY_KEY.match(str(k)) and not body:
                    body = " ".join(_strings(v))
            body = body or _email_text(args)                 # an HTML email (html / html_file): its text, in full
            said = " ".join(user_texts).lower() + " " + _profile_email()      # "send me": the user's own address
            # a whole address: not inside a longer one, but a full stop after it ends the sentence ("to a@x.com.")
            foreign = [a for a in rcpt
                       if not re.search(rf"(?<![\w.%+-]){re.escape(a.lower())}(?![\w-]|\.\w)", said)]
            lines = [f"{name}: {tool}"]
            for k, v in (args or {}).items():
                if not BODY_KEY.match(str(k)) and k != "html":
                    lines.append(f"  {k}: {' '.join(_strings(v)) if not isinstance(v, (int, float)) else v}"[:300])
            if body:
                lines.append("  body:\n    " + body[:1500].replace("\n", "\n    ") + (" …" if len(body) > 1500 else ""))
            reason = ("scheduled: approved now, runs later exactly as shown"
                      if isinstance(act, dict) else "sends or shares on your behalf")
            if foreign:
                reason += " · ADDRESS NOT FROM YOU: " + ", ".join(foreign)
            return "\n".join(lines), reason, True
        if tool in entry.ask:
            # the page it is on, and where the call goes: a navigate from a localhost page to a remote url is not local
            target = (args or {}).get("url")
            if entry.trust_local_pages and is_local_url(self.page.get(name, "")) and \
                    (not isinstance(target, str) or not target or is_local_url(target)):
                return None
            if name in self.trusted:
                return None
            preview = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in (args or {}).items() if k not in entry.ask_full_args)
            full = [f"  {k}:\n    " + str(v)[:4000].replace("\n", "\n    ") + (" …" if len(str(v)) > 4000 else "")
                    for k, v in (args or {}).items() if k in entry.ask_full_args]
            return "\n".join([f"{name}: {tool}({preview})"] + full), entry.ask_reason, False
        return None

    # ------------------------------------------------------------------ state
    def status(self) -> list[dict]:
        with self.lock:
            return [{"name": n, "on": n in self.enabled, "description": e.description,
                     "why": (self.enabled.get(n) or {}).get("why", ""),
                     "tools": len((self.enabled.get(n) or {}).get("tools", [])),
                     "unavailable": e.unavailable(self.surface) or ""} for n, e in self.catalog.items()]

    def command(self, arg: str) -> str:
        """/mcp, /mcp on NAME, /mcp off NAME, /mcp trust NAME, /mcp ask NAME."""
        sub, _, name = arg.strip().partition(" ")
        name = name.strip()
        if sub in ("trust", "ask") and name:
            # the user's own switch (never the model's mcp tool): NAME's `ask` tools run without the card this session
            if name not in self.catalog or not self.catalog[name].ask:
                return f"{name}: no tools that ask (see /mcp)."
            if sub == "trust":
                self.trusted.add(name)
                return f"{name}: its tools run without asking for the rest of this session (/mcp ask {name} to undo)."
            self.trusted.discard(name)
            return f"{name}: asks again before each call."
        if sub in ("on", "enable") and name:
            return self.enable(name, "/mcp on")
        if sub in ("off", "disable") and name:
            return self.disable(name, "/mcp off")
        if not self.catalog:
            return (f"No MCP servers configured ({CATALOG_PATH} not found)."
                    + ("\n" + "\n".join(self.problems) if self.problems else "")
                    + "\nBuilt in, always on: " + ", ".join(n for n, _ in BUILT_IN))
        rows = [f"{'●' if s['on'] else '○'} {s['name']:<12} {s['description']}"
                + (f"  [{s['tools']} tool{'s' if s['tools'] != 1 else ''}; {s['why']}]" if s["on"] else "")
                + (f"  ({s['unavailable']})" if s["unavailable"] else "") for s in self.status()]
        rows += [f"! {p}" for p in self.problems]
        always = [(n, d) for n, d in BUILT_IN if n not in self.catalog]
        if always:
            rows += ["", "Built in, always on (not in mcp.json):"] + [f"● {n:<12} {d}" for n, d in always]
        return "\n".join(rows) + "\n\n/mcp on NAME · /mcp off NAME · /mcp trust NAME (no card this session) · /mcp ask NAME · servers also turn on by themselves when a request needs them"

    def close(self) -> None:
        with self.lock:
            for srv in self.servers.values():
                try:
                    srv.close()
                except Exception:  # noqa: BLE001 - closing is best effort
                    pass
            self.servers.clear()
            self.enabled.clear()
            self.trusted.clear()                     # a new conversation asks again
            self.page.clear()
            self.routes.clear()
            self._defaults_done = False
