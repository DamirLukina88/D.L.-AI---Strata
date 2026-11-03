"""pc_music_mcp: songs, the Liked songs and links open in Ray's Brave profile; pause/next/previous go to its player;
and every prompt says where it was typed (phone, PC, another computer), so music plays there.  No Brave, no network.

Run from the repo root: python tools/test_pc_music.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli  # noqa: E402
import pc_music_mcp as pc  # noqa: E402

SONG = {"video_id": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artist": "Queen"}


class PlayOnThePc(unittest.TestCase):
    def play(self, args):
        with mock.patch.object(pc, "find_song", return_value=SONG), \
                mock.patch.object(pc, "open_one_tab", return_value=None) as tab, \
                mock.patch.object(pc, "make_it_play", return_value=True):
            return pc.play_music(args), tab

    def test_a_song(self):
        res, tab = self.play({"query": "bohemian rhapsody"})
        tab.assert_called_once_with("https://music.youtube.com/watch?v=BSTsnWoslP4")
        self.assertTrue(res.startswith("Playing 'Bohemian Rhapsody' by Queen on the PC."))

    def test_no_query_plays_the_liked_songs(self):
        res, tab = self.play({})
        tab.assert_called_once_with(pc.LIKED_PAGE)

    def test_only_youtube_links(self):
        res, tab = self.play({"url": "https://evil.example/x"})
        tab.assert_not_called()
        self.assertTrue(res.startswith("Error"))

    def test_the_answer_is_short(self):
        self.assertTrue(self.play({"query": "x"})[0].endswith(pc.SHORT_ANSWER))


class Controls(unittest.TestCase):
    def test_actions_go_to_the_player(self):
        with mock.patch.object(pc, "target_player", return_value="org.mpris.MediaPlayer2.brave.instance7"), \
                mock.patch.object(pc, "_gdbus", return_value="()") as bus:
            self.assertTrue(pc.control_media({"action": "next"}).startswith("Skipped"))
        self.assertIn("org.mpris.MediaPlayer2.Player.Next", bus.call_args[0][0])

    def test_nothing_to_control(self):
        with mock.patch.object(pc, "target_player", return_value=None):
            self.assertIn("pc_play_music", pc.control_media({"action": "play"}))

    def test_a_notification_gets_no_answer(self):
        self.assertIsNone(pc.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = {t["name"] for t in pc.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(names, {"pc_play_music", "pc_control_media", "pc_get_now_playing"})


class WhereThePromptCameFrom(unittest.TestCase):
    def test_the_ray_app_is_the_phone(self):
        self.assertEqual(dl_cli.device_of("ray-android"), "phone")
        self.assertEqual(dl_cli.device_of("ray-android-app-abc"), "phone")
        self.assertEqual(dl_cli.device_of("web-123"), "pc")

    def test_the_now_line_says_it(self):
        self.assertIn("sent from: the phone", dl_cli.now_line("phone"))
        self.assertIn("sent from: the PC", dl_cli.now_line("pc"))
        self.assertIn("ask: the phone or the PC?", dl_cli.now_line("remote"))
        self.assertNotIn("sent from", dl_cli.now_line())
        self.assertRegex(dl_cli.with_now("hi", "phone"), dl_cli.NOW_PREFIX)


if __name__ == "__main__":
    unittest.main()
