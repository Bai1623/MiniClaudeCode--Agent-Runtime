import unittest

from redaction import redact


class TestRedaction(unittest.TestCase):
    def test_redacts_top_level_secret(self):
        self.assertEqual(redact({"token": "abc", "name": "agent"}), {"token": "***", "name": "agent"})

    def test_redacts_nested_collections_without_mutation(self):
        source = {
            "database": {"password": "db-pass", "host": "localhost"},
            "accounts": [{"name": "a", "secret": "one"}, {"token": "two"}],
        }
        result = redact(source)
        self.assertEqual(result["database"]["password"], "***")
        self.assertEqual(result["accounts"][0]["secret"], "***")
        self.assertEqual(result["accounts"][1]["token"], "***")
        self.assertEqual(source["database"]["password"], "db-pass")


if __name__ == "__main__":
    unittest.main()
