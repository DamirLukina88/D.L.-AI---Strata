"""tools/test_dl_session_tools.py - Unit tests for session management tools and conversational continue.

Tests:
1. save_chat tool: default and custom filename export.
2. get_system_health tool: returns clean hardware health card.
3. get_engine_status tool: returns engine status.
4. clear_conversation tool: resets session messages and state.
5. Conversational continue: 'continue', 'keep going', 'go on', 'proceed' in dl_sessiond and dl_cli.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli
import dl_sessiond as sessiond


class TestSessionTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_chat_default_and_custom(self):
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "Hello agent"},
            {"role": "assistant", "content": "Hello user! How can I help?"},
        ]
        ctx = {"messages": messages, "workspace": self.ws}

        # 1. Custom filename
        out = cli.dispatch_dl_tool("save_chat", {"filename": "my_notes.md"}, self.ws, session_context=ctx)
        self.assertIn("Chat successfully saved as Markdown", out)
        target = self.ws / "my_notes.md"
        self.assertTrue(target.is_file())
        content = target.read_text(encoding="utf-8")
        self.assertIn("Hello agent", content)
        self.assertIn("Hello user!", content)

        # 2. Default filename
        out2 = cli.dispatch_dl_tool("save_chat", {}, self.ws, session_context=ctx)
        self.assertIn("Chat successfully saved as Markdown", out2)
        saved_files = list(self.ws.glob("dl-ai-code-chat-*.md"))
        self.assertEqual(len(saved_files), 1)

    def test_get_system_health(self):
        out = cli.dispatch_dl_tool("get_system_health", {}, self.ws)
        self.assertIsInstance(out, str)
        self.assertTrue(len(out) > 0)
        # Verify ANSI codes were stripped
        self.assertNotIn("\033[", out)

    def test_get_engine_status(self):
        out = cli.dispatch_dl_tool("get_engine_status", {}, self.ws)
        self.assertIsInstance(out, str)
        self.assertTrue(len(out) > 0)
        self.assertNotIn("\033[", out)

    def test_clear_conversation_cli_context(self):
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "Hello agent"},
            {"role": "assistant", "content": "Hello user"},
        ]
        ctx = {"messages": messages, "mode": "act"}
        out = cli.dispatch_dl_tool("clear_conversation", {}, self.ws, session_context=ctx)
        self.assertIn("reset", out.lower())
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")

    def test_clear_conversation_sessiond_context(self):
        sess = sessiond.Session("test-clear", self.ws)
        sess.messages.append({"role": "user", "content": "hi"})
        sess.messages.append({"role": "assistant", "content": "hello"})
        sess.events.append({"type": "text", "text": "hello"})

        ctx = {"session": sess, "messages": sess.messages}
        out = cli.dispatch_dl_tool("clear_conversation", {}, self.ws, session_context=ctx)
        self.assertIn("reset", out.lower())
        self.assertEqual(len(sess.messages), 1)
        self.assertEqual(sess.messages[0]["role"], "system")
        # Previous conversation text events are gone, only new control events remain
        event_types = [e.get("type") for e in sess.events]
        self.assertIn("cleared", event_types)
        self.assertNotIn("text", event_types)

    def test_conversational_continue_sessiond(self):
        sess = sessiond.Session("test-continue", self.ws)
        for phrase in ("/continue", "continue", "keep going", "go on", "proceed", "  CONTINUE  "):
            res = sess._command(phrase)
            self.assertEqual(res, cli.CONTINUE_PROMPT)

        # Non-continue phrases pass through
        self.assertEqual(sess._command("hello there"), "hello there")


if __name__ == "__main__":
    unittest.main()
