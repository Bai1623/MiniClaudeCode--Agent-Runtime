import unittest
from parser import parse_records


class TestParser(unittest.TestCase):
    def test_parses_valid_records(self):
        self.assertEqual(parse_records(["alpha|2", "beta|3"]), [("alpha", 2), ("beta", 3)])

    def test_skips_bad_records_and_continues(self):
        lines = ["alpha|2", "", "missing-count", "beta|oops", "gamma|4"]
        self.assertEqual(parse_records(lines), [("alpha", 2), ("gamma", 4)])


if __name__ == "__main__":
    unittest.main()
