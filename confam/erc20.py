"""ERC-20 token support for balances and transfers."""

from typing import Dict, Tuple

from eth_abi import decode, encode
from eth_utils import function_signature_to_4byte_selector, to_checksum_address

from confam.errors import TransactionError, ValidationError
from confam.rpc import RpcClient
from confam.tx import validate_address
from confam.units import format_token_amount, parse_token_amount

ERC20_SELECTORS = {
    "name": function_signature_to_4byte_selector("name()"),
    "symbol": function_signature_to_4byte_selector("symbol()"),
    "decimals": function_signature_to_4byte_selector("decimals()"),
    "balanceOf": function_signature_to_4byte_selector("balanceOf(address)"),
    "transfer": function_signature_to_4byte_selector("transfer(address,uint256)"),
}


def _hex_call(rpc: RpcClient, contract: str, data_bytes: bytes) -> str:
    hex_str = "0x" + data_bytes.hex()
    return rpc.eth_call(contract, hex_str)


def get_token_metadata(rpc: RpcClient, token_address: str) -> Dict[str, any]:
    """Retrieve ERC-20 metadata (symbol, name, decimals)."""
    contract = validate_address(token_address)
    metadata = {"address": contract, "symbol": "TOKEN", "name": "ERC20 Token", "decimals": 18}

    # Fetch decimals
    try:
        raw_decimals = _hex_call(rpc, contract, ERC20_SELECTORS["decimals"])
        if raw_decimals and raw_decimals != "0x":
            metadata["decimals"] = decode(["uint8"], bytes.fromhex(raw_decimals[2:]))[0]
    except Exception:
        pass

    # Fetch symbol
    try:
        raw_symbol = _hex_call(rpc, contract, ERC20_SELECTORS["symbol"])
        if raw_symbol and raw_symbol != "0x":
            try:
                metadata["symbol"] = decode(["string"], bytes.fromhex(raw_symbol[2:]))[0]
            except Exception:
                # Some old tokens like MKR returned bytes32 instead of string
                metadata["symbol"] = decode(["bytes32"], bytes.fromhex(raw_symbol[2:]))[0].decode("utf-8").strip("\x00")
    except Exception:
        pass

    # Fetch name
    try:
        raw_name = _hex_call(rpc, contract, ERC20_SELECTORS["name"])
        if raw_name and raw_name != "0x":
            try:
                metadata["name"] = decode(["string"], bytes.fromhex(raw_name[2:]))[0]
            except Exception:
                metadata["name"] = decode(["bytes32"], bytes.fromhex(raw_name[2:]))[0].decode("utf-8").strip("\x00")
    except Exception:
        pass

    return metadata


def get_token_balance(rpc: RpcClient, token_address: str, wallet_address: str) -> Tuple[int, Dict[str, any]]:
    """Query ERC-20 token balance for a given address."""
    contract = validate_address(token_address)
    owner = validate_address(wallet_address)
    metadata = get_token_metadata(rpc, contract)

    call_data = ERC20_SELECTORS["balanceOf"] + encode(["address"], [owner])
    res = _hex_call(rpc, contract, call_data)

    if not res or res == "0x":
        raw_balance = 0
    else:
        raw_balance = decode(["uint256"], bytes.fromhex(res[2:]))[0]

    return raw_balance, metadata


def build_erc20_transfer_data(recipient: str, amount_raw: int) -> str:
    """Build the transaction calldata for ERC-20 transfer(address,uint256)."""
    to_addr = validate_address(recipient)
    if amount_raw < 0:
        raise ValidationError("Amount cannot be negative")

    data = ERC20_SELECTORS["transfer"] + encode(["address", "uint256"], [to_addr, amount_raw])
    return "0x" + data.hex()

