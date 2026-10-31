import unittest

import textkit as t


class TextkitTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(t.slugify("  Hello, World! "), "hello-world")

    def test_is_anagram(self):
        self.assertTrue(t.is_anagram("Dormitory", "dirty room!"))

    def test_caesar(self):
        self.assertEqual(t.caesar("Zebra-1", 3), "Cheud-1")

    def test_rle_encode(self):
        self.assertEqual(t.rle_encode("aaab"), "3a1b")

    def test_rle_decode(self):
        self.assertEqual(t.rle_decode("3a1b"), "aaab")

    def test_word_freq(self):
        self.assertEqual(t.word_freq("It's it, IT"), {"it's": 1, "it": 2})

    def test_truncate(self):
        self.assertEqual(t.truncate("abcdef", 4), "abc…")

    def test_camel_to_snake(self):
        self.assertEqual(t.camel_to_snake("userId"), "user_id")

    def test_snake_to_camel(self):
        self.assertEqual(t.snake_to_camel("user_id"), "userId")

    def test_common_prefix(self):
        self.assertEqual(t.common_prefix(["flower", "flow", "flight"]), "fl")


if __name__ == "__main__":
    unittest.main()
