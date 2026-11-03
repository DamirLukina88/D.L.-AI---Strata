"""#4751 (upstream 35057071): `tools.write`, `functions.write` or `default_api.write` for a declared `write`."""
import unittest

from serve.frontend import OutputParser


class PrefixedNames(unittest.TestCase):
    """A programmatic-tool-calling harness shows the model `tools.write(...)`, and it then writes the native call that way."""

    WRITE = {"name": "write", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}}}
    TEXT = ("<tool_call>\n<function=tools.write>\n<parameter=file_path>/a/b.py</parameter>\n"
            "<parameter=content>x = 1\n</parameter>\n</function>\n</tool_call>")

    def calls(self, tools, text=None):
        p = OutputParser(thinking=False, tools=tools, stream_tools=True, recover=True, declared_only=True)
        evs = p.feed(text or self.TEXT) + p.finish("stop")
        return [e.call for e in evs if e.kind == "tool_call"], "".join(e.text for e in evs if e.kind == "content")

    def test_the_prefix_is_read_as_the_declared_tool(self):
        calls, answer = self.calls([self.WRITE])
        self.assertEqual([(c.name, c.arguments["file_path"]) for c in calls], [("write", "/a/b.py")])
        self.assertEqual(answer, "")

    def test_functions_and_default_api_prefixes_too(self):
        for prefix in ("functions.", "default_api."):
            calls, _ = self.calls([self.WRITE], self.TEXT.replace("tools.", prefix))
            self.assertEqual([c.name for c in calls], ["write"], prefix)

    def test_a_declared_dotted_name_wins(self):
        dotted = {"name": "tools.write", "parameters": self.WRITE["parameters"]}
        calls, _ = self.calls([self.WRITE, dotted])
        self.assertEqual([c.name for c in calls], ["tools.write"])

    def test_a_prefixed_undeclared_name_follows_the_local_rule(self):
        # upstream keeps `tools.delete` as text; this fork keeps a well-formed call of an undeclared name a call (0.2.7 port),
        # so the prefix only has to leave the name as written, not turn it into `write`
        calls, _ = self.calls([self.WRITE], self.TEXT.replace("tools.write", "tools.delete"))
        self.assertNotIn("write", [c.name for c in calls])


if __name__ == "__main__":
    unittest.main()
