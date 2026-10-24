#!/usr/bin/env python3
"""Unit tests for multimodal image, video, PDF, audio and binary handling in D.L. CLI & Session Daemon."""
import sys
import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import dl_cli as cli


class TestMultimodalMediaHandling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

        # Create sample files
        self.txt_file = self.ws / "hello.py"
        self.txt_file.write_text("print('hello world')", encoding="utf-8")

        self.jpg_file = self.ws / "photo.jpg"
        self.jpg_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb")

        self.png_file = self.ws / "diagram.png"
        self.png_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        self.bin_file = self.ws / "weights.gguf"
        self.bin_file.write_bytes(b"GGUF\x03\x00\x00\x00\x00\x00\x00\x00")

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
        self.assertIn("Describe this media and identify its key elements", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], f"file://{self.png_file.resolve()}")

    def test_mixed_text_and_image(self):
        prompt = f"Compare @hello.py with @diagram.png"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)
        self.assertIn("print('hello world')", content[0]["text"])
        self.assertIn("[Image: diagram.png]", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], f"file://{self.png_file.resolve()}")

    def test_binary_file_guard(self):
        prompt = f"Check model @weights.gguf"
        resolved = cli.resolve_file_references(prompt, self.ws)
        self.assertNotIn("GGUF", resolved)
        self.assertIn("[Binary file: weights.gguf", resolved)

    @patch("dl_cli._sample_video_frames")
    def test_video_file_sampling(self, mock_sample):
        vid_p = self.ws / "clip.mp4"
        vid_p.write_bytes(b"ftypmp42")
        frame1 = self.ws / "f1.jpg"
        frame2 = self.ws / "f2.jpg"
        frame1.write_bytes(b"\xff\xd8\xff")
        frame2.write_bytes(b"\xff\xd8\xff")
        mock_sample.return_value = [(1.5, frame1), (3.0, frame2)]

        prompt = f"What is in @clip.mp4?"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 3)  # text + 2 frames
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("[Video: clip.mp4 (2 frames @ 1.5s, 3.0s)]", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], f"file://{frame1.resolve()}")
        self.assertEqual(content[2]["image_url"]["url"], f"file://{frame2.resolve()}")

    @patch("dl_cli._render_pdf_pages")
    def test_pdf_page_rendering(self, mock_pdf):
        pdf_p = self.ws / "doc.pdf"
        pdf_p.write_bytes(b"%PDF-1.5")
        page1 = self.ws / "page-1.png"
        page1.write_bytes(b"\x89PNG")
        mock_pdf.return_value = [page1]

        prompt = f"Read @doc.pdf"
        content = cli.build_user_message_content(prompt, self.ws)
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 2)  # text + 1 page
        self.assertIn("[PDF: doc.pdf (1 page rendered)]", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], f"file://{page1.resolve()}")

    @patch("dl_cli._transcribe_audio_file")
    def test_audio_file_transcription(self, mock_transcribe):
        aud_p = self.ws / "voice.wav"
        aud_p.write_bytes(b"RIFF....WAVE")
        mock_transcribe.return_value = "Hello from the voice memo"

        prompt = f"Listen to @voice.wav"
        resolved = cli.resolve_file_references(prompt, self.ws)
        self.assertIn("[Audio: voice.wav (Whisper transcription)]", resolved)
        self.assertIn("Hello from the voice memo", resolved)

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
