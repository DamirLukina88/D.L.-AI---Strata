"""#3796: a declared `mcp__server__tool` written with every `__` collapsed to `_` is that tool.

    python -m unittest serve.test_tool_name_alias -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serve.frontend import OutputParser  # noqa: E402

# Local port of upstream 0.2.7 (#3796): only the collapsed `mcp__a__b` -> `mcp_a_b` spelling.  Upstream's tests that an
# undeclared name stays text when tools are declared are left out: this tree keeps such a call a call (see
# OutputParser._callable), and upstream's DriftedMcpNames aliases were never ported here.


def text_of(evs):
    return "".join(e.text or "" for e in evs if e.kind in ("content", "reasoning"))


def plain_tool(name):
    return {"name": name, "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}


def call_text(name, param="url", value="https://example.com"):
    return f"<tool_call>\n<function={name}>\n<parameter={param}>\n{value}\n</parameter>\n</function>\n</tool_call>"


def run_parser(text, tools, width=0):
    parser = OutputParser(thinking=False, tools=tools, stream_tools=True, declared_only=True)
    evs = []
    step = width or len(text) or 1
    for k in range(0, len(text), step):
        evs += parser.feed(text[k:k + step])
    evs += parser.finish("stop")
    return evs, parser


class CollapsedUnderscoreNames(unittest.TestCase):
    """#3796: `mcp__server__tool` written as `mcp_server_tool` is a spelling of the declared tool (the same class of
    difference as namespace__member). A name that is only similar stays text, and is named for the client."""
    MCP = [plain_tool("mcp__playwright__browser_navigate"), plain_tool("mcp__playwright__browser_snapshot"),
           plain_tool("mcp__playwright__browser_tabs"), plain_tool("todo_write")]

    def test_the_collapsed_spelling_is_the_declared_tool(self):
        for name in ("browser_navigate", "browser_snapshot", "browser_tabs"):
            for width in (0, 1, 5):
                with self.subTest(name=name, width=width):
                    evs, parser = run_parser("Opening it.\n" + call_text("mcp_playwright_" + name), self.MCP, width)
                    found = [e.call for e in evs if e.kind == "tool_call"]
                    self.assertEqual([c.name for c in found], ["mcp__playwright__" + name])   # the client gets the name it declared
                    self.assertEqual(found[0].arguments, {"url": "https://example.com"})
                    self.assertEqual(text_of(evs).strip(), "Opening it.")
                    self.assertEqual((parser.unread, parser.unread_names), (0, []))

    def test_the_declared_spelling_and_a_plain_tool_are_unchanged(self):
        evs, _ = run_parser(call_text("mcp__playwright__browser_tabs") + "\n" + call_text("todo_write"), self.MCP)
        self.assertEqual([e.call.name for e in evs if e.kind == "tool_call"], ["mcp__playwright__browser_tabs", "todo_write"])

    def test_a_tool_declared_in_the_collapsed_spelling_wins(self):
        tools = self.MCP + [plain_tool("mcp_playwright_browser_tabs")]
        evs, _ = run_parser(call_text("mcp_playwright_browser_tabs"), tools)
        self.assertEqual([e.call.name for e in evs if e.kind == "tool_call"], ["mcp_playwright_browser_tabs"])


if __name__ == "__main__":
    unittest.main()
