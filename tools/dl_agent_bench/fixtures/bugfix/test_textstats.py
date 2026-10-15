import unittest

from textstats import top_words, word_count


class TextStatsTest(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(word_count("the quick brown fox"), 4)

    def test_top_words(self):
        self.assertEqual(top_words("b a b, B. c a", 2), ["b", "a"])


if __name__ == "__main__":
    unittest.main()
