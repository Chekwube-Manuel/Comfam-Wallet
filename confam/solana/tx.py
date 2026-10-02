"""Solana wire transaction builder, message compiler, and serializer."""

import struct
import time
from typing import Dict, List, Optional, Tuple, Union

from confam.errors import TransactionError, ValidationError
from confam.solana.base58 import b58decode, b58encode
from confam.solana.keypair import SolanaKeypair
from confam.solana.rpc import SolanaRpcClient

SYSTEM_PROGRAM_ID = b58decode("11111111111111111111111111111111")
TOKEN_PROGRAM_ID = b58decode("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")


def encode_compact_u16(n: int) -> bytes:
    """Encode integer using Solana's compact-u16 format."""
    if n < 0:
        raise ValidationError("Compact-u16 cannot be negative")
    out = bytearray()
    while True:
        elem = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(elem)
            break
        else:
            elem |= 0x80
            out.append(elem)
    return bytes(out)


class AccountMeta:
    """Account metadata for instructions."""

    def __init__(self, pubkey: bytes, is_signer: bool, is_writable: bool):
        if len(pubkey) != 32:
            raise ValidationError(f"Public key must be 32 bytes, got {len(pubkey)}")
        self.pubkey = bytes(pubkey)
        self.is_signer = is_signer
        self.is_writable = is_writable


class Instruction:
    """Solana instruction representation."""

    def __init__(self, program_id: bytes, accounts: List[AccountMeta], data: bytes):
        if len(program_id) != 32:
            raise ValidationError(f"Program ID must be 32 bytes, got {len(program_id)}")
        self.program_id = bytes(program_id)
        self.accounts = accounts
        self.data = bytes(data)


def build_sol_transfer_instruction(
    from_pubkey: bytes, to_pubkey: bytes, lamports: int
) -> Instruction:
    """Construct standard SystemProgram Transfer instruction."""
    if lamports < 0:
        raise ValidationError("Lamports cannot be negative")

    # Instruction index 2 (Transfer) + uint64 little-endian lamports
    data = struct.pack("<IQ", 2, lamports)
    accounts = [
        AccountMeta(from_pubkey, is_signer=True, is_writable=True),
        AccountMeta(to_pubkey, is_signer=False, is_writable=True),
    ]
    return Instruction(SYSTEM_PROGRAM_ID, accounts, data)


def compile_message(
    payer: bytes, instructions: List[Instruction], recent_blockhash_b58: str
) -> Tuple[bytes, List[bytes]]:
    """Compile instructions and account keys into a binary Solana message."""
    blockhash_bytes = b58decode(recent_blockhash_b58)
    if len(blockhash_bytes) != 32:
        raise ValidationError(f"Blockhash must be 32 bytes, got {len(blockhash_bytes)}")

    # 1. Collect all account keys and determine their roles
    # We maintain order: writable signers, readonly signers, writable non-signers, readonly non-signers
    writable_signers = [payer]
    readonly_signers = []
    writable_non_signers = []
    readonly_non_signers = []

    def add_account(pubkey: bytes, is_signer: bool, is_writable: bool):
        if is_signer:
            if is_writable:
                if pubkey not in writable_signers:
                    writable_signers.append(pubkey)
            else:
                if pubkey not in readonly_signers and pubkey not in writable_signers:
                    readonly_signers.append(pubkey)
        else:
            if is_writable:
                if pubkey not in writable_non_signers and pubkey not in writable_signers:
                    writable_non_signers.append(pubkey)
            else:
                if (
                    pubkey not in readonly_non_signers
                    and pubkey not in writable_non_signers
                    and pubkey not in readonly_signers
                    and pubkey not in writable_signers
                ):
                    readonly_non_signers.append(pubkey)

    for ix in instructions:
        for acc in ix.accounts:
            add_account(acc.pubkey, acc.is_signer, acc.is_writable)
        # Program ID is always a readonly non-signer
        add_account(ix.program_id, is_signer=False, is_writable=False)

    all_accounts = (
        writable_signers + readonly_signers + writable_non_signers + readonly_non_signers
    )
    account_map = {acc: idx for idx, acc in enumerate(all_accounts)}

    # 2. Build Message Header
    num_required_signatures = len(writable_signers) + len(readonly_signers)
    num_readonly_signed_accounts = len(readonly_signers)
    num_readonly_unsigned_accounts = len(readonly_non_signers)
    header = bytes(
        [
            num_required_signatures,
            num_readonly_signed_accounts,
            num_readonly_unsigned_accounts,
        ]
    )

    # 3. Accounts array
    accounts_payload = encode_compact_u16(len(all_accounts)) + b"".join(all_accounts)

    # 4. Instructions payload
    compiled_ixs = bytearray()
    compiled_ixs.extend(encode_compact_u16(len(instructions)))
    for ix in instructions:
        prog_idx = account_map[ix.program_id]
        acc_indices = bytes([account_map[acc.pubkey] for acc in ix.accounts])
        compiled_ixs.append(prog_idx)
        compiled_ixs.extend(encode_compact_u16(len(acc_indices)))
        compiled_ixs.extend(acc_indices)
        compiled_ixs.extend(encode_compact_u16(len(ix.data)))
        compiled_ixs.extend(ix.data)

    message = header + accounts_payload + blockhash_bytes + bytes(compiled_ixs)
    return message, all_accounts


def sign_and_serialize_transaction(
    keypair: SolanaKeypair, instructions: List[Instruction], recent_blockhash_b58: str
) -> bytes:
    """Compile message, sign with keypair, and serialize into wire transaction bytes."""
    message, _ = compile_message(keypair.public_key_bytes, instructions, recent_blockhash_b58)
    signature = keypair.sign(message)

    # Wire Transaction: compact-u16(1) + signature(64) + message
    wire = encode_compact_u16(1) + signature + message
    return wire


def wait_for_solana_signature(
    rpc: SolanaRpcClient,
    signature_b58: str,
    timeout: int = 60,
    poll_interval: float = 2.0,
) -> dict:
    """Poll Solana RPC until transaction signature is confirmed."""
    start_time = time.time()
    while True:
        status_info = rpc.get_signature_status(signature_b58)
        if status_info is not None:
            err = status_info.get("err")
            if err:
                raise TransactionError(f"Solana transaction failed on-chain: {err}")
            confirmations = status_info.get("confirmations")
            status_str = status_info.get("confirmationStatus", "processed")
            if status_str in ("confirmed", "finalized") or (confirmations is not None and confirmations > 0):
                return status_info

        if time.time() - start_time > timeout:
            raise TransactionError(
                f"Transaction {signature_b58} was not confirmed within {timeout} seconds."
            )

        time.sleep(poll_interval)

