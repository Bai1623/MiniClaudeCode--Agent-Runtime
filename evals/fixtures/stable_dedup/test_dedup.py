import unittest

from dedup import deduplicate


class TestDeduplicate(unittest.TestCase):
    def test_supports_dictionary_records(self):
        records = [{"id": 1}, {"id": 1}, {"id": 2}]
        self.assertEqual(deduplicate(records), [{"id": 1}, {"id": 2}])

    def test_preserves_first_seen_order_and_input(self):
        source = ["beta", "alpha", "beta", "gamma"]
        self.assertEqual(deduplicate(source), ["beta", "alpha", "gamma"])
        self.assertEqual(source, ["beta", "alpha", "beta", "gamma"])


if __name__ == "__main__":
    unittest.main()
