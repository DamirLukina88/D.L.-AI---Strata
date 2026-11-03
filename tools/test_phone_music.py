"""phone_play_music: the song YouTube Music finds becomes a watch link for the phone; no query plays the Liked songs;
only YouTube links are passed on.  No network: the search answer is a fixture.

Run from the repo root: python tools/test_phone_music.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phone_mcp  # noqa: E402


def row(vid, title, second):
    return {"musicResponsiveListItemRenderer": {
        "playlistItemData": {"videoId": vid},
        "flexColumns": [
            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": title}]}}},
            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": second}]}}},
        ]}}


SEARCH = {"contents": {"tabbedSearchResultsRenderer": {"tabs": [{"tabRenderer": {"content": {"sectionListRenderer": {
    "contents": [{"musicShelfRenderer": {"contents": [
        row("BSTsnWoslP4", "Bohemian Rhapsody", "Queen • A Night At The Opera • 5:55"),
        row("other", "Bohemian Rhapsody", "Someone else • 5:57"),
    ]}}]}}}}]}}}


class PlayMusic(unittest.TestCase):
    def setUp(self):
        self.server = phone_mcp.PhoneMcpServer()

    def test_the_first_song_of_the_search(self):
        self.assertEqual(phone_mcp.first_song(SEARCH),
                         {"video_id": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artist": "Queen"})
        self.assertIsNone(phone_mcp.first_song({"contents": {}}))

    def test_a_query_becomes_a_watch_link(self):
        with mock.patch.object(phone_mcp, "find_song", return_value=phone_mcp.first_song(SEARCH)):
            args, found = self.server._resolve_song({"query": "bohemian rhapsody"})
        self.assertEqual(args["url"], "https://music.youtube.com/watch?v=BSTsnWoslP4")
        self.assertIn("Queen", found)

    def test_the_answer_is_short(self):
        with mock.patch.object(phone_mcp, "find_song", return_value=phone_mcp.first_song(SEARCH)), \
                mock.patch.object(self.server, "_execute_on_phone", return_value="Started."):
            res = self.server.execute_tool("phone_play_music", {"query": "bohemian rhapsody"})
        self.assertEqual(res, "Playing 'Bohemian Rhapsody' by Queen. " + phone_mcp.SHORT_ANSWER)

    def test_no_query_plays_the_liked_songs(self):
        with mock.patch.object(phone_mcp, "find_song") as search:
            args, found = self.server._resolve_song({})
        search.assert_not_called()
        self.assertEqual(args["url"], phone_mcp.LIKED_SONGS)

    def test_only_youtube_links(self):
        self.assertEqual(self.server._resolve_song({"url": "https://youtu.be/abc"})[0]["url"], "https://youtu.be/abc")
        args, found = self.server._resolve_song({"url": "https://evil.example/youtube.com/"})
        self.assertEqual(args, {})
        self.assertTrue(found.startswith("Error"))

    def test_nothing_found_never_reaches_the_phone(self):
        with mock.patch.object(phone_mcp, "find_song", return_value=None), \
                mock.patch.object(self.server, "_execute_on_phone") as phone:
            res = self.server.execute_tool("phone_play_music", {"query": "zzzz"})
        phone.assert_not_called()
        self.assertTrue(res.startswith("Error"))


if __name__ == "__main__":
    unittest.main()
