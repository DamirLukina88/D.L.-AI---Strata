# scan-secrets: fake-fixtures (the Google tokens below are made up to test the credential filter)
"""tools/test_dl_mcp.py - D.L. CLI's on-demand MCP servers (tools/dl_mcp.py) against serve/mcp_fake_server.py:
the router, allowlists, the tool limit, idle shutdown, Plan Mode, surfaces, approvals and the environment a server
gets.  No model, no network.

    python tools/test_dl_mcp.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_mcp  # noqa: E402

FAKE = str(HERE.parent / "serve" / "mcp_fake_server.py")


def server(**extra):
    return {"command": sys.executable, "args": [FAKE], "description": "a fake server", **extra}


CATALOG = {
    "servers": {
        "fetch": server(description="Read a web page", default="on", allow=["echo"], readonly=True,
                        triggers=[r"https?://\S+"]),
        "deepl": server(description="Translate text", allow=["echo", "add"], readonly=True,
                        triggers=["translat", "prevedi", "übersetz"]),
        "browser": server(description="A browser", allow=["echo", "add", "getenv"], readonly_tools=["echo"],
                          ask=["add"], triggers=["klikni", r"\bclick\b"]),
        "google": server(description="Gmail", allow=["echo", "add"], surfaces=["code"], ask_always=["echo"],
                         readonly_tools=["add"], triggers=[r"e-?mail", "pošalji"]),
        "needskey": server(description="Needs a key", env_from_secrets=["DL_TEST_NO_SUCH_KEY"], triggers=["keyed"]),
    },
    "settings": {"max_tools": 5, "idle_turns": 2, "timeout_s": 10},
}


def registry(surface="code", catalog=CATALOG):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(catalog, f)
    try:
        return dl_mcp.McpRegistry(surface=surface, catalog=dl_mcp.load_catalog(Path(f.name)))
    finally:
        os.unlink(f.name)


class Router(unittest.TestCase):
    def setUp(self):
        self.r = registry()

    def tearDown(self):
        self.r.close()

    def test_default_server_is_on_from_the_first_turn(self):
        self.assertEqual(self.r.route("hello"), [])
        self.assertEqual(list(self.r.enabled), ["fetch"])
        self.assertEqual([t["function"]["name"] for t in self.r.tools()], ["fetch__echo"])

    def test_words_in_three_languages(self):
        for text, want in (("prevedi ovo na njemački", "deepl"), ("Bitte übersetze das", "deepl"),
                           ("please translate this", "deepl"), ("pošalji mi izvještaj", "google"),
                           ("send an e-mail to me", "google"), ("klikni na gumb", "browser")):
            with self.subTest(text=text):
                r = registry()
                try:
                    self.assertEqual([n for n, _ in r.route(text)], [want])
                finally:
                    r.close()

    def test_unrelated_text_turns_nothing_on(self):
        self.r.route("refactor the parser in serve/frontend.py")
        self.assertEqual(list(self.r.enabled), ["fetch"])

    def test_allowlist_hides_tools(self):
        self.r.route("translate it")
        self.assertEqual(sorted(n for n in self.r.routes if n.startswith("deepl__")), ["deepl__add", "deepl__echo"])

    def test_idle_turns_turn_a_server_off_but_not_a_default(self):
        self.r.route("translate it")
        self.r.tick()
        self.assertIn("deepl", self.r.enabled)
        self.r.route("something else")
        self.r.tick()
        self.assertIn("deepl", self.r.enabled)          # idle_turns=2: two unused turns after the one that used it
        self.r.route("and more")
        self.r.tick()
        self.assertNotIn("deepl", self.r.enabled)
        self.assertIn("fetch", self.r.enabled)

    def test_a_used_server_stays(self):
        self.r.route("translate it")
        self.r.tick()
        self.r.route("again")
        self.assertEqual(self.r.call("deepl__add", {"a": 1, "b": 2}), "3")
        self.r.tick()
        self.assertIn("deepl", self.r.enabled)

    def test_tool_limit_turns_off_the_oldest(self):
        self.r.route("translate")                       # fetch 1 + deepl 2
        self.r.route("click it")                        # + browser 3 = 6 > 5: deepl (older) goes
        self.assertIn("browser", self.r.enabled)
        self.assertNotIn("deepl", self.r.enabled)
        self.assertLessEqual(len(self.r.routes), 5)

    def test_meta_tool_lists_and_enables(self):
        meta = self.r.meta_tool()["function"]
        self.assertEqual(meta["name"], "mcp")
        self.assertIn("- deepl: Translate text", meta["description"])
        self.assertIn("needs DL_TEST_NO_SUCH_KEY", meta["description"])
        self.assertTrue(self.r.handle_meta({"action": "enable", "server": "deepl"}).startswith("deepl is on"))
        self.assertIn("deepl__echo", self.r.routes)
        self.assertIn("deepl: ON", self.r.handle_meta({"action": "list"}))
        self.assertEqual(self.r.handle_meta({"action": "disable", "server": "deepl"}), "deepl is off")

    def test_missing_secret_is_refused(self):
        self.assertIn("needs DL_TEST_NO_SUCH_KEY", self.r.enable("needskey"))
        self.assertEqual(self.r.route("keyed"), [])


class Surfaces(unittest.TestCase):
    def test_google_only_in_code_sessions(self):
        r = registry(surface="terminal")
        try:
            self.assertEqual(r.route("pošalji mail"), [])
            self.assertIn("only available in the Code tab", r.enable("google"))
            self.assertIn("[only available", r.meta_tool()["function"]["description"])
        finally:
            r.close()


class PlanMode(unittest.TestCase):
    def test_only_readonly_tools(self):
        r = registry()
        try:
            r.enable("browser")
            r.enable("deepl")
            names = {t["function"]["name"] for t in r.tools("plan")}
            self.assertIn("browser__echo", names)        # readonly_tools
            self.assertNotIn("browser__add", names)
            self.assertIn("deepl__add", names)           # readonly server
            self.assertIn("Plan Mode", r.call("browser__add", {"a": 1, "b": 1}, mode="plan"))
        finally:
            r.close()


class Approvals(unittest.TestCase):
    def setUp(self):
        self.r = registry()
        self.r.enable("google")
        self.r.enable("browser")

    def tearDown(self):
        self.r.close()

    def test_send_always_asks_and_shows_the_mail(self):
        summary, reason, always = self.r.approval(
            "google__echo", {"to": "me@example.com", "subject": "Test", "body": "Hello\nthere"},
            ["send me@example.com a test mail"])
        self.assertTrue(always)
        self.assertIn("to: me@example.com", summary)
        self.assertIn("subject: Test", summary)
        self.assertIn("Hello\n    there", summary)
        self.assertNotIn("NOT FROM YOU", reason)

    def test_an_address_the_user_never_gave_is_flagged(self):
        _, reason, _ = self.r.approval("google__echo", {"to": ["me@example.com", "evil@attacker.test"]},
                                       ["send me@example.com the report"])
        self.assertIn("ADDRESS NOT FROM YOU: evil@attacker.test", reason)

    def test_browser_clicks_ask_but_not_always(self):
        summary, _, always = self.r.approval("browser__add", {"a": 1}, [])
        self.assertFalse(always)
        self.assertIn("browser: add", summary)
        self.assertIsNone(self.r.approval("browser__echo", {"text": "x"}, []))
        self.assertIsNone(self.r.approval("google__add", {}, []))


class FixedArgs(unittest.TestCase):
    def test_fixed_args_are_hidden_and_always_sent(self):
        r = registry(catalog={"servers": {"s": server(allow=["echo"], fixed_args={"text": "me@example.com"})}})
        try:
            r.enable("s")
            schema = r.tools()[0]["function"]["parameters"]
            self.assertNotIn("text", schema["properties"])
            self.assertNotIn("text", schema.get("required", []))
            self.assertEqual(r.call("s__echo", {}), "me@example.com")
            self.assertEqual(r.call("s__echo", {"text": "other@evil.test"}), "me@example.com")   # ours wins
        finally:
            r.close()


class AskAlwaysArgs(unittest.TestCase):
    def test_an_argument_can_make_a_call_always_ask(self):
        r = registry(catalog={"servers": {"s": server(allow=["add"], ask=["add"], ask_always_args={"add": ["b"]})}})
        try:
            r.enable("s")
            self.assertFalse(r.approval("s__add", {"a": 1})[2])
            self.assertTrue(r.approval("s__add", {"a": 1, "b": True})[2])
        finally:
            r.close()


class Environment(unittest.TestCase):
    def test_server_gets_only_inherited_and_named_variables(self):
        os.environ["EXA_API_KEY"] = "do-not-leak"
        os.environ["DL_TEST_KEY"] = "named"
        cat = {"servers": {"s": server(allow=["getenv"], env_from_secrets=["DL_TEST_KEY"])}}
        r = registry(catalog=cat)
        try:
            r.enable("s")
            self.assertEqual(r.call("s__getenv", {"name": "EXA_API_KEY"}), "<unset>")
            self.assertEqual(r.call("s__getenv", {"name": "DL_TEST_KEY"}), "named")
            self.assertNotEqual(r.call("s__getenv", {"name": "PATH"}), "<unset>")
        finally:
            r.close()
            del os.environ["EXA_API_KEY"], os.environ["DL_TEST_KEY"]


class Robustness(unittest.TestCase):
    def test_crash_restarts_on_next_call(self):
        cat = {"servers": {"s": server(allow=["echo", "die"])}}
        r = registry(catalog=cat)
        try:
            r.enable("s")
            self.assertTrue(r.call("s__die", {}).startswith("error:"))
            self.assertEqual(r.call("s__echo", {"text": "back"}), "back")
        finally:
            r.close()

    def test_no_catalogue_means_inactive(self):
        r = dl_mcp.McpRegistry(catalog=dl_mcp.load_catalog(Path("/nonexistent/mcp.json")))
        self.assertFalse(r.active)
        self.assertEqual(r.route("translate https://x.y"), [])
        self.assertEqual(r.tools(), [])

    def test_broken_entry_is_reported_not_fatal(self):
        cat = {"servers": {"ok": server(), "bad": {"description": "no command"}, "mcp": server()}}
        r = registry(catalog=cat)
        self.assertEqual(list(r.catalog), ["ok"])
        self.assertEqual(len(r.problems), 2)

    def test_unknown_tool(self):
        r = registry()
        self.assertTrue(r.call("nope__x", {}).startswith("error: there is no tool"))


class CliHooks(unittest.TestCase):
    """dl_cli's side: the tool list, dispatch and the approval gate, with and without a catalogue."""

    @classmethod
    def setUpClass(cls):
        import dl_cli
        cls.cli = dl_cli

    def test_no_registry_or_no_catalogue_keeps_todays_tool_list(self):
        ws = Path(tempfile.mkdtemp())
        before = json.dumps(self.cli.get_active_tools(ws, "act"))
        empty = dl_mcp.McpRegistry(catalog=dl_mcp.load_catalog(Path("/nonexistent/mcp.json")))
        self.assertEqual(json.dumps(self.cli.get_active_tools(ws, "act", registry=empty)), before)
        self.assertTrue(self.cli.dispatch_dl_tool("mcp", {}, ws, session_context={"mcp": empty})
                        .startswith("Error: Unknown tool mcp."))      # followed by the tools it does have

    def test_dispatch_routes_and_yolo_never_asks(self):
        ws = Path(tempfile.mkdtemp())
        r = registry()
        asked = []
        ctx = {"mcp": r, "yolo": False, "approve": lambda kind, summary, reason: asked.append(kind) or False}
        try:
            r.route("pošalji mail na me@example.com")
            names = [t["function"]["name"] for t in self.cli.get_active_tools(ws, "act", registry=r)]
            self.assertIn("mcp", names)
            self.assertIn("google__echo", names)
            out = self.cli.dispatch_dl_tool("google__echo", {"text": "hi to me@example.com"}, ws, session_context=ctx)
            self.assertEqual(asked, ["mcp-always"])            # sending asks outside YOLO
            self.assertTrue(out.startswith("Denied by user"))
            r.enable("browser")
            self.assertTrue(self.cli.dispatch_dl_tool("browser__add", {"a": 2, "b": 3}, ws,
                                                      session_context=ctx).startswith("Denied"))
            self.assertEqual(asked, ["mcp-always", "tool"])
            ctx["yolo"] = True                                  # YOLO: fully autonomous, sending included
            self.assertEqual(self.cli.dispatch_dl_tool("google__echo", {"text": "hi"}, ws, session_context=ctx), "hi")
            self.assertEqual(self.cli.dispatch_dl_tool("browser__add", {"a": 2, "b": 3}, ws, session_context=ctx), "5")
            self.assertEqual(asked, ["mcp-always", "tool"])
            self.assertIn("deepl", self.cli.dispatch_dl_tool("mcp", {"action": "list"}, ws, session_context=ctx))
            # a parameter the tool does not have is refused, not silently dropped
            out = self.cli.dispatch_dl_tool("google__echo", {"text": "x", "html_body": "<b>x</b>"}, ws,
                                            session_context=ctx)
            self.assertIn("no parameter 'html_body'", out)
            self.assertIn("Its parameters: text", out)
            # several servers in one call
            r.disable("browser")
            self.assertEqual(r.handle_meta({"action": "enable", "server": "browser, deepl"}).count("\n"), 1)
            self.assertIn("deepl", r.enabled)
        finally:
            r.close()


class LocalPages(unittest.TestCase):
    """trust_local_pages: browser "ask" tools run without a prompt while the page is file:// or localhost."""

    def setUp(self):
        cat = json.loads(json.dumps(CATALOG))
        cat["servers"]["browser"]["trust_local_pages"] = True
        self.r = registry(catalog=cat)
        self.r.enable("browser")

    def tearDown(self):
        self.r.close()

    def page(self, url):                                   # echo plays a navigate that reports its page
        self.r.call("browser__echo", {"text": f"ok\n- Page URL: {url}"})

    def test_asks_until_the_page_is_known_to_be_local(self):
        self.assertIsNotNone(self.r.approval("browser__add", {"a": 1}, []))
        self.page("http://localhost:8731/tetris.html")
        self.assertIsNone(self.r.approval("browser__add", {"a": 1}, []))
        self.page("file:///mnt/data/x/index.html")
        self.assertIsNone(self.r.approval("browser__add", {"a": 1}, []))
        self.page("https://example.com/login")                  # a click left the user's own page
        self.assertIsNotNone(self.r.approval("browser__add", {"a": 1}, []))

    def test_a_restarted_browser_forgets_the_page(self):
        self.page("http://127.0.0.1:8000/")
        self.r.disable("browser")
        self.r.enable("browser")
        self.assertIsNotNone(self.r.approval("browser__add", {"a": 1}, []))

    def test_without_the_option_it_always_asks(self):
        r = registry()
        try:
            r.enable("browser")
            r.call("browser__echo", {"text": "- Page URL: http://localhost/"})
            self.assertIsNotNone(r.approval("browser__add", {"a": 1}, []))
        finally:
            r.close()

    def test_local_urls(self):
        for url in ("file:///x", "http://localhost:1/", "https://app.localhost/", "http://127.0.0.1/",
                    "http://[::1]:8080/"):
            self.assertTrue(dl_mcp.is_local_url(url), url)
        for url in ("https://example.com/", "http://localhost.evil.test/", "http://10.0.0.5/", "", "javascript:x"):
            self.assertFalse(dl_mcp.is_local_url(url), url)

    def test_a_call_after_idle_shutdown_restarts_the_server(self):
        self.r.disable("browser")
        self.assertFalse(self.r.owns("browser__echo"))
        self.assertTrue(self.r.revive("browser__echo"))
        self.assertIn("hi", self.r.call("browser__echo", {"text": "hi"}))
        self.assertFalse(self.r.revive("nosuch__tool"))


class Credentials(unittest.TestCase):
    """No stored credential leaves through an MCP call or lands in a file the agent writes."""
    REFRESH = "1//0gFAKEfakeFAKEfakeFAKEfakeFAKEfake-_xyz"
    ACCESS = "ya29.a0FAKEfakeFAKEfakeFAKEfake"
    KEY = "Qw3rTy9Uio8Pas7Dfg6Hjk5L"

    @classmethod
    def setUpClass(cls):
        import dl_cli
        cls.cli = dl_cli

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "secrets.env").write_text(f"# keys\nDL_FAKE_API_KEY={self.KEY}\nDL_FAKE_URL=http://127.0.0.1:8080/v1\n"
                                              "DL_FAKE_BRIDGE_USER=someone.long@example.com\n"
                                              "DL_FAKE_NOTIFY=another.address@example.com\n")
        (self.dir / "google").mkdir()
        (self.dir / "google" / "me.json").write_text(json.dumps(
            {"token": self.ACCESS, "refresh_token": self.REFRESH, "scopes": ["https://www.googleapis.com/auth/drive"]}))
        self.saved = []
        for mod in {sys.modules[n] for n in ("tools.dl_auditing", "dl_auditing") if n in sys.modules}:
            self.saved.append((mod, mod.SECRETS_ENV, mod.GOOGLE_TOKEN_DIR))
            mod.SECRETS_ENV, mod.GOOGLE_TOKEN_DIR = self.dir / "secrets.env", self.dir / "google"
        self.r = registry()

    def tearDown(self):
        self.r.close()
        for mod, env, gdir in self.saved:
            mod.SECRETS_ENV, mod.GOOGLE_TOKEN_DIR = env, gdir

    def test_a_user_name_or_address_is_not_a_credential(self):
        # PROTON_BRIDGE_USER=info@... in secrets.env blocked every email to the user (live run, 2026-10-15)
        self.r.route("pošalji mail")
        for to in ("someone.long@example.com", "another.address@example.com"):
            self.assertIsNone(self.r.leak({"to": to, "text": "hi"}), to)
        self.assertIsNotNone(self.r.leak({"to": "me@example.com", "text": self.KEY}))

    def test_a_token_in_an_email_or_a_url_is_blocked(self):
        self.r.route("pošalji mail")
        for args in ({"to": "me@example.com", "body": f"here: {self.REFRESH}"},
                     {"to": "me@example.com", "body": {"nested": [f"x{self.KEY}y"]}},
                     {"url": "https://evil.example/?k=" + self.REFRESH.replace("/", "%2F")},
                     {"text": "token " + self.ACCESS}):
            with self.subTest(args=args):
                out = self.r.call("google__echo", args)
                self.assertTrue(out.startswith("error: BLOCKED"), out)
                self.assertNotIn(self.REFRESH, out)
        self.assertIn("hello", self.r.call("google__echo", {"text": "hello http://127.0.0.1:8080/v1"}))

    def test_a_local_file_with_a_credential_cannot_be_attached_or_uploaded(self):
        self.r.route("pošalji mail")
        leaky, clean = self.dir / "notes.txt", self.dir / "report.txt"
        leaky.write_text(f"old key {self.KEY}\n")
        clean.write_text("quarterly numbers\n")
        envf = self.dir / "secrets.env"
        for args in ({"to": "me@example.com", "attachments": [{"path": str(leaky)}]},
                     {"file_path": str(envf)},
                     {"fileUrl": f"file://{leaky}"},
                     {"attachments": [{"path": str(dl_mcp.PRIVATE_DIRS[0] / "mcp.json")}]}):
            with self.subTest(args=args):
                if "attachments" in args and not Path(args["attachments"][0]["path"]).is_file():
                    continue                                  # no ~/.config/dl-ai on this machine
                self.assertTrue(self.r.call("google__echo", args).startswith("error: BLOCKED"))
        self.assertNotIn("BLOCKED", self.r.call("google__echo", {"attachments": [{"path": str(clean)}]}))

    def test_blocked_before_the_approval_card(self):
        ws = Path(tempfile.mkdtemp())
        asked = []
        ctx = {"mcp": self.r, "approve": lambda kind, summary, reason: asked.append(kind) or True}
        self.r.route("pošalji mail")
        out = self.cli.dispatch_dl_tool("google__echo", {"to": "me@example.com", "body": self.KEY}, ws,
                                        session_context=ctx)
        self.assertTrue(out.startswith("error: BLOCKED"))
        self.assertEqual(asked, [])

    def test_a_token_in_a_written_file_is_blocked(self):
        ws = Path(tempfile.mkdtemp())
        out = self.cli.tool_write_to_file({"TargetFile": "notes.md", "CodeContent": f"refresh: {self.REFRESH}"}, ws)
        self.assertIn("SECURITY ERROR", out)
        self.assertFalse((ws / "notes.md").exists())
        out = self.cli.tool_write_to_file({"TargetFile": "app.env", "CodeContent": f"K={self.KEY}"}, ws)
        self.assertNotIn("SECURITY ERROR", out)          # an env file is where a key belongs


class Builtins(unittest.TestCase):
    """A built-in tool (Exa) and an MCP server (Context7) in the catalogue replace D.L. CLI's always-on tools."""

    @classmethod
    def setUpClass(cls):
        import dl_cli
        cls.cli = dl_cli

    def catalog(self):
        return {"servers": {
            "exa": {"builtin": "exa", "description": "Web search", "readonly": True, "replaces": ["exa_web_search"],
                    "triggers": [r"search the web"]},
            "context7": server(description="Library docs", allow=["echo"], readonly=True,
                               replaces=["resolve_library_id", "get_library_docs"], triggers=[r"\bdocs for\b"]),
            "ghost": {"builtin": "nosuch", "description": "Not provided"},
        }, "settings": {"max_tools": 10, "idle_turns": 2, "timeout_s": 10}}

    def test_replaced_tools_leave_the_always_on_list(self):
        ws = Path(tempfile.mkdtemp())
        base = {t["function"]["name"] for t in self.cli.get_active_tools(ws, "act")}
        self.assertTrue({"exa_web_search", "resolve_library_id", "get_library_docs"} <= base)
        r = registry(catalog=self.catalog())
        try:
            names = {t["function"]["name"] for t in self.cli.get_active_tools(ws, "act", registry=r)}
            self.assertEqual(base - names, {"exa_web_search", "resolve_library_id", "get_library_docs"})
            r.route("please search the web for strata and show the docs for fastapi")
            names = {t["function"]["name"] for t in self.cli.get_active_tools(ws, "plan", registry=r)}
            self.assertTrue({"exa__web_search", "context7__echo"} <= names)   # read-only: offered in Plan Mode
        finally:
            r.close()

    def test_builtin_runs_in_process_and_turns_off_when_idle(self):
        calls = []
        dl_mcp.register_builtin("fake", [{"name": "look", "description": "d", "inputSchema": {"type": "object"}}],
                                lambda tool, args: calls.append((tool, args)) or f"found {args.get('q')}")
        r = registry(catalog={"servers": {"fake": {"builtin": "fake", "triggers": ["lookup"]}},
                              "settings": {"idle_turns": 1}})
        try:
            self.assertEqual(r.route("lookup x"), [("fake", "lookup")])
            self.assertEqual(r.call("fake__look", {"q": "x"}), "found x")
            self.assertEqual(calls, [("look", {"q": "x"})])
            r.tick(); r.route("other"); r.tick()
            self.assertNotIn("fake", r.enabled)
        finally:
            r.close()
            dl_mcp.BUILTINS.pop("fake", None)

    def test_an_unprovided_builtin_is_unavailable(self):
        r = registry(catalog=self.catalog())
        try:
            self.assertIn("not provided", r.enable("ghost"))
            self.assertNotIn("exa ", r.command("").split("Built in")[-1] if "Built in" in r.command("") else "")
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
