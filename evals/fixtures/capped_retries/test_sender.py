import unittest

from policy import retry_delays
from sender import send_with_retry


class TestSender(unittest.TestCase):
    def test_returns_without_retry_on_first_success(self):
        sleeps = []
        result = send_with_retry(lambda: "ok", sleeps.append)
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [])

    def test_policy_caps_exponential_delays(self):
        self.assertEqual(retry_delays(5, base=2, cap=5), [2, 4, 5, 5, 5])

    def test_retries_until_success_using_policy(self):
        attempts = iter([RuntimeError("one"), RuntimeError("two"), "ok"])
        sleeps = []

        def send():
            result = next(attempts)
            if isinstance(result, Exception):
                raise result
            return result

        self.assertEqual(send_with_retry(send, sleeps.append, retries=3, base=1, cap=2), "ok")
        self.assertEqual(sleeps, [1, 2])


if __name__ == "__main__":
    unittest.main()
