"""Two small MCP servers: Europe PMC wrote every answer to one fixed /tmp/epmc_out.json (calls raced, and another
local user could plant the file); Modern Web Guidance ran `npx -y modern-web-guidance@latest` (whatever npm
published next, unreviewed, on every call).

    python -m unittest tools.test_small_mcp_servers   (from the repo root, with tools/ on PYTHONPATH)
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import europepmc_mcp  # noqa: E402
import modernweb_mcp  # noqa: E402


class SmallMcpServers(unittest.TestCase):
    def test_europepmc_uses_a_private_file_per_call_and_cleans_up(self):
        seen = []

        def fake_run(cmd, **k):
            out = cmd[cmd.index("--output") + 1]
            seen.append(out)
            Path(out).write_text('{"ok": 1}', encoding="utf-8")
            return mock.Mock(stderr="")
        with mock.patch.object(europepmc_mcp.subprocess, "run", fake_run):
            self.assertEqual(europepmc_mcp.run_cmd("search", "a"), '{"ok": 1}')
            self.assertEqual(europepmc_mcp.run_cmd("search", "b"), '{"ok": 1}')
        self.assertNotEqual(seen[0], seen[1])
        self.assertNotIn("/tmp/epmc_out.json", seen)
        for s in seen:
            self.assertFalse(os.path.exists(os.path.dirname(s)))

    def test_modern_web_guidance_is_pinned(self):
        self.assertRegex(modernweb_mcp.MWG_PACKAGE, r"^modern-web-guidance@\d+\.\d+\.\d+$")
        src = (Path(__file__).resolve().parent / "modernweb_mcp.py").read_text(encoding="utf-8")
        self.assertNotIn("modern-web-guidance@latest\"", src)


if __name__ == "__main__":
    unittest.main()
