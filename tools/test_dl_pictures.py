"""2026-11-15: Ray answered an attached photo only after running exiftool, magick, xdg-open and a web server he left
running.  The picture is now marked as shown, desktop openers and commands on the attached file are refused unless the
words ask, and what a detached command leaves listening is stopped at the end of the request."""
import os as _os
_os.environ.setdefault("RAY_MEMORY_DIR", "off")

import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import dl_cli as cli  # noqa: E402
import dl_effort  # noqa: E402
import dl_mcp  # noqa: E402


def boundary(cmd, words):
    return cli.agent_boundary("run_command", {"CommandLine": cmd}, Path("/tmp"), {"yolo": True, "user_text": words})


class PictureRefusals(unittest.TestCase):
    ASK = "@uploads/cat.jpg what breed is this?"

    def test_desktop_openers_need_words(self):
        for cmd in ("xdg-open uploads/x.png", "gio open a.png", "cd /x && eog a.png", "nohup gwenview a.png &",
                    "kde-open5 a.png", "feh a.png"):
            self.assertIn("window on the user's screen", boundary(cmd, "what is in this?") or "", cmd)
        self.assertIsNone(boundary("xdg-open report.html", "open report.html on my screen"))
        self.assertIsNone(boundary("xdg-open report.html", "otvori to na ekranu"))
        self.assertIsNone(boundary("grep feh notes.txt", "find feh in the notes"))   # not in command position

    def test_commands_on_the_attached_file(self):
        for cmd in ("exiftool uploads/cat.jpg", "magick identify cat.jpg", "python3 -c \"open('cat.jpg')\""):
            self.assertIn("already shown to you", boundary(cmd, self.ASK) or "", cmd)
        self.assertIsNone(boundary("ls uploads", self.ASK))
        self.assertIsNone(boundary("magick cat.jpg -resize 50% small.jpg", "@uploads/cat.jpg resize this to half"))
        self.assertIsNone(boundary("exiftool cat.jpg", "@uploads/cat.jpg what does the EXIF say?"))
        # the path's own words do not count as asking
        self.assertIn("already shown", boundary("magick crop.jpg info:", "@uploads/crop.jpg what is this?") or "")

    def test_typed_commands_pass(self):
        self.assertIsNone(cli.agent_boundary("run_command", {"CommandLine": "xdg-open a.png"}, Path("/tmp"), {}))

    def test_marker_and_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "cat.jpg").write_bytes(b"\xff\xd8\xff\xe0JFIF")
            content = cli.build_user_message_content("@cat.jpg", ws)
        self.assertIn("[Attached image, shown to you below: cat.jpg]", content[0]["text"])
        self.assertIn("Describe this media", content[0]["text"])
        self.assertEqual(dl_effort.pick("[Attached image, shown to you below: a.png]", router_mode="rules"),
                         ("low", "picture only"))
        self.assertTrue(dl_mcp.HAS_ATTACHMENT.search("[Attached image, shown to you below: a.png] hi"))
        self.assertIn("already visible to you", cli.build_dl_system_prompt(Path("/tmp")))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def listening(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class LeftServers(unittest.TestCase):
    def run_server(self, words):
        port = free_port()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = {"yolo": True, "user_text": words, "bg_listeners": []}
        cmd = f"nohup {sys.executable} -m http.server {port} --bind 127.0.0.1 >/dev/null 2>&1 &"
        out = cli.dispatch_dl_tool("run_command", {"CommandLine": cmd}, Path(tmp.name), session_context=ctx)
        self.assertIn("exited with code 0", out)
        for _ in range(20):
            if listening(port):
                break
            time.sleep(0.1)
        self.assertTrue(listening(port))
        self.addCleanup(lambda: [subprocess.run(["kill", str(p)]) for p, *_ in list(ctx.get("_left", []))])
        ctx["_left"] = list(ctx["bg_listeners"])
        return ctx, port

    def test_a_server_left_running_is_stopped(self):
        ctx, port = self.run_server("what is in this picture?")
        self.assertEqual([p for _, p, _, _ in ctx["bg_listeners"]], [port])
        notes = []
        cli.stop_left_listeners(ctx, notes.append)
        self.assertEqual(len(notes), 1)
        self.assertIn(f"port {port}", notes[0]["text"])
        time.sleep(0.2)
        self.assertFalse(listening(port))

    def test_kept_when_the_words_ask(self):
        ctx, port = self.run_server("start a dev server for the game")
        self.assertEqual(cli.stop_left_listeners(ctx, lambda e: None), [])
        self.assertTrue(listening(port))

    def test_foreground_commands_are_not_watched(self):
        ctx = {"yolo": True, "user_text": "x", "bg_listeners": []}
        cli.dispatch_dl_tool("run_command", {"CommandLine": "echo a && echo b 2>&1"}, Path("/tmp"), session_context=ctx)
        self.assertEqual(ctx["bg_listeners"], [])


class Triggers(unittest.TestCase):
    def test_a_short_word_starts_a_word(self):
        e = dl_mcp.Entry("networking", {"command": "x", "triggers": ["lan", "\\bvlan\\b"]})
        self.assertFalse(any(t.search("make a plan") for t in e.triggers))
        self.assertTrue(any(t.search("my LAN is slow") for t in e.triggers))
        self.assertTrue(any(t.search("two lans") for t in e.triggers))


if __name__ == "__main__":
    unittest.main()
