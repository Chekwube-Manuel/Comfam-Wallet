"""Encrypted Web3-style keystore management for Solana Ed25519 keypairs."""

import hashlib
import json
import os
from typing import Tuple, Union
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

from confam.errors import KeystoreError, ValidationError
from confam.keystore import _atomic_write_json
from confam.solana.base58 import b58decode, b58encode
from confam.solana.keypair import SolanaKeypair


def _encrypt_seed(seed: bytes, password: str) -> dict:
    """Encrypt 32-byte seed using Scrypt KDF + AES-128-CTR."""
    salt = os.urandom(32)
    # Scrypt parameters: N=8192, r=8, p=1, dklen=32
    derived = scrypt(password.encode("utf-8"), salt, key_len=32, N=8192, r=8, p=1)
    enc_key = derived[:16]
    mac_key = derived[16:32]

    iv = os.urandom(16)
    cipher = AES.new(enc_key, AES.MODE_CTR, initial_value=iv, nonce=b"")
    ciphertext = cipher.encrypt(seed)
    mac = hashlib.sha256(mac_key + ciphertext).hexdigest()

    return {
        "cipher": "aes-128-ctr",
        "ciphertext": ciphertext.hex(),
        "cipherparams": {"iv": iv.hex()},
        "kdf": "scrypt",
        "kdfparams": {
            "dklen": 32,
            "n": 8192,
            "p": 1,
            "r": 8,
            "salt": salt.hex(),
        },
        "mac": mac,
    }


def _decrypt_seed(crypto_dict: dict, password: str) -> bytes:
    """Decrypt 32-byte seed from encrypted keystore payload."""
    try:
        salt = bytes.fromhex(crypto_dict["kdfparams"]["salt"])
        n = crypto_dict["kdfparams"].get("n", 8192)
        r = crypto_dict["kdfparams"].get("r", 8)
        p = crypto_dict["kdfparams"].get("p", 1)
        dklen = crypto_dict["kdfparams"].get("dklen", 32)
        iv = bytes.fromhex(crypto_dict["cipherparams"]["iv"])
        ciphertext = bytes.fromhex(crypto_dict["ciphertext"])
        expected_mac = crypto_dict["mac"]

        derived = scrypt(password.encode("utf-8"), salt, key_len=dklen, N=n, r=r, p=p)
        enc_key = derived[:16]
        mac_key = derived[16:32]

        calculated_mac = hashlib.sha256(mac_key + ciphertext).hexdigest()
        if calculated_mac != expected_mac:
            raise KeystoreError("could not unlock keystore (wrong password?)")

        cipher = AES.new(enc_key, AES.MODE_CTR, initial_value=iv, nonce=b"")
        return cipher.decrypt(ciphertext)
    except KeystoreError:
        raise
    except Exception as exc:
        raise KeystoreError(f"could not unlock keystore: {exc}") from exc


def create_solana_wallet(keyfile: str, password: str, force: bool = False) -> Tuple[SolanaKeypair, dict]:
    """Generate a fresh Solana keypair and save as an encrypted keystore."""
    if os.path.exists(keyfile) and not force:
        raise KeystoreError(
            f"keyfile '{keyfile}' already exists. Use --force to overwrite."
        )

    if not password:
        raise ValidationError("empty password")

    keypair = SolanaKeypair.generate()
    crypto = _encrypt_seed(keypair.seed, password)
    keystore = {
        "version": 1,
        "type": "solana",
        "address": keypair.address,
        "crypto": crypto,
    }
    _atomic_write_json(keyfile, keystore)
    return keypair, keystore


def import_solana_key(
    key_input: str, keyfile: str, password: str, force: bool = False
) -> Tuple[SolanaKeypair, dict]:
    """Import Solana private key from Base58 string or JSON array of 64 bytes."""
    if os.path.exists(keyfile) and not force:
        raise KeystoreError(
            f"keyfile '{keyfile}' already exists. Use --force to overwrite."
        )

    if not password:
        raise ValidationError("empty password")

    raw_input = key_input.strip()
    if raw_input.startswith("[") and raw_input.endswith("]"):
        try:
            byte_list = json.loads(raw_input)
            secret_bytes = bytes(byte_list)
        except Exception as exc:
            raise ValidationError(f"Invalid JSON array private key: {exc}")
    else:
        try:
            secret_bytes = b58decode(raw_input)
        except Exception as exc:
            raise ValidationError(f"Invalid Base58 private key: {exc}")

    keypair = SolanaKeypair.from_secret_key(secret_bytes)
    crypto = _encrypt_seed(keypair.seed, password)
    keystore = {
        "version": 1,
        "type": "solana",
        "address": keypair.address,
        "crypto": crypto,
    }
    _atomic_write_json(keyfile, keystore)
    return keypair, keystore


def unlock_solana_keystore(keyfile: str, password: str) -> SolanaKeypair:
    """Decrypt an existing Solana keystore and return the SolanaKeypair."""
    if not os.path.exists(keyfile):
        raise KeystoreError(f"keyfile not found: {keyfile}")

    try:
        with open(keyfile, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        raise KeystoreError(f"cannot read keyfile: {exc}") from exc

    crypto = data.get("crypto")
    if not crypto:
        raise KeystoreError(f"Invalid Solana keystore: missing crypto block")

    seed = _decrypt_seed(crypto, password)
    return SolanaKeypair.from_seed(seed)


def export_solana_key(keyfile: str, password: str) -> str:
    """Decrypt keystore and return the full 64-byte secret key in Base58."""
    keypair = unlock_solana_keystore(keyfile, password)
    return keypair.to_base58()

