"""A tool can hand the model a picture with [[image: <path>]] in its result (the phone's phone_get_last_photo).  Only
the allowed tools may, and only image files inside the workspace count.

Run from the repo root: python -m unittest tools.test_dl_tool_images
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli  # noqa: E402


class ToolResultImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ws"
        self.project = self.root / "project_2"
        (self.root / "phone-photos").mkdir(parents=True)
        self.project.mkdir()
        self.photo = self.root / "phone-photos" / "RAY_SNAP_1.jpg"
        self.photo.write_bytes(b"\xff\xd8\xff fake jpeg")
        (self.root / "notes.txt").write_text("not an image")
        self.outside = Path(self.tmp.name) / "secret.jpg"
        self.outside.write_bytes(b"\xff\xd8\xff")
        self.env = mock.patch.dict(os.environ, {"STRATA_WORKSPACE_DIR": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_the_phone_photo_from_the_workspace_root(self):
        res = "The photo is in the workspace as phone-photos/RAY_SNAP_1.jpg. [[image: phone-photos/RAY_SNAP_1.jpg]]"
        self.assertEqual(dl_cli.tool_result_images("phone__phone_get_last_photo", res, self.project),
                         [f"file://{self.photo.resolve()}"])

    def test_other_tools_cannot_show_images(self):
        res = "[[image: phone-photos/RAY_SNAP_1.jpg]]"
        for name in ("fetch__fetch", "view_file", "phone__phone_get_screen"):
            self.assertEqual(dl_cli.tool_result_images(name, res, self.project), [], name)

    def test_only_image_files_inside_the_workspace(self):
        for marker in ("../secret.jpg", str(self.outside), "notes.txt", "phone-photos/missing.jpg"):
            with self.subTest(marker=marker):
                self.assertEqual(dl_cli.tool_result_images("phone__phone_get_last_photo",
                                                           f"[[image: {marker}]]", self.project), [])

    def test_the_image_reaches_the_model_as_a_cli_note(self):
        # the message added after the round is a CLI note (not the user's words: the finish checks look for those)
        msg = {"role": "user", "content": [{"type": "text", "text": "[D.L. CLI: the image the tool returned above.]"}]}
        self.assertTrue(dl_cli.is_cli_note(msg))


if __name__ == "__main__":
    unittest.main()
