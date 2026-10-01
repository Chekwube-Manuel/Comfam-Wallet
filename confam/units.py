"""Lossless currency and unit conversion using Decimal arithmetic."""

from decimal import Decimal, InvalidOperation
from typing import Union
from confam.errors import ValidationError

ETHER_UNITS = {
    "wei": Decimal("1"),
    "kwei": Decimal("1000"),
    "mwei": Decimal("1000000"),
    "gwei": Decimal("1000000000"),
    "szabo": Decimal("1000000000000"),
    "finney": Decimal("1000000000000000"),
    "ether": Decimal("1000000000000000000"),
    "eth": Decimal("1000000000000000000"),
}


def parse_ether_amount(value: str) -> int:
    """Parse an ether amount string (e.g. '0.01 ether', '50 gwei', '0.5') to wei.

    Uses Decimal to avoid floating point inaccuracy (e.g. 0.29 float loss).
    """
    if not isinstance(value, str):
        raise ValidationError(f"bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")

    raw = value.strip().lower()
    if not raw:
        raise ValidationError(f"bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")

    parts = raw.split()
    if len(parts) == 1:
        num_str = parts[0]
        unit = "ether"
    elif len(parts) == 2:
        num_str, unit = parts
    else:
        raise ValidationError(f"bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")

    if unit not in ETHER_UNITS:
        raise ValidationError(f"bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")

    try:
        dec_num = Decimal(num_str)
    except InvalidOperation:
        raise ValidationError(f"bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")

    if dec_num < 0:
        raise ValidationError(f"bad amount {value!r} (amount cannot be negative)")

    multiplier = ETHER_UNITS[unit]
    wei_decimal = dec_num * multiplier

    # Verify that there is no fractional wei
    if wei_decimal % 1 != 0:
        raise ValidationError(f"bad amount {value!r} (results in fractional wei: {wei_decimal})")

    return int(wei_decimal)


def format_wei(wei_amount: Union[int, str]) -> str:
    """Format wei amount into human-readable ETH string without scientific notation."""
    wei = int(wei_amount)
    eth_decimal = Decimal(wei) / Decimal("1000000000000000000")
    formatted = f"{eth_decimal:.18f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def parse_token_amount(value: str, decimals: int) -> int:
    """Parse a token amount with arbitrary decimals (e.g. USDC with 6 decimals)."""
    raw = value.strip()
    try:
        dec = Decimal(raw)
    except InvalidOperation:
        raise ValidationError(f"bad amount {value!r} (expected valid decimal number)")

    if dec < 0:
        raise ValidationError("token amount cannot be negative")

    multiplier = Decimal(10) ** decimals
    raw_amount = dec * multiplier
    if raw_amount % 1 != 0:
        raise ValidationError(f"token amount '{value}' has more precision than {decimals} decimals")

    return int(raw_amount)


def format_token_amount(raw_amount: Union[int, str], decimals: int) -> str:
    """Format raw token amount with specified decimals into human-readable string."""
    amt = Decimal(int(raw_amount))
    divisor = Decimal(10) ** decimals
    dec = amt / divisor
    formatted = f"{dec:.{decimals}f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"

