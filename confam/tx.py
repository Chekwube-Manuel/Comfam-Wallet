"""Ethereum transaction construction, signing, validation, pre-flight checks, and receipt polling."""

import time
from typing import Any, Dict, Optional

from eth_account import Account
from eth_utils import is_address, is_checksum_address, to_checksum_address

from confam.errors import TransactionError, ValidationError
from confam.rpc import RpcClient
from confam.units import format_wei


def validate_address(address: str) -> str:
    """Validate Ethereum address and return normalized checksum representation."""
    if not isinstance(address, str):
        raise ValidationError(f"Address must be a string, got {type(address).__name__}")

    raw = address.strip()
    if not is_address(raw):
        raise ValidationError(f"Invalid Ethereum address: '{address}'")

    return to_checksum_address(raw)


def build_transaction(
    rpc: RpcClient,
    from_addr: str,
    to: str,
    value_wei: int,
    data: str = "",
    gas_limit: Optional[int] = None,
    nonce: Optional[int] = None,
    chain_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Construct an EIP-1559 or Legacy transaction dictionary with pre-flight balance checks."""
    from_checksum = validate_address(from_addr)
    to_checksum = validate_address(to)

    if chain_id is None:
        chain_id = rpc.get_chain_id()

    if nonce is None:
        nonce = rpc.get_transaction_count(from_checksum, "pending")

    clean_data = data
    if clean_data and not clean_data.startswith("0x"):
        clean_data = "0x" + clean_data

    tx: Dict[str, Any] = {
        "from": from_checksum,
        "to": to_checksum,
        "value": value_wei,
        "nonce": nonce,
        "chainId": chain_id,
    }
    if clean_data:
        tx["data"] = clean_data

    # Determine Gas Pricing (EIP-1559 vs Legacy)
    latest_block = rpc.get_block_by_number("latest", False)
    base_fee_hex = latest_block.get("baseFeePerGas")

    if base_fee_hex is not None:
        base_fee = int(base_fee_hex, 16) if isinstance(base_fee_hex, str) else int(base_fee_hex)
        suggested_priority = rpc.max_priority_fee_per_gas()
        if suggested_priority is not None and suggested_priority > 0:
            priority_fee = suggested_priority
        else:
            # Safe default priority fee: 1.5 Gwei or base_fee if higher
            priority_fee = max(1_500_000_000, min(base_fee, 2_000_000_000)) if base_fee > 0 else 1_000_000_000

        max_fee = (base_fee * 2) + priority_fee
        tx["maxFeePerGas"] = max_fee
        tx["maxPriorityFeePerGas"] = priority_fee
        tx["type"] = "0x2"
        effective_price = max_fee
    else:
        gas_price = rpc.gas_price()
        tx["gasPrice"] = gas_price
        effective_price = gas_price

    # Estimate Gas
    if gas_limit is not None:
        tx["gas"] = gas_limit
    else:
        estimate_payload = {
            "from": from_checksum,
            "to": to_checksum,
            "value": hex(value_wei),
        }
        if clean_data:
            estimate_payload["data"] = clean_data

        try:
            estimated = rpc.estimate_gas(estimate_payload)
            # Add a 15% buffer for safety on contract interactions, min 21000
            tx["gas"] = max(21000, int(estimated * 1.15))
        except Exception as exc:
            # If standard simple transfer without data, default to 21000
            if not clean_data or clean_data == "0x":
                tx["gas"] = 21000
            else:
                raise TransactionError(f"Gas estimation failed: {exc}") from exc

    # Pre-flight balance validation
    sender_balance = rpc.get_balance(from_checksum)
    max_cost = value_wei + (tx["gas"] * effective_price)
    if sender_balance < max_cost:
        raise TransactionError(
            f"Insufficient funds: account balance is {format_wei(sender_balance)} ETH ({sender_balance} wei), "
            f"but total required is {format_wei(max_cost)} ETH (value: {format_wei(value_wei)} ETH + max gas: {format_wei(max_cost - value_wei)} ETH)"
        )

    return tx


def sign_transaction(account: Account, tx_dict: Dict[str, Any]) -> str:
    """Sign a transaction dictionary with local account and return raw transaction hex."""
    tx_to_sign = dict(tx_dict)
    signed = account.sign_transaction(tx_to_sign)
    raw = getattr(signed, "raw_transaction", None)
    if raw is None:
        raw = signed.rawTransaction

    if isinstance(raw, str):
        return raw if raw.startswith("0x") else "0x" + raw
    return "0x" + bytes(raw).hex()


def wait_for_receipt(
    rpc: RpcClient,
    tx_hash: str,
    timeout: int = 120,
    poll_interval: float = 2.0,
) -> dict:
    """Poll for transaction inclusion until receipt is available or timeout expires."""
    clean_hash = tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash
    start_time = time.time()

    while True:
        receipt = rpc.get_transaction_receipt(clean_hash)
        if receipt is not None:
            return receipt

        if time.time() - start_time > timeout:
            raise TransactionError(
                f"Transaction {clean_hash} was not mined within {timeout} seconds. "
                "It may still confirm on-chain later."
            )

        time.sleep(poll_interval)

