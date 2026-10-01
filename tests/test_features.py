"""Tests for production features: overwrite protection, export key, offline signing, ERC-20, and receipt polling."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eth_account import Account
from confam.cli import main
from confam.erc20 import build_erc20_transfer_data, get_token_metadata
from confam.errors import TransactionError, ValidationError
from confam.keystore import create_wallet, export_private_key, unlock_keystore
from confam.rpc import RpcClient


class FeatureRpcHandler(BaseHTTPRequestHandler):
    """Stub RPC handler with support for eth_call, getTransactionReceipt, and gas queries."""

    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        FeatureRpcHandler.received.append(body)
        method = body["method"]

        if method == "eth_chainId":
            result = "0x1"
        elif method == "eth_blockNumber":
            result = "0x12345"
        elif method == "eth_gasPrice":
            result = hex(20 * 10**9)
        elif method == "eth_maxPriorityFeePerGas":
            result = hex(2 * 10**9)
        elif method == "eth_getBlockByNumber":
            result = {
                "number": "0x12345",
                "baseFeePerGas": hex(15 * 10**9),
            }
        elif method == "eth_getBalance":
            # return 10 ETH
            result = hex(10 * 10**18)
        elif method == "eth_getTransactionCount":
            result = "0x2"
        elif method == "eth_estimateGas":
            result = "0x5208"  # 21000
        elif method == "eth_sendRawTransaction":
            result = "0x" + "a" * 64
        elif method == "eth_getTransactionReceipt":
            result = {
                "status": "0x1",
                "blockNumber": "0x12345",
                "gasUsed": "0x5208",
                "effectiveGasPrice": hex(17 * 10**9),
            }
        elif method == "eth_call":
            # ERC20 metadata or balance mock
            result = "0x"
        else:
            result = None

        out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        payload = out.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class ProductionFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FeatureRpcHandler.received = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FeatureRpcHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.rpc = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keyfile = os.path.join(self.tmp.name, "wallet.json")
        self._old_rpc = os.environ.get("CONFAM_RPC_URL")
        os.environ["CONFAM_RPC_URL"] = self.rpc

    def tearDown(self):
        if self._old_rpc is None:
            os.environ.pop("CONFAM_RPC_URL", None)
        else:
            os.environ["CONFAM_RPC_URL"] = self._old_rpc
        self.tmp.cleanup()

    def test_keystore_overwrite_protection(self):
        """Creating an already existing keyfile must fail unless --force is passed."""
        main(["create", "--keyfile", self.keyfile, "--password", "pass1"])
        self.assertTrue(os.path.exists(self.keyfile))

        # Attempting to recreate must fail
        with self.assertRaises(SystemExit) as ctx:
            main(["create", "--keyfile", self.keyfile, "--password", "pass2"])
        self.assertIn("already exists", str(ctx.exception))

        # With --force it must succeed
        rc = main(["create", "--keyfile", self.keyfile, "--password", "pass3", "--force"])
        self.assertEqual(rc, 0)

    def test_export_key_with_flag(self):
        """Export key outputs the 32-byte private key when confirmed."""
        acc, _ = create_wallet(self.keyfile, "mypass")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["export-key", "--keyfile", self.keyfile, "--password", "mypass", "--yes"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("private_key: 0x", output)
        priv_hex = output.split("private_key: ")[1].strip()
        self.assertEqual(Account.from_key(priv_hex).address, acc.address)

    def test_password_from_env(self):
        """Keystore commands respect CONFAM_PASSWORD environment variable."""
        acc, _ = create_wallet(self.keyfile, "secret-env-pass")
        os.environ["CONFAM_PASSWORD"] = "secret-env-pass"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["address", "--keyfile", self.keyfile])
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), acc.address)
        finally:
            os.environ.pop("CONFAM_PASSWORD", None)

    def test_chain_info_and_gas_price(self):
        """Verify chain-info and gas-price output formats."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["chain-info"])
        self.assertEqual(rc, 0)
        self.assertIn("chainId:      1", buf.getvalue())

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc = main(["gas-price"])
        self.assertEqual(rc, 0)
        self.assertIn("baseFeePerGas:", buf2.getvalue())

    def test_offline_sign_and_broadcast(self):
        """Air-gapped transaction signing and network broadcast."""
        acc, _ = create_wallet(self.keyfile, "offlinepass")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(
                [
                    "sign-tx",
                    "--keyfile",
                    self.keyfile,
                    "--password",
                    "offlinepass",
                    "--to",
                    "0x000000000000000000000000000000000000dEaD",
                    "--amount",
                    "0.05 ether",
                    "--nonce",
                    "1",
                    "--chain-id",
                    "1",
                    "--max-fee",
                    "30000000000",
                    "--priority-fee",
                    "2000000000",
                ]
            )
        self.assertEqual(rc, 0)
        raw_tx = buf.getvalue().strip()
        self.assertTrue(raw_tx.startswith("0x"))

        # Broadcast raw transaction
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = main(["broadcast-tx", "--raw-tx", raw_tx])
        self.assertEqual(rc2, 0)
        self.assertIn("broadcast: 0x", buf2.getvalue())

    def test_receipt_command(self):
        """Verify transaction receipt fetching."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["receipt", "--tx-hash", "0x" + "b" * 64])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("status:       SUCCESS", output)
        self.assertIn("blockNumber:  74565", output)

    def test_erc20_transfer_calldata(self):
        """Verify standard ERC-20 transfer(address,uint256) data encoding."""
        recipient = "0x000000000000000000000000000000000000dEaD"
        amount = 100_000_000  # 100 USDC (6 decimals)
        calldata = build_erc20_transfer_data(recipient, amount)
        self.assertTrue(calldata.startswith("0xa9059cbb"))  # transfer selector
        self.assertEqual(len(bytes.fromhex(calldata[2:])), 68)  # 4 bytes selector + 64 bytes arguments

    def test_invalid_signature_in_verify_message(self):
        """Malformed signature lengths and non-hex inputs must be rejected gracefully."""
        with self.assertRaises(SystemExit) as ctx:
            main(
                [
                    "verify-message",
                    "--address",
                    "0x000000000000000000000000000000000000dEaD",
                    "--signature",
                    "0x1234",  # invalid length
                    "--message",
                    "test",
                ]
            )
        self.assertIn("65 bytes", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
