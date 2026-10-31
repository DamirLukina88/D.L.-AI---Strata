import unittest

from money import split


class SplitTest(unittest.TestCase):
    def test_even(self):
        self.assertEqual(split(100, 4), [25, 25, 25, 25])

    def test_remainder_goes_first(self):
        self.assertEqual(split(10, 3), [4, 3, 3])

    def test_parts_add_up(self):
        for total in range(0, 500, 7):
            for n in range(1, 9):
                self.assertEqual(sum(split(total, n)), total)

    def test_three_way(self):
        self.assertEqual(split(100, 3), [33, 33, 33])

    def test_bad_n(self):
        with self.assertRaises(ValueError):
            split(100, 0)


if __name__ == "__main__":
    unittest.main()
