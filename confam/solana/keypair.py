"""Ed25519 keypair management for Solana."""

import os
from typing import Union
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from confam.errors import ValidationError
from confam.solana.base58 import b58decode, b58encode


class SolanaKeypair:
    """Solana Ed25519 Keypair handling address generation and message signing."""

    def __init__(self, seed: bytes):
        if not isinstance(seed, (bytes, bytearray)) or len(seed) != 32:
            raise ValidationError("Solana seed must be exactly 32 bytes")
        self._seed = bytes(seed)
        self._ecc = ECC.construct(curve="ed25519", seed=self._seed)
        self._pub_bytes = self._ecc.public_key().export_key(format="raw")
        self._address = b58encode(self._pub_bytes)

    @classmethod
    def generate(cls) -> "SolanaKeypair":
        """Generate a cryptographically secure random Solana keypair using OS CSPRNG."""
        seed = os.urandom(32)
        return cls(seed)

    @classmethod
    def from_seed(cls, seed: bytes) -> "SolanaKeypair":
        """Construct keypair from 32-byte seed."""
        return cls(seed)

    @classmethod
    def from_secret_key(cls, secret_key: bytes) -> "SolanaKeypair":
        """Construct keypair from 64-byte secret key (seed + public key) or 32-byte seed."""
        if len(secret_key) == 64:
            seed = secret_key[:32]
        elif len(secret_key) == 32:
            seed = secret_key
        else:
            raise ValidationError(f"Invalid secret key length: expected 32 or 64 bytes, got {len(secret_key)}")
        return cls(seed)

    @classmethod
    def from_base58(cls, b58_str: str) -> "SolanaKeypair":
        """Import keypair from Base58-encoded secret key string."""
        raw = b58decode(b58_str.strip())
        return cls.from_secret_key(raw)

    @property
    def seed(self) -> bytes:
        return self._seed

    @property
    def public_key_bytes(self) -> bytes:
        """32-byte raw public key."""
        return self._pub_bytes

    @property
    def address(self) -> str:
        """Base58-encoded public key address."""
        return self._address

    @property
    def secret_key_bytes(self) -> bytes:
        """64-byte full secret key (seed + public key) as standard in Solana."""
        return self._seed + self._pub_bytes

    def sign(self, message: bytes) -> bytes:
        """Sign message using Ed25519 (RFC 8032) and return 64-byte signature."""
        signer = eddsa.new(self._ecc, "rfc8032")
        return signer.sign(message)

    @staticmethod
    def verify(pubkey_bytes: bytes, message: bytes, signature: bytes) -> bool:
        """Verify an Ed25519 signature against a 32-byte public key."""
        if len(pubkey_bytes) != 32:
            raise ValidationError(f"Public key must be 32 bytes, got {len(pubkey_bytes)}")
        if len(signature) != 64:
            raise ValidationError(f"Signature must be 64 bytes, got {len(signature)}")

        # RFC 8410 SubjectPublicKeyInfo prefix for Ed25519
        ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
        try:
            der_key = ED25519_SPKI_PREFIX + pubkey_bytes
            ecc_pub = ECC.import_key(der_key)
            verifier = eddsa.new(ecc_pub, "rfc8032")
            verifier.verify(message, signature)
            return True
        except (ValueError, TypeError):
            return False

    def to_base58(self) -> str:
        """Export full 64-byte secret key in Base58 format."""
        return b58encode(self.secret_key_bytes)

    def to_json_array(self) -> list:
        """Export 64-byte secret key as list of integers (Solana CLI format)."""
        return list(self.secret_key_bytes)
