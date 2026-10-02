"""Lossless currency conversion for Solana (SOL, Lamports, and SPL tokens)."""

from decimal import Decimal, InvalidOperation
from typing import Union
from confam.errors import ValidationError

LAMPORTS_PER_SOL = Decimal("1000000000")

SOL_UNITS = {
    "sol": LAMPORTS_PER_SOL,
    "lamport": Decimal("1"),
    "lamports": Decimal("1"),
}


def parse_sol_amount(value: str) -> int:
    """Parse an amount string (e.g. '0.5 sol', '50000 lamports', '1.2') to lamports.

    Uses Decimal for lossless financial precision.
    """
    if not isinstance(value, str):
        raise ValidationError(f"Amount must be a string, got {type(value).__name__}")

    raw = value.strip().lower()
    if not raw:
        raise ValidationError("Amount cannot be empty")

    parts = raw.split()
    if len(parts) == 1:
        num_str = parts[0]
        unit = "sol"
    elif len(parts) == 2:
        num_str, unit = parts
    else:
        raise ValidationError(f"Invalid amount format: '{value}'. Expected '<number> [unit]'.")

    if unit not in SOL_UNITS:
        units_str = ", ".join(sorted(set(SOL_UNITS.keys())))
        raise ValidationError(f"Unknown unit '{unit}'. Supported: {units_str}")

    try:
        dec = Decimal(num_str)
    except InvalidOperation:
        raise ValidationError(f"Invalid numerical amount: '{num_str}'")

    if dec < 0:
        raise ValidationError(f"Amount cannot be negative: '{value}'")

    lamports_dec = dec * SOL_UNITS[unit]
    if lamports_dec % 1 != 0:
        raise ValidationError(f"Amount '{value}' results in fractional lamports ({lamports_dec})")

    return int(lamports_dec)


def format_lamports(lamports: Union[int, str]) -> str:
    """Format lamports into human-readable SOL without scientific notation."""
    lam = Decimal(int(lamports))
    sol = lam / LAMPORTS_PER_SOL
    formatted = f"{sol:.9f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def parse_spl_amount(value: str, decimals: int) -> int:
    """Parse an SPL token amount with given decimals to raw integer amount."""
    raw = value.strip()
    try:
        dec = Decimal(raw)
    except InvalidOperation:
        raise ValidationError(f"Invalid token amount: '{value}'")

    if dec < 0:
        raise ValidationError("Token amount cannot be negative")

    multiplier = Decimal(10) ** decimals
    raw_amount = dec * multiplier
    if raw_amount % 1 != 0:
        raise ValidationError(f"Amount '{value}' exceeds maximum token precision of {decimals} decimals")

    return int(raw_amount)


def format_spl_amount(raw_amount: Union[int, str], decimals: int) -> str:
    """Format raw token amount with decimals into human-readable string."""
    amt = Decimal(int(raw_amount))
    divisor = Decimal(10) ** decimals
    dec = amt / divisor
    formatted = f"{dec:.{decimals}f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"

