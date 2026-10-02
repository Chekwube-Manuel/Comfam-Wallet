"""Confam Wallet - Production-grade non-custodial multi-chain CLI wallet."""

import argparse
import getpass
import json
import os
import sys
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from confam import __version__
from confam.erc20 import (
    build_erc20_transfer_data,
    get_token_balance,
    get_token_metadata,
)
from confam.errors import ConfamError, KeystoreError, ValidationError
from confam.keystore import (
    create_wallet,
    export_private_key,
    import_private_key,
    resolve_password,
    unlock_keystore,
)
from confam.rpc import RpcClient
from confam.solana.cli import register_solana_subparser
from confam.tx import (
    build_transaction,
    sign_transaction,
    validate_address,
    wait_for_receipt,
)
from confam.units import (
    format_token_amount,
    format_wei,
    parse_ether_amount,
    parse_token_amount,
)

DEFAULT_CONFAM_DIR = os.path.expanduser("~/.confam")
DEFAULT_ETH_KEYFILE = os.path.join(DEFAULT_CONFAM_DIR, "ethereum.json")


def _get_rpc(args) -> RpcClient:
    rpc_url = getattr(args, "rpc_url", None)
    return RpcClient(endpoint_url=rpc_url)


def _resolve_eth_keyfile(args, for_creation: bool = False) -> str:
    kf = getattr(args, "keyfile", None)
    if kf:
        return os.path.abspath(kf)
    env_kf = os.environ.get("CONFAM_KEYFILE")
    if env_kf:
        return os.path.abspath(env_kf)
    if not for_creation and not os.path.exists(DEFAULT_ETH_KEYFILE):
        raise KeystoreError(
            f"No Ethereum wallet found at default path '{DEFAULT_ETH_KEYFILE}'. "
            f"Run 'confam create' first or pass --keyfile."
        )
    return DEFAULT_ETH_KEYFILE


def _render_receipt(receipt: dict) -> None:
    status_raw = receipt.get("status")
    status = "SUCCESS" if status_raw in (1, "0x1", "0x01") else "REVERTED"
    block_number = int(receipt.get("blockNumber", 0), 16) if isinstance(receipt.get("blockNumber"), str) else receipt.get("blockNumber")
    gas_used = int(receipt.get("gasUsed", 0), 16) if isinstance(receipt.get("gasUsed"), str) else receipt.get("gasUsed")

    print(f"status:       {status}")
    print(f"blockNumber:  {block_number}")
    print(f"gasUsed:      {gas_used}")
    if "effectiveGasPrice" in receipt:
        eff_price = int(receipt["effectiveGasPrice"], 16) if isinstance(receipt["effectiveGasPrice"], str) else receipt["effectiveGasPrice"]
        print(f"effectiveGas: {format_wei(eff_price * gas_used)} ETH ({eff_price} wei/gas)")


def cmd_create(args) -> int:
    keyfile = _resolve_eth_keyfile(args, for_creation=True)
    password = resolve_password(args, prompt="Choose a keystore password: ", confirm=True)
    account, _ = create_wallet(keyfile, password, force=args.force)
    print(f"created:  {to_checksum_address(account.address)}")
    print(f"keyfile:  {keyfile}")
    print("Your key never left this machine. Back up the keyfile and password now.")
    return 0


def cmd_import_key(args) -> int:
    keyfile = _resolve_eth_keyfile(args, for_creation=True)
    private_key = args.private_key
    if not private_key:
        private_key = getpass.getpass("Enter private key hex: ")
        if not private_key:
            raise ValidationError("empty private key")

    password = resolve_password(args, prompt="Choose a keystore password: ", confirm=True)
    account, _ = import_private_key(private_key, keyfile, password, force=args.force)
    print(f"imported: {to_checksum_address(account.address)}")
    print(f"keyfile:  {keyfile}")
    return 0


def cmd_export_key(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    if not args.yes:
        confirm = input(f"WARNING: Exporting key from {keyfile} exposes all funds. Continue? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Export cancelled.")
            return 1

    password = resolve_password(args)
    priv_key = export_private_key(keyfile, password)
    print(f"private_key: {priv_key}")
    return 0


def cmd_address(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    password = resolve_password(args)
    account = unlock_keystore(keyfile, password)
    print(to_checksum_address(account.address))
    return 0


def cmd_balance(args) -> int:
    rpc = _get_rpc(args)
    if args.address:
        target_addr = validate_address(args.address)
    else:
        keyfile = _resolve_eth_keyfile(args)
        password = resolve_password(args)
        account = unlock_keystore(keyfile, password)
        target_addr = to_checksum_address(account.address)

    result = rpc.call("eth_getBalance", [target_addr.lower(), "latest"])
    wei = int(result, 16) if isinstance(result, str) else int(result)
    print(f"address: {target_addr}")
    print(f"balance: {wei} wei")
    print(f"         {format_wei(wei)} ETH")
    return 0


def cmd_chain_info(args) -> int:
    rpc = _get_rpc(args)
    chain_id = rpc.get_chain_id()
    block = rpc.get_block_number()
    latest_block = rpc.get_block_by_number("latest")
    gas_price = rpc.gas_price()
    base_fee = latest_block.get("baseFeePerGas")

    print(f"rpc:          {rpc.endpoint_url}")
    print(f"chainId:      {chain_id}")
    print(f"blockNumber:  {block}")
    print(f"gasPrice:     {format_wei(gas_price)} ETH ({gas_price} wei)")
    if base_fee is not None:
        bf = int(base_fee, 16) if isinstance(base_fee, str) else base_fee
        print(f"baseFeePerGas:{bf} wei")
    return 0


def cmd_gas_price(args) -> int:
    rpc = _get_rpc(args)
    latest_block = rpc.get_block_by_number("latest")
    base_fee_hex = latest_block.get("baseFeePerGas")
    gas_price = rpc.gas_price()

    print(f"legacyGasPrice: {gas_price} wei ({gas_price / 10**9:.2f} Gwei)")
    if base_fee_hex is not None:
        base_fee = int(base_fee_hex, 16) if isinstance(base_fee_hex, str) else base_fee_hex
        prio = rpc.max_priority_fee_per_gas() or 1_500_000_000
        print(f"baseFeePerGas:  {base_fee} wei ({base_fee / 10**9:.2f} Gwei)")
        print(f"maxPriorityFee: {prio} wei ({prio / 10**9:.2f} Gwei)")
        print(f"recommendedMax: {base_fee * 2 + prio} wei ({(base_fee * 2 + prio) / 10**9:.2f} Gwei)")
    return 0


def cmd_sign_message(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    password = resolve_password(args)
    account = unlock_keystore(keyfile, password)
    signed = account.sign_message(encode_defunct(text=args.message))
    raw_sig = signed.signature
    sig_hex = "0x" + raw_sig.hex() if hasattr(raw_sig, "hex") else "0x" + bytes(raw_sig).hex()
    addr = to_checksum_address(account.address)
    print(sig_hex)
    print(f"verify:  confam verify-message --address {addr} --signature {sig_hex} --message '{args.message}'")
    return 0


def cmd_verify_message(args) -> int:
    expected = validate_address(args.address)
    signature = args.signature.strip()
    if signature.startswith("0x"):
        raw_sig_hex = signature[2:]
    else:
        raw_sig_hex = signature

    if len(raw_sig_hex) != 130:
        raise ValidationError(f"Signature must be 65 bytes (130 hex characters), got {len(raw_sig_hex) // 2} bytes")

    try:
        sig_bytes = bytes.fromhex(raw_sig_hex)
    except ValueError as exc:
        raise ValidationError(f"Invalid signature hex: {exc}")

    try:
        recovered = Account.recover_message(
            encode_defunct(text=args.message),
            signature=sig_bytes,
        )
    except Exception as exc:
        raise ValidationError(f"Could not recover signer from signature: {exc}")

    recovered_addr = to_checksum_address(recovered)
    ok = recovered_addr == expected
    print(f"recovered: {recovered_addr}")
    print("valid" if ok else "INVALID: signature does not match address")
    return 0 if ok else 1


def cmd_send_tx(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    value_wei = parse_ether_amount(args.amount)
    password = resolve_password(args)
    account = unlock_keystore(keyfile, password)
    rpc = _get_rpc(args)

    from_addr = to_checksum_address(account.address)
    to_addr = validate_address(args.to)

    tx_dict = build_transaction(
        rpc=rpc,
        from_addr=from_addr,
        to=to_addr,
        value_wei=value_wei,
        data=args.data or "",
        gas_limit=args.gas_limit,
    )

    raw_tx = sign_transaction(account, tx_dict)
    tx_hash = rpc.send_raw_transaction(raw_tx)

    print(f"sent:  {tx_hash}")
    print(f"from:  {from_addr}")
    print(f"to:    {to_addr}")
    print(f"value: {value_wei} wei")

    if args.wait:
        print("Waiting for transaction confirmation...")
        receipt = wait_for_receipt(rpc, tx_hash, timeout=args.timeout)
        _render_receipt(receipt)

    return 0


def cmd_token_balance(args) -> int:
    rpc = _get_rpc(args)
    if args.address:
        target_addr = validate_address(args.address)
    else:
        keyfile = _resolve_eth_keyfile(args)
        password = resolve_password(args)
        account = unlock_keystore(keyfile, password)
        target_addr = to_checksum_address(account.address)

    raw_bal, meta = get_token_balance(rpc, args.token, target_addr)
    formatted = format_token_amount(raw_bal, meta["decimals"])
    print(f"token:    {meta['name']} ({meta['symbol']})")
    print(f"contract: {meta['address']}")
    print(f"decimals: {meta['decimals']}")
    print(f"balance:  {raw_bal} raw units")
    print(f"          {formatted} {meta['symbol']}")
    return 0


def cmd_transfer_token(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    rpc = _get_rpc(args)
    password = resolve_password(args)
    account = unlock_keystore(keyfile, password)
    from_addr = to_checksum_address(account.address)
    to_addr = validate_address(args.to)
    token_addr = validate_address(args.token)

    meta = get_token_metadata(rpc, token_addr)
    raw_amount = parse_token_amount(args.amount, meta["decimals"])
    calldata = build_erc20_transfer_data(to_addr, raw_amount)

    tx_dict = build_transaction(
        rpc=rpc,
        from_addr=from_addr,
        to=token_addr,
        value_wei=0,
        data=calldata,
        gas_limit=args.gas_limit,
    )

    raw_tx = sign_transaction(account, tx_dict)
    tx_hash = rpc.send_raw_transaction(raw_tx)

    print(f"sent:   {tx_hash}")
    print(f"token:  {meta['symbol']} ({token_addr})")
    print(f"from:   {from_addr}")
    print(f"to:     {to_addr}")
    print(f"amount: {raw_amount} ({format_token_amount(raw_amount, meta['decimals'])} {meta['symbol']})")

    if args.wait:
        print("Waiting for transaction confirmation...")
        receipt = wait_for_receipt(rpc, tx_hash, timeout=args.timeout)
        _render_receipt(receipt)

    return 0


def cmd_receipt(args) -> int:
    rpc = _get_rpc(args)
    receipt = rpc.get_transaction_receipt(args.tx_hash)
    if receipt is None:
        print(f"Transaction {args.tx_hash} is pending or not found.")
        return 1
    _render_receipt(receipt)
    return 0


def cmd_sign_tx(args) -> int:
    keyfile = _resolve_eth_keyfile(args)
    password = resolve_password(args)
    account = unlock_keystore(keyfile, password)
    to_addr = validate_address(args.to)
    value_wei = parse_ether_amount(args.amount)

    tx = {
        "from": to_checksum_address(account.address),
        "to": to_addr,
        "value": value_wei,
        "nonce": args.nonce,
        "chainId": args.chain_id,
        "gas": args.gas_limit,
    }
    if args.data:
        tx["data"] = args.data if args.data.startswith("0x") else "0x" + args.data

    if args.max_fee is not None:
        tx["maxFeePerGas"] = args.max_fee
        tx["maxPriorityFeePerGas"] = args.priority_fee or 1_500_000_000
        tx["type"] = "0x2"
    elif args.gas_price is not None:
        tx["gasPrice"] = args.gas_price
    else:
        raise ValidationError("Must provide either --max-fee (EIP-1559) or --gas-price (legacy) for offline signing")

    raw = sign_transaction(account, tx)
    print(raw)
    return 0


def cmd_broadcast_tx(args) -> int:
    rpc = _get_rpc(args)
    tx_hash = rpc.send_raw_transaction(args.raw_tx)
    print(f"broadcast: {tx_hash}")

    if args.wait:
        print("Waiting for transaction confirmation...")
        receipt = wait_for_receipt(rpc, tx_hash, timeout=args.timeout)
        _render_receipt(receipt)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confam",
        description="Confam Wallet - non-custodial multi-chain (Ethereum & Solana) wallet CLI",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="Print complete Python traceback on error")

    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_key(p):
        p.add_argument(
            "--keyfile",
            "-k",
            help=f"path to the encrypted keystore (defaults to {DEFAULT_ETH_KEYFILE})",
        )
        p.add_argument("--password", help="keystore password (defaults to a hidden prompt)")
        p.add_argument("--password-stdin", action="store_true", help="read password from standard input")

    def add_rpc(p):
        p.add_argument(
            "--rpc-url",
            "-r",
            help="Ethereum JSON-RPC endpoint URL (defaults to CONFAM_RPC_URL or http://127.0.0.1:8545)",
        )

    # create
    p = sub.add_parser("create", help="generate a new key locally and save an encrypted keystore")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"destination path for keystore (defaults to {DEFAULT_ETH_KEYFILE})",
    )
    p.add_argument("--password", help="keystore password (defaults to a hidden prompt)")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--force", "-f", action="store_true", help="overwrite existing keyfile")
    p.set_defaults(func=cmd_create)

    # import-key
    p = sub.add_parser("import-key", help="import an existing private key into an encrypted keystore")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"destination path for keystore (defaults to {DEFAULT_ETH_KEYFILE})",
    )
    p.add_argument("--private-key", help="private key hex (omit for hidden prompt)")
    p.add_argument("--password")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--force", "-f", action="store_true", help="overwrite existing keyfile")
    p.set_defaults(func=cmd_import_key)

    # export-key
    p = sub.add_parser("export-key", help="export private key in hex")
    add_common_key(p)
    p.add_argument("--yes", "-y", action="store_true", help="skip confirmation warning")
    p.set_defaults(func=cmd_export_key)

    # address
    p = sub.add_parser("address", help="print the checksum address for a keystore")
    add_common_key(p)
    p.set_defaults(func=cmd_address)

    # balance
    p = sub.add_parser("balance", help="print the account balance in wei and ETH")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"keystore path (defaults to {DEFAULT_ETH_KEYFILE})",
    )
    p.add_argument("--address", "-a", help="arbitrary address to check")
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    add_rpc(p)
    p.set_defaults(func=cmd_balance)

    # chain-info
    p = sub.add_parser("chain-info", help="print connected network status, block number, and fees")
    add_rpc(p)
    p.set_defaults(func=cmd_chain_info)

    # gas-price
    p = sub.add_parser("gas-price", help="query network fee market")
    add_rpc(p)
    p.set_defaults(func=cmd_gas_price)

    # sign-message
    p = sub.add_parser("sign-message", help="sign a message locally (EIP-191 personal_sign)")
    add_common_key(p)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_sign_message)

    # verify-message
    p = sub.add_parser("verify-message", help="recover the signer of a message and compare it to an address")
    p.add_argument("--address", required=True)
    p.add_argument("--signature", required=True)
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_verify_message)

    # send-tx
    p = sub.add_parser("send-tx", help="build, sign locally, and broadcast an ETH transfer")
    add_common_key(p)
    p.add_argument("--to", required=True, help="recipient address")
    p.add_argument("--amount", required=True, help="amount like '0.01 ether' or '1234567 gwei'")
    p.add_argument("--data", help="optional hex data")
    p.add_argument("--gas-limit", type=int, help="optional gas limit")
    p.add_argument("--wait", "-w", action="store_true", help="wait for transaction receipt")
    p.add_argument("--timeout", type=int, default=120, help="timeout in seconds")
    add_rpc(p)
    p.set_defaults(func=cmd_send_tx)

    # token-balance
    p = sub.add_parser("token-balance", help="query ERC-20 token balance")
    p.add_argument("--token", "-t", required=True, help="ERC-20 token contract address")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"keystore path (defaults to {DEFAULT_ETH_KEYFILE})",
    )
    p.add_argument("--address", "-a", help="wallet address to check")
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    add_rpc(p)
    p.set_defaults(func=cmd_token_balance)

    # transfer-token
    p = sub.add_parser("transfer-token", help="transfer ERC-20 tokens")
    add_common_key(p)
    p.add_argument("--token", "-t", required=True, help="ERC-20 token contract address")
    p.add_argument("--to", required=True, help="recipient address")
    p.add_argument("--amount", required=True, help="token amount in human units (e.g. '10.5')")
    p.add_argument("--gas-limit", type=int, help="optional gas limit")
    p.add_argument("--wait", "-w", action="store_true", help="wait for receipt confirmation")
    p.add_argument("--timeout", type=int, default=120, help="timeout in seconds for receipt")
    add_rpc(p)
    p.set_defaults(func=cmd_transfer_token)

    # receipt
    p = sub.add_parser("receipt", help="query transaction receipt by hash")
    p.add_argument("--tx-hash", required=True, help="transaction hash")
    add_rpc(p)
    p.set_defaults(func=cmd_receipt)

    # sign-tx (offline)
    p = sub.add_parser("sign-tx", help="offline transaction signing (air-gapped wallet)")
    add_common_key(p)
    p.add_argument("--to", required=True, help="recipient address")
    p.add_argument("--amount", required=True, help="amount in ether/gwei/wei")
    p.add_argument("--nonce", type=int, required=True, help="account transaction nonce")
    p.add_argument("--chain-id", type=int, required=True, help="target network Chain ID")
    p.add_argument("--gas-limit", type=int, default=21000, help="gas limit")
    p.add_argument("--max-fee", type=int, help="max fee per gas in wei (EIP-1559)")
    p.add_argument("--priority-fee", type=int, help="priority fee per gas in wei (EIP-1559)")
    p.add_argument("--gas-price", type=int, help="legacy gas price in wei")
    p.add_argument("--data", help="optional hex data")
    p.set_defaults(func=cmd_sign_tx)

    # broadcast-tx
    p = sub.add_parser("broadcast-tx", help="broadcast pre-signed raw transaction hex")
    p.add_argument("--raw-tx", required=True, help="signed raw transaction hex")
    p.add_argument("--wait", "-w", action="store_true", help="wait for transaction receipt")
    p.add_argument("--timeout", type=int, default=120, help="timeout in seconds for receipt")
    add_rpc(p)
    p.set_defaults(func=cmd_broadcast_tx)

    # Register Solana commands
    register_solana_subparser(sub)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except ConfamError as exc:
        if getattr(args, "debug", False):
            raise
        raise SystemExit(f"error: {exc}")
    except KeyboardInterrupt:
        raise SystemExit("\nInterrupted.")

