"""Tests for lossless Decimal arithmetic and unit conversion in confam.units."""

import unittest
from decimal import Decimal
from confam.errors import ValidationError
from confam.units import (
    format_token_amount,
    format_wei,
    parse_ether_amount,
    parse_token_amount,
)


class UnitsTests(unittest.TestCase):
    def test_float_loss_prevention(self):
        """0.29 ether in float suffers binary truncation (289999999999999968 wei).

        Confam's Decimal implementation must convert it losslessly to 290000000000000000 wei.
        """
        parsed = parse_ether_amount("0.29 ether")
        self.assertEqual(parsed, 290_000_000_000_000_000)

        # 0.000000000000000001 ether = 1 wei
        self.assertEqual(parse_ether_amount("0.000000000000000001 ether"), 1)

    def test_bare_number_defaults_to_ether(self):
        self.assertEqual(parse_ether_amount("1"), 10**18)
        self.assertEqual(parse_ether_amount("0.5"), 5 * 10**17)
        self.assertEqual(parse_ether_amount("10.0"), 10 * 10**18)

    def test_all_ether_units(self):
        self.assertEqual(parse_ether_amount("10 wei"), 10)
        self.assertEqual(parse_ether_amount("5 kwei"), 5_000)
        self.assertEqual(parse_ether_amount("2 mwei"), 2_000_000)
        self.assertEqual(parse_ether_amount("50 gwei"), 50_000_000_000)
        self.assertEqual(parse_ether_amount("1 szabo"), 10**12)
        self.assertEqual(parse_ether_amount("1 finney"), 10**15)
        self.assertEqual(parse_ether_amount("1.5 eth"), int(1.5 * 10**18))

    def test_fractional_wei_rejected(self):
        with self.assertRaises(ValidationError):
            parse_ether_amount("0.5 wei")

        with self.assertRaises(ValidationError):
            parse_ether_amount("0.0000000000000000001 ether")

    def test_invalid_units_and_values(self):
        with self.assertRaises(ValidationError):
            parse_ether_amount("bad_number ether")
        with self.assertRaises(ValidationError):
            parse_ether_amount("-1 ether")
        with self.assertRaises(ValidationError):
            parse_ether_amount("10 bitcoin")
        with self.assertRaises(ValidationError):
            parse_ether_amount("")

    def test_format_wei(self):
        self.assertEqual(format_wei(10**18), "1")
        self.assertEqual(format_wei(5 * 10**17), "0.5")
        self.assertEqual(format_wei(1), "0.000000000000000001")
        self.assertEqual(format_wei(0), "0")

    def test_token_units(self):
        # USDC (6 decimals)
        self.assertEqual(parse_token_amount("100.5", decimals=6), 100_500_000)
        self.assertEqual(format_token_amount(100_500_000, decimals=6), "100.5")

        # Reject more decimals than supported
        with self.assertRaises(ValidationError):
            parse_token_amount("1.1234567", decimals=6)

        # Reject negative token amount
        with self.assertRaises(ValidationError):
            parse_token_amount("-5", decimals=6)


if __name__ == "__main__":
    unittest.main()
