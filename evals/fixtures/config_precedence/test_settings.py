import unittest

from settings import load_settings


class TestSettings(unittest.TestCase):
    def test_environment_has_highest_precedence(self):
        result = load_settings(
            {"mode": "safe", "workers": 1},
            {"workers": 2},
            {"workers": 8},
        )
        self.assertEqual(result["workers"], 8)

    def test_keeps_unoverridden_defaults(self):
        result = load_settings({"mode": "safe"}, {}, {"workers": 4})
        self.assertEqual(result, {"mode": "safe", "workers": 4})


if __name__ == "__main__":
    unittest.main()
