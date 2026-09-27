import unittest

from pricing import subtotal, total_with_tax


class TestPricing(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(subtotal([10.0, 5.0]), 15.0)

    def test_fractional_tax_uses_currency_precision(self):
        self.assertAlmostEqual(total_with_tax([19.99], 0.07), 21.39, places=2)


if __name__ == "__main__":
    unittest.main()
