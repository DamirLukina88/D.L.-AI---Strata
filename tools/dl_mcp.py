#!/usr/bin/env python3
"""dl_mcp.py - MCP servers for D.L. CLI, started only while a request needs them.

Every tool schema D.L. CLI offers is sent again with every turn, and the local model pays for it in prefill time.  So
the servers in ~/.config/dl-ai/mcp.json (DL_MCP_CONFIG overrides the path) are not loaded up front:

- a router turns a server on before the model call when the user's message matches one of its `triggers` (regexes;
  English, Croatian and German words), and the model can turn one on itself with the small `mcp` tool, whose
  description lists the catalogue in one line per server;
- a server whose tools went unused for `idle_turns` user turns is turned off again (and one with `idle_s`, such as a
  browser, after that many idle seconds); `"default": "on"` servers stay;
- only the tools in a server's `allow` list reach the model, at most `max_tools` at once (the server used longest
  ago is turned off first).

The MCP client is serve/mcp.py's McpServer (stdio and Streamable HTTP, restart after a crash).  A server gets only
PATH, HOME and a few more of our variables (`env_inherit`) plus the keys it names in `env_from_secrets`, never the
whole secrets file.  `surfaces` limits where a server may run ("code": the shared session daemon, the web Code tab
and `dl_cli.py --attach`; "terminal": the stand-alone REPL).  Tools in `ask` need the user's approval (YOLO skips it);
tools in `ask_always` need it every time, YOLO or not (sending email).

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

# D.L. CLI's own tools that are not in the catalogue; /mcp lists them so every outside service shows in one place
BUILT_IN = [("exa", "Web search (Exa web API, not MCP): exa_web_search, /exa <query>"),
            ("context7", "Library docs (Context7 MCP, started for each lookup): resolve_library_id, get_library_docs, /context7 <lib>")]
CATALOG_PATH = Path(os.environ.get("DL_MCP_CONFIG") or Path.home() / ".config" / "dl-ai" / "mcp.json")
ENV_INHERIT = ["PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "XDG_RUNTIME_DIR", "XDG_CACHE_HOME",
               "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"]
SETTINGS = {"max_tools": 25, "idle_turns": 3, "timeout_s": 120.0, "start_timeout_s": 180.0,
            "max_result_chars": DEFAULTS["max_result_chars"]}
META_NAME = "mcp"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RECIPIENT_KEY = re.compile(r"^(to|cc|bcc|recipients?|send_?to|share_?with|new_owner_email)$", re.I)
BODY_KEY = re.compile(r"^(body|text|content|message|html_?body|plain_?body)$", re.I)


class Entry:
    """One catalogue server: the MCP config for McpServer and D.L. CLI's own fields."""

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.description = str(raw.get("description") or name)
        self.default_on = raw.get("default") == "on"
        self.allow = list(raw.get("allow") or [])            # empty: every tool the server lists
        self.readonly = raw.get("readonly") is True
        self.readonly_tools = set(raw.get("readonly_tools") or [])
        self.ask = set(raw.get("ask") or [])
        self.ask_always = set(raw.get("ask_always") or [])
        # {"tool": ["arg", ...]}: the call always asks when one of these arguments is set (e.g. trashed=true)
        self.ask_always_args = {str(k): list(v) for k, v in (raw.get("ask_always_args") or {}).items()}
        # "ask" tools run without asking while the server's page is local (file://, localhost): the agent testing
        # its own work in a browser.  Opt-in per server; anything else, or a page not known yet, still asks.
        self.trust_local_pages = raw.get("trust_local_pages") is True
        self.surfaces = list(raw.get("surfaces") or [])      # empty: everywhere
        self.idle_s = float(raw.get("idle_s") or 0)
        # arguments set here, hidden from the model and added to every call (e.g. the Google account)
        self.fixed_args = {str(k): v for k, v in (raw.get("fixed_args") or {}).items()}
        self.triggers = [re.compile(t, re.I) for t in raw.get("triggers") or []]
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
    for name, raw in (data.get("servers") or {}).items():
        if not isinstance(raw, dict) or raw.get("disabled") is True:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) or name == META_NAME:
            problems.append(f"{path}: server name {name!r} must be 1-32 letters, digits, - or _ (and not 'mcp')")
            continue
        try:
            servers[name] = Entry(name, raw)
        except (SystemExit, re.error, TypeError, ValueError) as e:
            problems.append(f"{path}: server {name!r}: {e}")
    settings = dict(SETTINGS)
    settings.update({k: v for k, v in (data.get("settings") or {}).items() if k in SETTINGS})
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
FILE_KEY = re.compile(r"^(path|file_?path|file_?url|fileUrl|url|source|local_?path)$", re.I)
PRIVATE_DIRS = [Path.home() / ".config" / "dl-ai", Path.home() / ".ssh", Path.home() / ".gnupg",
                Path.home() / ".aws", Path.home() / ".kube", Path.home() / ".docker"]
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
        self.lock = threading.RLock()
        self.on_change = None                                # the daemon re-sends its state
        self._timer = None
        self._defaults_done = False
        self.said: list[str] = []                            # the user's own words, for the recipient check
        self.page: dict[str, str] = {}                       # server -> the URL its browser is on, as last seen

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
        with self.lock:
            if name in self.enabled:
                self.enabled[name]["turn"] = self.turn
                return f"{name} is already on: " + ", ".join(self.enabled[name]["tools"])
            srv = self.servers.get(name)
            if srv is None:
                srv = self.servers[name] = (BuiltinServer(entry.builtin) if entry.builtin
                                            else McpServer(name, entry.cfg, self.settings))
            if not entry.builtin:
                self.notify(f"starting MCP server {name}…")
            if not srv.start():
                return f"error: {name} did not start: {srv.error}"
            tools = [t for t in srv.tools if not entry.allow or t["name"] in entry.allow]
            self.enabled[name] = {"turn": self.turn, "used": time.monotonic(), "why": why,
                                  "tools": [t["name"] for t in tools]}
            self._evict(keep=name)
            self._rebuild()
            if entry.idle_s:
                self._start_timer()
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

    def _evict(self, keep: str) -> None:
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
            self.notify(f"-{name} (tool limit {self.settings['max_tools']})", "info")

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
    def route(self, text: str) -> list[tuple[str, str]]:
        """Start of a user turn: count it, turn on the default servers and every server a trigger matches."""
        self.turn += 1
        if text:
            self.said.append(text)
        self.ensure_defaults()
        hits = []
        for name, entry in self.catalog.items():
            if name in self.enabled or entry.unavailable(self.surface):
                continue
            for rx in entry.triggers:
                m = rx.search(text or "")
                if m:
                    word = m.group(0)[:40]
                    if not self.enable(name, f"matched '{word}'").startswith("error"):
                        hits.append((name, word))
                    break
        return hits

    def tick(self) -> None:
        """End of a user turn: turn off what went unused for idle_turns turns."""
        limit = int(self.settings["idle_turns"])
        for name in list(self.enabled):
            entry = self.catalog.get(name)
            if entry and not entry.default_on and self.turn - self.enabled[name]["turn"] >= limit:
                self.disable(name, f"unused for {limit} turns")

    def _start_timer(self) -> None:
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
                for n in idle:
                    self.disable(n, f"idle for {int(self.catalog[n].idle_s)} s")
                if not left and not idle:
                    return

        self._timer = threading.Thread(target=loop, daemon=True, name="dl-mcp-idle")
        self._timer.start()

    # ------------------------------------------------------------------ what the model sees
    def meta_tool(self) -> dict:
        lines = []
        for name, entry in self.catalog.items():
            bad = entry.unavailable(self.surface)
            lines.append(f"- {name}: {entry.description}" + (f" [{bad}]" if bad else ""))
        return {"type": "function", "function": {
            "name": META_NAME,
            "description": "Turn MCP tool servers on or off. Their tools appear from your next step. Servers:\n"
                           + "\n".join(lines),
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["list", "enable", "disable"]},
                "server": {"type": "string", "description": "Server name, for enable and disable."}},
                "required": ["action"]}}}

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
        server = str(args.get("server") or "")
        if action == "enable":
            return self.enable(server, "asked by the model")
        if action == "disable":
            return self.disable(server, "asked by the model")
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

    def _track_page(self, name: str, tool: str, args, text: str) -> None:
        """Remember which URL the server's browser shows: from a navigate call, then from the "Page URL:" line
        Playwright adds to its results (a click may have left the page)."""
        seen = PAGE_URL.findall(text or "")
        url = seen[-1] if seen else (args.get("url") if tool.endswith("navigate") and isinstance(args, dict) else None)
        if url:
            with self.lock:
                self.page[name] = str(url)

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
        with self.lock:
            self.enabled[name]["turn"] = self.turn
            self.enabled[name]["used"] = time.monotonic()
            srv = self.servers[name]
        try:
            args = {**(args if isinstance(args, dict) else {}), **self.catalog[name].fixed_args}
            res = srv.call(tool, args, float(self.settings["timeout_s"]), cancel)
            text = result_text(res)
            if res.get("isError"):
                text = "error: " + (text or "the tool reported an error")
            else:
                self._track_page(name, tool, args, text)
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

    # ------------------------------------------------------------------ approvals
    def approval(self, model_name: str, args: dict, user_texts: list[str] | None = None) -> tuple[str, str, bool] | None:
        """(summary, reason, always) when a call needs the user's yes; `always`: even in YOLO.  `user_texts`: what
        the user typed (default: every message routed in this session) - a recipient not in it is flagged."""
        user_texts = self.said if user_texts is None else user_texts
        name, tool = self.routes.get(model_name, (None, None))
        if name is None:
            return None
        entry = self.catalog[name]
        if tool in entry.ask_always or any((args or {}).get(a) for a in entry.ask_always_args.get(tool, [])):
            rcpt, body = [], ""
            for k, v in (args or {}).items():
                if RECIPIENT_KEY.match(str(k)):
                    rcpt += [a for s in _strings(v) for a in EMAIL.findall(s)]
                elif BODY_KEY.match(str(k)) and not body:
                    body = " ".join(_strings(v))
            said = " ".join(user_texts).lower()
            foreign = [a for a in rcpt if a.lower() not in said]
            lines = [f"{name}: {tool}"]
            for k, v in (args or {}).items():
                if not BODY_KEY.match(str(k)):
                    lines.append(f"  {k}: {' '.join(_strings(v)) if not isinstance(v, (int, float)) else v}"[:300])
            if body:
                lines.append("  body:\n    " + body[:1500].replace("\n", "\n    ") + (" …" if len(body) > 1500 else ""))
            reason = "sends on your behalf; always asks, even in YOLO"
            if foreign:
                reason += " · ADDRESS NOT FROM YOU: " + ", ".join(foreign)
            return "\n".join(lines), reason, True
        if tool in entry.ask:
            if entry.trust_local_pages and is_local_url(self.page.get(name, "")):
                return None
            preview = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in (args or {}).items())
            return f"{name}: {tool}({preview})", "acts in the browser / outside D.L. CLI", False
        return None

    # ------------------------------------------------------------------ state
    def status(self) -> list[dict]:
        with self.lock:
            return [{"name": n, "on": n in self.enabled, "description": e.description,
                     "why": (self.enabled.get(n) or {}).get("why", ""),
                     "tools": len((self.enabled.get(n) or {}).get("tools", [])),
                     "unavailable": e.unavailable(self.surface) or ""} for n, e in self.catalog.items()]

    def command(self, arg: str) -> str:
        """/mcp, /mcp on NAME, /mcp off NAME."""
        sub, _, name = arg.strip().partition(" ")
        name = name.strip()
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
        return "\n".join(rows) + "\n\n/mcp on NAME · /mcp off NAME · servers also turn on by themselves when a request needs them"

    def close(self) -> None:
        with self.lock:
            for srv in self.servers.values():
                try:
                    srv.close()
                except Exception:  # noqa: BLE001 - closing is best effort
                    pass
            self.servers.clear()
            self.enabled.clear()
            self.page.clear()
            self.routes.clear()
            self._defaults_done = False
