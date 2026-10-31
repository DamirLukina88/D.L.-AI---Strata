import unittest
from datetime import datetime

from schedule import next_run


class NextRunTest(unittest.TestCase):
    def test_every_minute(self):
        self.assertEqual(next_run("* * * * *", datetime(2026, 3, 1, 10, 0, 30)), datetime(2026, 3, 1, 10, 1))

    def test_fixed_time_tomorrow(self):
        self.assertEqual(next_run("30 6 * * *", datetime(2026, 3, 1, 7, 0)), datetime(2026, 3, 2, 6, 30))

    def test_step(self):
        self.assertEqual(next_run("*/15 * * * *", datetime(2026, 3, 1, 10, 16)), datetime(2026, 3, 1, 10, 30))

    def test_list_and_range(self):
        self.assertEqual(next_run("0 9-17/4 * * *", datetime(2026, 3, 1, 13, 5)), datetime(2026, 3, 1, 17, 0))

    def test_weekday(self):   # 2026-03-01 is a Sunday
        self.assertEqual(next_run("0 8 * * 1-5", datetime(2026, 3, 1, 9, 0)), datetime(2026, 3, 2, 8, 0))

    def test_day_of_month_or_weekday(self):
        self.assertEqual(next_run("0 0 13 * 5", datetime(2026, 3, 1, 0, 0)), datetime(2026, 3, 6, 0, 0))

    def test_leap_day(self):
        self.assertEqual(next_run("0 12 29 2 *", datetime(2026, 3, 1)), datetime(2028, 2, 29, 12, 0))

    def test_bad_expression(self):
        for bad in ("* * * *", "60 * * * *", "a * * * *", "*/0 * * * *"):
            with self.assertRaises(ValueError):
                next_run(bad, datetime(2026, 3, 1))


if __name__ == "__main__":
    unittest.main()
