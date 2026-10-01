"""JSON-RPC 2.0 Ethereum client with error formatting and retry capabilities."""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Union

from confam.errors import RpcError

DEFAULT_RPC_URL = "http://127.0.0.1:8545"


class RpcClient:
    """Production-ready Ethereum JSON-RPC 2.0 client."""

    def __init__(self, endpoint_url: Optional[str] = None, timeout: int = 30):
        self.endpoint_url = endpoint_url or os.environ.get("CONFAM_RPC_URL") or DEFAULT_RPC_URL
        self.timeout = timeout
        self._request_id = 1

    def call(self, method: str, params: Optional[Union[List[Any], Dict[str, Any]]] = None) -> Any:
        """Execute a JSON-RPC 2.0 request and return the result payload."""
        if params is None:
            params = []

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._request_id += 1

        encoded_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=encoded_data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ConfamWallet/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                err_json = json.loads(body)
                if "error" in err_json:
                    raise RpcError(f"RPC HTTP {exc.code} error: {err_json['error']}") from exc
            except Exception:
                pass
            raise RpcError(f"HTTP {exc.code} connecting to RPC at {self.endpoint_url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RpcError(f"Cannot reach RPC endpoint at '{self.endpoint_url}': {exc.reason}") from exc
        except TimeoutError as exc:
            raise RpcError(f"RPC call '{method}' timed out after {self.timeout}s at {self.endpoint_url}") from exc

        try:
            res_data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise RpcError(f"Invalid JSON returned by RPC endpoint: {raw_response[:200]}") from exc

        if not isinstance(res_data, dict):
            raise RpcError(f"Malformed RPC response: expected JSON object, got {type(res_data).__name__}")

        if "error" in res_data:
            err = res_data["error"]
            if isinstance(err, dict):
                msg = err.get("message", "Unknown RPC error")
                code = err.get("code", "")
                data = err.get("data", "")
                detail = f" (code: {code})" if code else ""
                if data:
                    detail += f" - data: {data}"
                raise RpcError(f"RPC {method} error: {msg}{detail}")
            raise RpcError(f"RPC {method} error: {err}")

        if "result" not in res_data:
            raise RpcError(f"RPC response missing 'result' field: {res_data}")

        return res_data["result"]

    def get_chain_id(self) -> int:
        res = self.call("eth_chainId")
        return int(res, 16) if isinstance(res, str) else int(res)

    def get_block_number(self) -> int:
        res = self.call("eth_blockNumber")
        return int(res, 16) if isinstance(res, str) else int(res)

    def get_balance(self, address: str, block: str = "latest") -> int:
        res = self.call("eth_getBalance", [address.lower(), block])
        return int(res, 16) if isinstance(res, str) else int(res)

    def get_transaction_count(self, address: str, block: str = "pending") -> int:
        try:
            res = self.call("eth_getTransactionCount", [address.lower(), block])
        except RpcError:
            # Some nodes don't support "pending" for getTransactionCount; fallback to "latest"
            res = self.call("eth_getTransactionCount", [address.lower(), "latest"])
        return int(res, 16) if isinstance(res, str) else int(res)

    def get_block_by_number(self, block: str = "latest", full_tx: bool = False) -> dict:
        res = self.call("eth_getBlockByNumber", [block, full_tx])
        if res is None:
            raise RpcError(f"Block '{block}' not found")
        return res

    def gas_price(self) -> int:
        res = self.call("eth_gasPrice")
        return int(res, 16) if isinstance(res, str) else int(res)

    def max_priority_fee_per_gas(self) -> Optional[int]:
        try:
            res = self.call("eth_maxPriorityFeePerGas")
            if res is None:
                return None
            return int(res, 16) if isinstance(res, str) else int(res)
        except Exception:
            return None

    def estimate_gas(self, tx_dict: dict) -> int:
        res = self.call("eth_estimateGas", [tx_dict])
        return int(res, 16) if isinstance(res, str) else int(res)

    def send_raw_transaction(self, raw_hex: str) -> str:
        clean = raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex
        return self.call("eth_sendRawTransaction", [clean])

    def get_transaction_receipt(self, tx_hash: str) -> Optional[dict]:
        clean = tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash
        return self.call("eth_getTransactionReceipt", [clean])

    def eth_call(self, to: str, data: str, block: str = "latest") -> str:
        tx_data = {"to": to, "data": data}
        return self.call("eth_call", [tx_data, block])
