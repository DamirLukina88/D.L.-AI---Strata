"""The phone tools Ray is told about (tools/phone_mcp.py) and the ones the Android app runs (PhoneTools.kt) must be
the same: the same names, and every argument the app reads must be in the tool's schema (a renamed argument would be
silently ignored on the phone, which uses its default).

Run from the repo root: python tools/test_phone_tool_parity.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from phone_mcp import TOOLS_DEFINITIONS  # noqa: E402

KOTLIN = ROOT / "android/app/src/main/kotlin/com/damirl/ray/tools/PhoneTools.kt"


def app_tools():
    """{tool name: {argument: default as written in Kotlin}} from PhoneTools.execute's `when`."""
    src = KOTLIN.read_text(encoding="utf-8")
    body = src[src.index("fun execute("):src.index("else ->")]
    tools = {}
    # each branch starts with "phone_x" -> and runs to the next branch
    parts = re.split(r'\n\s*"(phone_[a-z0-9_]+)"\s*->', "\n" + body)
    for name, code in zip(parts[1::2], parts[2::2]):
        tools[name] = dict(re.findall(r'args\.opt\w+\("([a-z_]+)",\s*([^)]+)\)', code))
    return tools


class PhoneToolParity(unittest.TestCase):
    def test_same_tool_names(self):
        self.assertEqual(sorted(app_tools()), sorted(t["name"] for t in TOOLS_DEFINITIONS))

    def test_every_argument_the_app_reads_is_in_the_schema(self):
        schemas = {t["name"]: t["inputSchema"].get("properties", {}) for t in TOOLS_DEFINITIONS}
        for name, args in app_tools().items():
            for arg in args:
                self.assertIn(arg, schemas[name], f"{name}: the app reads '{arg}', which the schema doesn't have")

    def test_required_arguments_are_read_by_the_app(self):
        tools = app_tools()
        for t in TOOLS_DEFINITIONS:
            for arg in t["inputSchema"].get("required", []):
                self.assertIn(arg, tools[t["name"]], f"{t['name']}: required '{arg}' is never read on the phone")

    def test_schema_defaults_match_the_app(self):
        tools = app_tools()
        for t in TOOLS_DEFINITIONS:
            for arg, spec in t["inputSchema"].get("properties", {}).items():
                if "default" in spec and arg in tools[t["name"]]:
                    self.assertEqual(str(spec["default"]), tools[t["name"]][arg].strip('"'), f"{t['name']}.{arg}")


if __name__ == "__main__":
    unittest.main()
