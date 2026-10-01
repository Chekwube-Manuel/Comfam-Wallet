"""Secure Web3 V3 keystore management with atomic writes and permission hardening."""

import getpass
import json
import os
import stat
import subprocess
import sys
import tempfile
from typing import Optional, Tuple

from eth_account import Account
from eth_utils import to_checksum_address

from confam.errors import KeystoreError, ValidationError


def _secure_file_permissions(filepath: str) -> None:
    """Apply strict owner-only read/write permissions cross-platform."""
    if os.name == "posix":
        try:
            os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    elif os.name == "nt":
        # On Windows NTFS, restrict ACLs to current user using icacls if available
        try:
            username = os.environ.get("USERNAME")
            if username:
                subprocess.run(
                    [
                        "icacls.exe",
                        filepath,
                        "/inheritance:r",
                        "/grant:r",
                        f"{username}:(R,W)",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        except Exception:
            pass


def _atomic_write_json(filepath: str, data: dict) -> None:
    """Write data to a temporary file first, then atomically replace destination."""
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(dir=dirpath, prefix=".confam_tmp_")
    try:
        with open(temp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        _secure_file_permissions(temp_path)
        os.replace(temp_path, filepath)
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise KeystoreError(f"Failed to write keystore safely: {exc}") from exc


def load_keystore(keyfile: str) -> dict:
    """Load and validate JSON structure of an Ethereum keystore."""
    if not os.path.exists(keyfile):
        raise KeystoreError(f"keyfile not found: {keyfile}")
    if os.path.isdir(keyfile):
        raise KeystoreError(f"keyfile is a directory: {keyfile}")

    try:
        with open(keyfile, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise KeystoreError(f"keyfile is not valid JSON: {keyfile}") from exc
    except OSError as exc:
        raise KeystoreError(f"cannot read keyfile '{keyfile}': {exc}") from exc

    if not isinstance(data, dict) or ("crypto" not in data and "Crypto" not in data):
        raise KeystoreError(f"keyfile is not a valid Web3 Ethereum keystore: {keyfile}")

    return data


def create_wallet(keyfile: str, password: str, force: bool = False) -> Tuple[Account, dict]:
    """Generate a new private key locally and save as an encrypted Web3 V3 keystore."""
    if os.path.exists(keyfile) and not force:
        raise KeystoreError(
            f"keyfile '{keyfile}' already exists. Use --force to overwrite (CAUTION: previous key will be destroyed)."
        )

    if not password:
        raise ValidationError("empty password")

    account = Account.create()
    keystore = account.encrypt(password, kdf="scrypt")
    _atomic_write_json(keyfile, keystore)
    return account, keystore


def import_private_key(
    private_key_hex: str, keyfile: str, password: str, force: bool = False
) -> Tuple[Account, dict]:
    """Import an existing private key and save as an encrypted Web3 V3 keystore."""
    if os.path.exists(keyfile) and not force:
        raise KeystoreError(
            f"keyfile '{keyfile}' already exists. Use --force to overwrite (CAUTION: previous key will be destroyed)."
        )

    if not password:
        raise ValidationError("empty password")

    clean_key = private_key_hex.strip()
    if clean_key.startswith("0x"):
        clean_key = clean_key[2:]

    if len(clean_key) != 64:
        raise ValidationError("private key must be a 32-byte hex string (64 characters)")

    try:
        bytes.fromhex(clean_key)
    except ValueError as exc:
        raise ValidationError(f"private key contains invalid hex characters: {exc}") from exc

    try:
        account = Account.from_key("0x" + clean_key)
    except Exception as exc:
        raise ValidationError(f"invalid private key: {exc}") from exc

    keystore = account.encrypt(password, kdf="scrypt")
    _atomic_write_json(keyfile, keystore)
    return account, keystore


def unlock_keystore(keyfile: str, password: str) -> Account:
    """Decrypt an existing keystore and return the unlocked Account object."""
    keystore = load_keystore(keyfile)
    try:
        private_key = Account.decrypt(keystore, password)
    except Exception as exc:
        raise KeystoreError(f"could not unlock keystore (wrong password?): {exc}") from exc

    return Account.from_key(private_key)


def export_private_key(keyfile: str, password: str) -> str:
    """Decrypt keystore and return the 0x-prefixed private key hex."""
    account = unlock_keystore(keyfile, password)
    key = account.key
    raw_hex = key.hex() if hasattr(key, "hex") else key.to_0x_hex()
    return raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex


def resolve_password(
    args,
    prompt: str = "Keystore password: ",
    confirm: bool = False,
) -> str:
    """Resolve password from CLI flag, stdin, environment variable, or secure prompt."""
    if getattr(args, "password", None):
        return args.password

    if getattr(args, "password_stdin", False):
        pwd = sys.stdin.readline().rstrip("\r\n")
        if not pwd:
            raise ValidationError("empty password from stdin")
        return pwd

    env_pwd = os.environ.get("CONFAM_PASSWORD")
    if env_pwd:
        return env_pwd

    pwd = getpass.getpass(prompt)
    if not pwd:
        raise ValidationError("empty password")

    if confirm:
        pwd2 = getpass.getpass("Confirm password: ")
        if pwd != pwd2:
            raise ValidationError("passwords do not match")

    return pwd
