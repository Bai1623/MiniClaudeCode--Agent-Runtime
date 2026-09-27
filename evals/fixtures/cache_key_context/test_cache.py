import unittest

from cache import make_cache_key


class TestCacheKey(unittest.TestCase):
    def test_same_context_is_stable(self):
        first = make_cache_key("/home", "zh-CN", "acme")
        second = make_cache_key("/home", "zh-CN", "acme")
        self.assertEqual(first, second)

    def test_locale_and_tenant_are_part_of_key(self):
        base = make_cache_key("/home", "zh-CN", "acme")
        self.assertNotEqual(base, make_cache_key("/home", "en-US", "acme"))
        self.assertNotEqual(base, make_cache_key("/home", "zh-CN", "other"))


if __name__ == "__main__":
    unittest.main()
