"""Solana CLI subcommands for Confam Wallet."""

import argparse
import getpass
import json
import os
import sys
from typing import Optional

from confam.errors import ConfamError, KeystoreError, ValidationError
from confam.keystore import resolve_password
from confam.solana.base58 import b58decode, b58encode
from confam.solana.keypair import SolanaKeypair
from confam.solana.keystore import (
    create_solana_wallet,
    export_solana_key,
    import_solana_key,
    unlock_solana_keystore,
)
from confam.solana.rpc import SolanaRpcClient
from confam.solana.spl import (
    build_spl_transfer_instruction,
    get_all_spl_tokens,
    get_spl_balance,
)
from confam.solana.tx import (
    build_sol_transfer_instruction,
    sign_and_serialize_transaction,
    wait_for_solana_signature,
)
from confam.solana.units import (
    format_lamports,
    format_spl_amount,
    parse_sol_amount,
    parse_spl_amount,
)

DEFAULT_CONFAM_DIR = os.path.expanduser("~/.confam")
DEFAULT_SOLANA_KEYFILE = os.path.join(DEFAULT_CONFAM_DIR, "solana.json")


def _get_solana_rpc(args) -> SolanaRpcClient:
    rpc_url = getattr(args, "rpc_url", None)
    return SolanaRpcClient(endpoint_url=rpc_url)


def _resolve_solana_keyfile(args, for_creation: bool = False) -> str:
    kf = getattr(args, "keyfile", None)
    if kf:
        return os.path.abspath(kf)
    env_kf = os.environ.get("CONFAM_SOLANA_KEYFILE")
    if env_kf:
        return os.path.abspath(env_kf)
    if not for_creation and not os.path.exists(DEFAULT_SOLANA_KEYFILE):
        raise KeystoreError(
            f"No Solana wallet found at default path '{DEFAULT_SOLANA_KEYFILE}'. "
            f"Run 'confam solana create' first or pass --keyfile."
        )
    return DEFAULT_SOLANA_KEYFILE


def cmd_solana_create(args) -> int:
    keyfile = _resolve_solana_keyfile(args, for_creation=True)
    password = resolve_password(args, prompt="Choose a keystore password: ", confirm=True)
    keypair, _ = create_solana_wallet(keyfile, password, force=args.force)
    print(f"created:  {keypair.address}")
    print(f"keyfile:  {keyfile}")
    print("Security: Solana Ed25519 key generated locally. Back up your keyfile and password.")
    return 0


def cmd_solana_import(args) -> int:
    keyfile = _resolve_solana_keyfile(args, for_creation=True)
    key_input = args.private_key
    if not key_input:
        key_input = getpass.getpass("Enter Solana private key (Base58 or [1,2,...] JSON): ")
        if not key_input:
            raise ValidationError("Empty private key")

    password = resolve_password(args, prompt="Choose a keystore password: ", confirm=True)
    keypair, _ = import_solana_key(key_input, keyfile, password, force=args.force)
    print(f"imported: {keypair.address}")
    print(f"keyfile:  {keyfile}")
    return 0


def cmd_solana_export(args) -> int:
    keyfile = _resolve_solana_keyfile(args)
    if not args.yes:
        confirm = input(f"WARNING: Exporting key from {keyfile} exposes all funds. Continue? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Export cancelled.")
            return 1

    password = resolve_password(args)
    keypair = unlock_solana_keystore(keyfile, password)
    if args.json:
        print(f"private_key: {json.dumps(keypair.to_json_array())}")
    else:
        print(f"private_key: {keypair.to_base58()}")
    return 0


def cmd_solana_address(args) -> int:
    keyfile = _resolve_solana_keyfile(args)
    password = resolve_password(args)
    keypair = unlock_solana_keystore(keyfile, password)
    print(keypair.address)
    return 0


def cmd_solana_balance(args) -> int:
    rpc = _get_solana_rpc(args)
    if args.address:
        target_addr = args.address.strip()
    else:
        keyfile = _resolve_solana_keyfile(args)
        password = resolve_password(args)
        keypair = unlock_solana_keystore(keyfile, password)
        target_addr = keypair.address

    lamports = rpc.get_balance(target_addr)
    print(f"address:  {target_addr}")
    print(f"balance:  {lamports} lamports")
    print(f"          {format_lamports(lamports)} SOL")
    return 0


def cmd_solana_status(args) -> int:
    rpc = _get_solana_rpc(args)
    slot = rpc.get_slot()
    version = rpc.get_version()
    blockhash, _ = rpc.get_latest_blockhash()

    print(f"rpc:        {rpc.endpoint_url}")
    print(f"version:    {version}")
    print(f"slot:       {slot}")
    print(f"blockhash:  {blockhash}")
    return 0


def cmd_solana_sign_message(args) -> int:
    keyfile = _resolve_solana_keyfile(args)
    password = resolve_password(args)
    keypair = unlock_solana_keystore(keyfile, password)
    sig_bytes = keypair.sign(args.message.encode("utf-8"))
    sig_b58 = b58encode(sig_bytes)
    print(sig_b58)
    print(
        f"verify: confam solana verify-message --address {keypair.address} "
        f"--signature {sig_b58} --message '{args.message}'"
    )
    return 0


def cmd_solana_verify_message(args) -> int:
    pub_bytes = b58decode(args.address.strip())
    sig_bytes = b58decode(args.signature.strip())
    msg_bytes = args.message.encode("utf-8")

    ok = SolanaKeypair.verify(pub_bytes, msg_bytes, sig_bytes)
    print(f"signer: {args.address}")
    print("valid" if ok else "INVALID: signature does not match address")
    return 0 if ok else 1


def cmd_solana_send(args) -> int:
    keyfile = _resolve_solana_keyfile(args)
    lamports = parse_sol_amount(args.amount)
    password = resolve_password(args)
    keypair = unlock_solana_keystore(keyfile, password)
    rpc = _get_solana_rpc(args)

    to_bytes = b58decode(args.to.strip())
    if len(to_bytes) != 32:
        raise ValidationError(f"Invalid recipient address: '{args.to}'")

    sender_lamports = rpc.get_balance(keypair.address)
    fee_estimate = 5000
    if sender_lamports < lamports + fee_estimate:
        raise ValidationError(
            f"Insufficient balance: account has {format_lamports(sender_lamports)} SOL, "
            f"needs {format_lamports(lamports + fee_estimate)} SOL (amount + 5000 lamports fee)"
        )

    blockhash, _ = rpc.get_latest_blockhash()
    transfer_ix = build_sol_transfer_instruction(keypair.public_key_bytes, to_bytes, lamports)
    wire_tx = sign_and_serialize_transaction(keypair, [transfer_ix], blockhash)

    sig = rpc.send_transaction(wire_tx)
    print(f"signature: {sig}")
    print(f"from:      {keypair.address}")
    print(f"to:        {args.to.strip()}")
    print(f"amount:    {lamports} lamports ({format_lamports(lamports)} SOL)")

    if args.wait:
        print("Waiting for confirmation on Solana...")
        status = wait_for_solana_signature(rpc, sig, timeout=args.timeout)
        print(f"status:    CONFIRMED ({status.get('confirmationStatus', 'confirmed')})")
        if "slot" in status:
            print(f"slot:      {status['slot']}")

    return 0


def cmd_solana_token_balance(args) -> int:
    rpc = _get_solana_rpc(args)
    if args.address:
        target_addr = args.address.strip()
    else:
        keyfile = _resolve_solana_keyfile(args)
        password = resolve_password(args)
        keypair = unlock_solana_keystore(keyfile, password)
        target_addr = keypair.address

    mint = args.mint.strip()
    raw, decimals, formatted = get_spl_balance(rpc, target_addr, mint)
    print(f"mint:     {mint}")
    print(f"owner:    {target_addr}")
    print(f"decimals: {decimals}")
    print(f"balance:  {raw} raw units")
    print(f"          {formatted} tokens")
    return 0


def cmd_solana_tokens(args) -> int:
    rpc = _get_solana_rpc(args)
    if args.address:
        target_addr = args.address.strip()
    else:
        keyfile = _resolve_solana_keyfile(args)
        password = resolve_password(args)
        keypair = unlock_solana_keystore(keyfile, password)
        target_addr = keypair.address

    tokens = get_all_spl_tokens(rpc, target_addr)
    print(f"SPL Tokens for {target_addr}:")
    if not tokens:
        print("  (no token accounts found)")
        return 0

    for idx, t in enumerate(tokens, 1):
        print(f"[{idx}] Mint:    {t['mint']}")
        print(f"    Account: {t['token_account']}")
        print(f"    Balance: {t['amount']} (raw: {t['raw_amount']})")
    return 0


def cmd_solana_transfer_token(args) -> int:
    keyfile = _resolve_solana_keyfile(args)
    rpc = _get_solana_rpc(args)
    password = resolve_password(args)
    keypair = unlock_solana_keystore(keyfile, password)

    source_token_acc = b58decode(args.source.strip())
    dest_token_acc = b58decode(args.to.strip())
    raw_amount = parse_spl_amount(args.amount, args.decimals)

    transfer_ix = build_spl_transfer_instruction(
        source_token_account=source_token_acc,
        destination_token_account=dest_token_acc,
        owner=keypair.public_key_bytes,
        amount_raw=raw_amount,
    )

    blockhash, _ = rpc.get_latest_blockhash()
    wire_tx = sign_and_serialize_transaction(keypair, [transfer_ix], blockhash)

    sig = rpc.send_transaction(wire_tx)
    print(f"signature: {sig}")
    print(f"from:      {args.source.strip()}")
    print(f"to:        {args.to.strip()}")
    print(f"amount:    {raw_amount} (ui: {format_spl_amount(raw_amount, args.decimals)})")

    if args.wait:
        print("Waiting for confirmation on Solana...")
        status = wait_for_solana_signature(rpc, sig, timeout=args.timeout)
        print(f"status:    CONFIRMED ({status.get('confirmationStatus', 'confirmed')})")

    return 0


def register_solana_subparser(subparsers):
    """Register 'solana' subcommand and its nested operations."""
    sol_parser = subparsers.add_parser("solana", help="Solana (SOL & SPL token) commands")
    sol_sub = sol_parser.add_subparsers(dest="solana_command", required=True)

    def add_common_key(p):
        p.add_argument(
            "--keyfile",
            "-k",
            help=f"path to encrypted Solana keystore (defaults to {DEFAULT_SOLANA_KEYFILE})",
        )
        p.add_argument("--password", help="keystore password")
        p.add_argument("--password-stdin", action="store_true", help="read password from stdin")

    def add_rpc(p):
        p.add_argument(
            "--rpc-url",
            "-r",
            help="Solana JSON-RPC URL (defaults to CONFAM_SOLANA_RPC_URL or https://api.mainnet-beta.solana.com)",
        )

    # create
    p = sol_sub.add_parser("create", help="generate a new Solana Ed25519 keypair and encrypted keystore")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"destination path for keystore (defaults to {DEFAULT_SOLANA_KEYFILE})",
    )
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--force", "-f", action="store_true", help="overwrite existing keystore")
    p.set_defaults(func=cmd_solana_create)

    # import-key
    p = sol_sub.add_parser("import-key", help="import Solana private key (Base58 or [1,2,...] JSON)")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"destination path for keystore (defaults to {DEFAULT_SOLANA_KEYFILE})",
    )
    p.add_argument("--private-key", help="Solana private key string")
    p.add_argument("--password")
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--force", "-f", action="store_true")
    p.set_defaults(func=cmd_solana_import)

    # export-key
    p = sol_sub.add_parser("export-key", help="export Solana private key")
    add_common_key(p)
    p.add_argument("--json", action="store_true", help="export as Solana CLI JSON array [1,2,...]")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(func=cmd_solana_export)

    # address
    p = sol_sub.add_parser("address", help="print Base58 address for Solana keystore")
    add_common_key(p)
    p.set_defaults(func=cmd_solana_address)

    # balance
    p = sol_sub.add_parser("balance", help="query SOL balance")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"Solana keystore path (defaults to {DEFAULT_SOLANA_KEYFILE})",
    )
    p.add_argument("--address", "-a", help="Solana Base58 address to check")
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_balance)

    # status
    p = sol_sub.add_parser("status", help="query Solana network slot, version, and blockhash")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_status)

    # sign-message
    p = sol_sub.add_parser("sign-message", help="sign text with Ed25519")
    add_common_key(p)
    p.add_argument("--message", "-m", required=True)
    p.set_defaults(func=cmd_solana_sign_message)

    # verify-message
    p = sol_sub.add_parser("verify-message", help="verify Ed25519 signature")
    p.add_argument("--address", "-a", required=True)
    p.add_argument("--signature", "-s", required=True)
    p.add_argument("--message", "-m", required=True)
    p.set_defaults(func=cmd_solana_verify_message)

    # send
    p = sol_sub.add_parser("send", help="send native SOL transfer")
    add_common_key(p)
    p.add_argument("--to", required=True, help="recipient Solana Base58 address")
    p.add_argument("--amount", required=True, help="amount, e.g. '0.5 sol' or '500000000 lamports'")
    p.add_argument("--wait", "-w", action="store_true", help="wait for confirmation")
    p.add_argument("--timeout", type=int, default=60, help="timeout in seconds")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_send)

    # token-balance
    p = sol_sub.add_parser("token-balance", help="query SPL token balance for a mint")
    p.add_argument("--mint", "-m", required=True, help="SPL token mint address")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"Solana keystore path (defaults to {DEFAULT_SOLANA_KEYFILE})",
    )
    p.add_argument("--address", "-a", help="Solana owner address")
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_token_balance)

    # tokens
    p = sol_sub.add_parser("tokens", help="list all SPL tokens in wallet")
    p.add_argument(
        "--keyfile",
        "-k",
        help=f"Solana keystore path (defaults to {DEFAULT_SOLANA_KEYFILE})",
    )
    p.add_argument("--address", "-a", help="Solana owner address")
    p.add_argument("--password", help="keystore password")
    p.add_argument("--password-stdin", action="store_true")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_tokens)

    # transfer-token
    p = sol_sub.add_parser("transfer-token", help="transfer SPL tokens between token accounts")
    add_common_key(p)
    p.add_argument("--source", required=True, help="source SPL token account address")
    p.add_argument("--to", required=True, help="destination SPL token account address")
    p.add_argument("--amount", required=True, help="token amount in human units (e.g. '10.5')")
    p.add_argument("--decimals", type=int, default=6, help="token decimals (default: 6 for USDC/USDT)")
    p.add_argument("--wait", "-w", action="store_true", help="wait for confirmation")
    p.add_argument("--timeout", type=int, default=60, help="timeout in seconds")
    add_rpc(p)
    p.set_defaults(func=cmd_solana_transfer_token)

    return sol_parser

