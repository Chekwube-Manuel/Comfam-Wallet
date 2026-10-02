"""Base58 encoding and decoding for Solana addresses and signatures."""

import hashlib
from confam.errors import ValidationError

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58_MAP = {char: idx for idx, char in enumerate(B58_ALPHABET)}


def b58encode(data: bytes) -> str:
    """Encode bytes into a Base58 string."""
    if not isinstance(data, (bytes, bytearray)):
        raise ValidationError(f"Expected bytes, got {type(data).__name__}")

    n = int.from_bytes(data, "big")
    chars = []
    while n > 0:
        n, r = divmod(n, 58)
        chars.append(B58_ALPHABET[r])

    # Count leading zeroes in original bytes
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break

    return "1" * pad + "".join(reversed(chars))


def b58decode(text: str) -> bytes:
    """Decode a Base58 string into bytes."""
    if not isinstance(text, str):
        raise ValidationError(f"Expected string, got {type(text).__name__}")

    s = text.strip()
    if not s:
        return b""

    n = 0
    for char in s:
        if char not in B58_MAP:
            raise ValidationError(f"Invalid Base58 character '{char}' in '{text}'")
        n = n * 58 + B58_MAP[char]

    pad = 0
    for char in s:
        if char == "1":
            pad += 1
        else:
            break

    res = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * pad + res


def b58encode_check(data: bytes) -> str:
    """Encode data with a 4-byte double SHA-256 checksum."""
    checksum = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    return b58encode(data + checksum)


def b58decode_check(text: str) -> bytes:
    """Decode and verify 4-byte double SHA-256 checksum."""
    raw = b58decode(text)
    if len(raw) < 4:
        raise ValidationError("Base58Check payload too short")
    data, check = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    if check != digest:
        raise ValidationError("Invalid Base58 checksum")
    return data

