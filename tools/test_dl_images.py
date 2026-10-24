#!/usr/bin/env python3
"""Unit tests for multimodal image handling in D.L. CLI & Session Daemon."""
import sys
import unittest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import dl_cli as cli


class TestImageHandling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

        # Create sample files
        self.txt_file = self.ws / "hello.py"
        self.txt_file.write_text("print('hello world')", encoding="utf-8")

        self.jpg_file = self.ws / "photo.jpg"
        # Write minimal valid JPEG header bytes
        self.jpg_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb")

        self.png_file = self.ws / "diagram.png"
        self.png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_file_inlining_remains_unchanged(self):
        prompt = f"Check @hello.py"
        resolved = cli.resolve_file_references(prompt, self.ws)
        self.assertIn("```file:hello.py", resolved)
        self.assertIn("print('hello world')", resolved)

        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, str)
        self.assertIn("print('hello world')", content)

    def test_image_reference_does_not_dump_binary(self):
        prompt = f"Describe @photo.jpg please"
        resolved = cli.resolve_file_references(prompt, self.ws)
        self.assertNotIn("JFIF", resolved)
        self.assertIn("[Image: photo.jpg]", resolved)

    def test_build_user_message_content_multimodal_parts(self):
        prompt = f"Look at @photo.jpg and tell me what you see"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("Look at [Image: photo.jpg]", content[0]["text"])
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], f"file://{self.jpg_file.resolve()}")

    def test_bare_image_gets_default_instruction(self):
        prompt = f"@diagram.png"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        self.assertIn("Describe this image and identify its key elements", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], f"file://{self.png_file.resolve()}")

    def test_mixed_text_and_image(self):
        prompt = f"Compare @hello.py with @diagram.png"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        # text part has the inlined code block and image placeholder
        self.assertIn("print('hello world')", content[0]["text"])
        self.assertIn("[Image: diagram.png]", content[0]["text"])
        # image part has diagram.png
        self.assertEqual(content[1]["image_url"]["url"], f"file://{self.png_file.resolve()}")

    def test_format_messages_to_markdown_with_multimodal(self):
        msgs = [
            {"role": "system", "content": "system prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "[Now: 2026-10-24 04:30]\n[Image: photo.jpg] What is this?"},
                    {"type": "image_url", "image_url": {"url": "file:///path/photo.jpg"}}
                ]
            },
            {"role": "assistant", "content": "This is a photo."}
        ]
        md = cli.format_messages_to_markdown(msgs, workspace=self.ws)
        self.assertIn("## You", md)
        self.assertIn("[Image: photo.jpg]", md)
        self.assertIn("This is a photo.", md)

    def test_latest_task_and_is_cli_note(self):
        user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "[Now: 2026-10-24]\nInspect this image"},
                {"type": "image_url", "image_url": {"url": "file:///test.jpg"}}
            ]
        }
        self.assertFalse(cli.is_cli_note(user_msg))
        task = cli._latest_task([user_msg])
        self.assertEqual(task, "Inspect this image")


if __name__ == "__main__":
    unittest.main()
