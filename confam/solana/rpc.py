"""Solana JSON-RPC 2.0 client."""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

from confam.errors import RpcError
from confam.solana.base58 import b58decode, b58encode

DEFAULT_SOLANA_RPC = "https://api.mainnet-beta.solana.com"


class SolanaRpcClient:
    """Production client for Solana JSON-RPC 2.0 nodes."""

    def __init__(self, endpoint_url: Optional[str] = None, timeout: int = 30):
        self.endpoint_url = endpoint_url or os.environ.get("CONFAM_SOLANA_RPC_URL") or DEFAULT_SOLANA_RPC
        self.timeout = timeout
        self._request_id = 1

    def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Perform a JSON-RPC 2.0 call to the Solana RPC node."""
        if params is None:
            params = []

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._request_id += 1

        encoded = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ConfamWallet-Solana/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_response = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                err_json = json.loads(body)
                if "error" in err_json:
                    raise RpcError(f"Solana RPC HTTP {exc.code} error: {err_json['error']}") from exc
            except Exception:
                pass
            raise RpcError(f"HTTP {exc.code} connecting to Solana RPC at {self.endpoint_url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RpcError(f"Cannot reach Solana RPC at '{self.endpoint_url}': {exc.reason}") from exc
        except TimeoutError as exc:
            raise RpcError(f"Solana RPC call '{method}' timed out after {self.timeout}s") from exc

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise RpcError(f"Invalid JSON from Solana RPC: {raw_response[:200]}") from exc

        if "error" in data:
            err = data["error"]
            msg = err.get("message", "Unknown Solana RPC error") if isinstance(err, dict) else str(err)
            raise RpcError(f"Solana RPC {method} error: {msg}")

        if "result" not in data:
            raise RpcError(f"Solana RPC response missing 'result': {data}")

        return data["result"]

    def get_balance(self, address: str) -> int:
        """Get native SOL balance in lamports."""
        res = self.call("getBalance", [address, {"commitment": "confirmed"}])
        return int(res.get("value", 0))

    def get_slot(self) -> int:
        """Get current slot."""
        return int(self.call("getSlot", [{"commitment": "confirmed"}]))

    def get_version(self) -> str:
        """Get Solana node version."""
        res = self.call("getVersion", [])
        return res.get("solana-core", "unknown")

    def get_latest_blockhash(self) -> Tuple[str, int]:
        """Fetch latest blockhash and lastValidBlockHeight."""
        res = self.call("getLatestBlockhash", [{"commitment": "confirmed"}])
        val = res["value"]
        return val["blockhash"], val["lastValidBlockHeight"]

    def send_transaction(self, raw_tx_bytes: bytes) -> str:
        """Broadcast raw wire transaction bytes and return transaction signature (Base58)."""
        tx_b64 = base64.b64encode(raw_tx_bytes).decode("ascii")
        sig = self.call(
            "sendTransaction",
            [
                tx_b64,
                {
                    "encoding": "base64",
                    "preflightCommitment": "confirmed",
                },
            ],
        )
        return sig

    def get_signature_status(self, signature: str) -> Optional[dict]:
        """Check status of a transaction signature."""
        res = self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        vals = res.get("value", [])
        return vals[0] if vals else None

    def get_token_accounts_by_owner(self, owner: str, mint: Optional[str] = None) -> List[dict]:
        """Fetch SPL token accounts owned by an address."""
        TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        filter_criteria = {"mint": mint} if mint else {"programId": TOKEN_PROGRAM_ID}
        res = self.call(
            "getTokenAccountsByOwner",
            [
                owner,
                filter_criteria,
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
        )
        return res.get("value", [])

    def get_token_supply(self, mint: str) -> dict:
        """Fetch token supply and decimals for a mint."""
        res = self.call("getTokenSupply", [mint, {"commitment": "confirmed"}])
        return res.get("value", {})
