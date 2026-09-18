#!/usr/bin/env python3
"""Confam Wallet - a non-custodial Ethereum CLI wallet.

Keys are generated on this machine (CSPRNG), stored in a password-encrypted
Web3 V3 keystore, and every signature is produced locally. The network is
only ever contacted for public reads (nonce, gas, balance) and to broadcast
already-signed raw transactions. No key material ever leaves the machine.

RPC endpoint is taken from CONFAM_RPC_URL (defaults to http://127.0.0.1:8545).
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

DEFAULT_RPC_URL = "http://127.0.0.1:8545"
ETHER_UNITS = {
    "wei": 1,
    "gwei": 10**9,
    "ether": 10**18,
}


def rpc_url() -> str:
    return os.environ.get("CONFAM_RPC_URL", DEFAULT_RPC_URL)


def rpc_call(method: str, params):
    """Perform a single JSON-RPC 2.0 call and return the result (or raise)."""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)}
    ).encode()
    req = urllib.request.Request(
        rpc_url(),
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: cannot reach RPC at {rpc_url()}: {exc}")
    if "error" in body:
        raise SystemExit(f"error: RPC {method} failed: {body['error']}")
    return body["result"]


def load_keystore(keyfile: str) -> dict:
    try:
        with open(keyfile, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"error: keyfile not found: {keyfile}")
    except json.JSONDecodeError:
        raise SystemExit(f"error: keyfile is not valid JSON: {keyfile}")


def ask_password(prompt: str) -> str:
    password = getpass.getpass(prompt)
    if not password:
        raise SystemExit("error: empty password")
    return password


def get_password(args) -> str:
    if getattr(args, "password", None):
        return args.password
    return ask_password("Keystore password: ")


def _choose_password(args) -> str:
    if getattr(args, "password", None):
        return args.password
    first = ask_password("Choose a keystore password: ")
    again = getpass.getpass("Confirm password: ")
    if again != first:
        raise SystemExit("error: passwords do not match")
    return first


def private_key_hex(account) -> str:
    key = account.key
    return key.hex() if hasattr(key, "hex") else key.to_0x_hex()


def cmd_create(args) -> int:
    account = Account.create()
    password = _choose_password(args)
    keystore = account.encrypt(password, kdf="scrypt")
    os.makedirs(os.path.dirname(os.path.abspath(args.keyfile)), exist_ok=True)
    with open(args.keyfile, "w", encoding="utf-8") as fh:
        json.dump(keystore, fh, indent=2)
        fh.write("\n")
    try:
        os.chmod(args.keyfile, 0o600)
    except OSError:
        pass
    print(f"created:  {to_checksum_address(account.address)}")
    print(f"keyfile:  {args.keyfile}")
    print("Your key never left this machine. Back up the keyfile and password now.")
    return 0


def cmd_import_key(args) -> int:
    account = Account.from_key(args.private_key)
    password = _choose_password(args)
    keystore = account.encrypt(password, kdf="scrypt")
    os.makedirs(os.path.dirname(os.path.abspath(args.keyfile)), exist_ok=True)
    with open(args.keyfile, "w", encoding="utf-8") as fh:
        json.dump(keystore, fh, indent=2)
        fh.write("\n")
    try:
        os.chmod(args.keyfile, 0o600)
    except OSError:
        pass
    print(f"imported: {to_checksum_address(account.address)}")
    print(f"keyfile:  {args.keyfile}")
    return 0


def _unlock(args) -> Account:
    password = get_password(args)
    keystore = load_keystore(args.keyfile)
    try:
        private_key = Account.decrypt(keystore, password)
    except Exception as exc:
        raise SystemExit(f"error: could not unlock keystore (wrong password?): {exc}")
    return Account.from_key(private_key)


def cmd_address(args) -> int:
    account = _unlock(args)
    print(to_checksum_address(account.address))
    return 0


def cmd_balance(args) -> int:
    account = _unlock(args)
    result = rpc_call("eth_getBalance", [account.address.lower(), "latest"])
    wei = int(result, 16) if isinstance(result, str) else int(result)
    print(f"{wei} wei")
    print(f"{wei / 10**18:.18f} ETH")
    return 0


def _hex(data) -> str:
    """Render bytes/HexBytes as a 0x-prefixed hex string."""
    if isinstance(data, str):
        return data if data.startswith("0x") else "0x" + data
    return "0x" + bytes(data).hex()


def cmd_sign_message(args) -> int:
    account = _unlock(args)
    signed = account.sign_message(encode_defunct(text=args.message))
    sig = _hex(signed.signature)
    print(sig)
    print(
        "verify:  confam verify-message --address "
        f"{to_checksum_address(account.address)} "
        f"--signature {sig} "
        f"--message '{args.message}'"
    )
    return 0


def cmd_verify_message(args) -> int:
    signature = args.signature if args.signature.startswith("0x") else "0x" + args.signature
    recovered = Account.recover_message(
        encode_defunct(text=args.message),
        signature=bytes.fromhex(signature[2:]),
    )
    expected = to_checksum_address(args.address)
    ok = to_checksum_address(recovered) == expected
    print(f"recovered: {to_checksum_address(recovered)}")
    print("valid" if ok else "INVALID: signature does not match address")
    return 0 if ok else 1


def _parse_amount(value: str) -> int:
    try:
        num, _, unit = value.lower().rpartition(" ")
        unit = unit or "ether"
        if unit not in ETHER_UNITS:
            raise ValueError
        return int(float(num) * ETHER_UNITS[unit])
    except ValueError:
        raise SystemExit(f"error: bad amount {value!r} (use e.g. '0.01 ether' or '1234567 gwei')")


def _tx_fields(from_addr: str, to: str, value_wei: int):
    chain_id = int(rpc_call("eth_chainId", []), 16)
    nonce = int(rpc_call("eth_getTransactionCount", [from_addr, "pending"]), 16)
    latest = rpc_call("eth_getBlockByNumber", ["latest", False])
    data = {"to": to_checksum_address(to), "value": value_wei,
            "nonce": nonce, "chainId": chain_id}
    base_fee = latest.get("baseFeePerGas")
    if base_fee is not None:
        base = int(base_fee, 16)
        data["maxFeePerGas"] = base * 2
        data["maxPriorityFeePerGas"] = min(base, 2 * 10**9)
    else:
        data["gasPrice"] = int(rpc_call("eth_gasPrice", []), 16)
    try:
        data["gas"] = int(
            rpc_call(
                "eth_estimateGas",
                [{"from": from_addr, "to": data["to"], "value": hex(value_wei)}],
            ),
            16,
        ) + 1000
    except SystemExit:
        data["gas"] = 21000
    return data


def cmd_send_tx(args) -> int:
    value_wei = _parse_amount(args.amount)
    account = _unlock(args)
    from_addr = to_checksum_address(account.address)
    tx = _tx_fields(from_addr, args.to, value_wei)
    tx["from"] = from_addr
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None)
    if raw is None:  # older eth-account versions
        raw = signed.rawTransaction
    tx_hash = rpc_call("eth_sendRawTransaction", [_hex(raw)])
    print(f"sent:  {tx_hash}")
    print(f"from:  {to_checksum_address(account.address)}")
    print(f"to:    {to_checksum_address(args.to)}")
    print(f"value: {value_wei} wei")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confam",
        description="Confam Wallet - non-custodial Ethereum wallet CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, needs_keyfile=True):
        if needs_keyfile:
            p.add_argument("--keyfile", required=True, help="path to the encrypted keystore")
            p.add_argument("--password", help="keystore password (defaults to a hidden prompt)")

    p = sub.add_parser("create", help="generate a new key locally and save an encrypted keystore")
    p.add_argument("--keyfile", required=True)
    p.add_argument("--password", help="keystore password (defaults to a hidden prompt)")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("import-key", help="import an existing private key into an encrypted keystore")
    p.add_argument("--private-key", required=True)
    p.add_argument("--keyfile", required=True)
    p.add_argument("--password")
    p.set_defaults(func=cmd_import_key)

    p = sub.add_parser("address", help="print the checksum address for a keystore")
    add_common(p)
    p.set_defaults(func=cmd_address)

    p = sub.add_parser("balance", help="print the account balance in wei and ETH")
    add_common(p)
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("sign-message", help="sign a message locally (EIP-191 personal_sign)")
    add_common(p)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_sign_message)

    p = sub.add_parser("verify-message", help="recover the signer of a message and compare it to an address")
    p.add_argument("--address", required=True)
    p.add_argument("--signature", required=True)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_verify_message)

    p = sub.add_parser("send-tx", help="build, sign locally, and broadcast an ETH transfer")
    add_common(p)
    p.add_argument("--to", required=True, help="recipient address")
    p.add_argument("--amount", required=True, help="amount like '0.01 ether' or '1234567 gwei'")
    p.set_defaults(func=cmd_send_tx)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())