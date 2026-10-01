"""SPL Token operations for Solana (balances, metadata, and transfers)."""

import struct
from typing import Dict, List, Optional, Tuple

from confam.errors import TransactionError, ValidationError
from confam.solana.base58 import b58decode, b58encode
from confam.solana.rpc import SolanaRpcClient
from confam.solana.tx import AccountMeta, Instruction, TOKEN_PROGRAM_ID


def build_spl_transfer_instruction(
    source_token_account: bytes,
    destination_token_account: bytes,
    owner: bytes,
    amount_raw: int,
) -> Instruction:
    """Build standard SPL Token transfer instruction (type 3)."""
    if len(source_token_account) != 32 or len(destination_token_account) != 32 or len(owner) != 32:
        raise ValidationError("Account public keys must be 32 bytes")

    if amount_raw < 0:
        raise ValidationError("Token amount cannot be negative")

    # Instruction index 3 (Transfer) + uint64 little-endian amount
    data = struct.pack("<BQ", 3, amount_raw)
    accounts = [
        AccountMeta(source_token_account, is_signer=False, is_writable=True),
        AccountMeta(destination_token_account, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=True, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, accounts, data)


def get_spl_balance(
    rpc: SolanaRpcClient, owner_b58: str, mint_b58: str
) -> Tuple[int, int, str]:
    """Retrieve token balance for a specific mint owned by owner.

    Returns (raw_amount, decimals, ui_amount_string).
    """
    accounts = rpc.get_token_accounts_by_owner(owner_b58, mint_b58)
    if not accounts:
        # Check decimals from mint supply
        supply_info = rpc.get_token_supply(mint_b58)
        decimals = supply_info.get("decimals", 0)
        return 0, decimals, "0"

    total_raw = 0
    decimals = 0
    for acc in accounts:
        parsed_info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        token_amt = parsed_info.get("tokenAmount", {})
        total_raw += int(token_amt.get("amount", 0))
        decimals = int(token_amt.get("decimals", decimals))

    from confam.solana.units import format_spl_amount
    return total_raw, decimals, format_spl_amount(total_raw, decimals)


def get_all_spl_tokens(rpc: SolanaRpcClient, owner_b58: str) -> List[Dict[str, any]]:
    """Retrieve all SPL token accounts and their balances for a given owner."""
    accounts = rpc.get_token_accounts_by_owner(owner_b58)
    results = []

    for acc in accounts:
        pubkey = acc.get("pubkey")
        parsed_info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        mint = parsed_info.get("mint")
        token_amt = parsed_info.get("tokenAmount", {})
        raw_amt = int(token_amt.get("amount", 0))
        decimals = int(token_amt.get("decimals", 0))
        ui_amt = token_amt.get("uiAmountString", "0")

        results.append(
            {
                "token_account": pubkey,
                "mint": mint,
                "raw_amount": raw_amt,
                "decimals": decimals,
                "amount": ui_amt,
            }
        )

    return results
