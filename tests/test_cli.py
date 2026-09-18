"""Tests for the Confam Wallet CLI.

Covers keystore creation, address recovery, message signing/verification,
and send-tx against a local stub JSON-RPC server (no real network needed).
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eth_account import Account
from eth_account.messages import encode_defunct

import cli

KNOWN_KEY = "0x" + "11" * 32


class StubRpcHandler(BaseHTTPRequestHandler):
    """Minimal JSON-RPC stub: answers the calls send-tx/balance make."""

    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        StubRpcHandler.received.append(body)
        method = body["method"]
        if method == "eth_chainId":
            result = "0x1"
        elif method == "eth_getTransactionCount":
            result = "0x5"
        elif method == "eth_getBlockByNumber":
            result = {
                "baseFeePerGas": "0x3b9aca00",
                "number": "0x10",
            }
        elif method == "eth_estimateGas":
            result = "0x5208"
        elif method == "eth_sendRawTransaction":
            raw = body["params"][0]
            signed = Account.recover_transaction(raw)
            result = "0x" + signed
        elif method == "eth_getBalance":
            result = hex(10**18)
        else:
            result = None
        out = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        payload = out.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class ConfamWalletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        StubRpcHandler.received = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StubRpcHandler)
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

    def create_keystore(self, password="testpass"):
        rc = cli.main(["create", "--keyfile", self.keyfile, "--password", password])
        self.assertEqual(rc, 0)
        with open(self.keyfile) as fh:
            ks = json.load(fh)
        self.assertEqual(ks["version"], 3)
        self.assertEqual(ks["crypto"]["kdf"], "scrypt")
        return ks

    def test_create_and_address_recovery(self):
        ks = self.create_keystore()
        address = Account.decrypt(ks, "testpass")
        self.assertEqual(len(address), 32)
        rc = cli.main(["address", "--keyfile", self.keyfile, "--password", "testpass"])
        self.assertEqual(rc, 0)

    def test_wrong_password_rejected(self):
        self.create_keystore("right-password")
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["address", "--keyfile", self.keyfile, "--password", "wrong"])
        self.assertIn("wrong password", str(ctx.exception))

    def test_import_key_recovers_address(self):
        rc = cli.main(
            [
                "import-key",
                "--private-key",
                KNOWN_KEY,
                "--keyfile",
                self.keyfile,
                "--password",
                "testpass",
            ]
        )
        self.assertEqual(rc, 0)
        expected = Account.from_key(KNOWN_KEY).address
        rc = cli.main(["address", "--keyfile", self.keyfile, "--password", "testpass"])
        self.assertEqual(rc, 0)
        # capture stdout
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["address", "--keyfile", self.keyfile, "--password", "testpass"])
        self.assertEqual(buf.getvalue().strip(), Account.from_key(KNOWN_KEY).address)

    def test_sign_and_verify_message_roundtrip(self):
        ks = self.create_keystore()
        priv = Account.decrypt(ks, "testpass")
        addr = Account.from_key(priv).address
        message = "hello confam"

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(
                ["sign-message", "--keyfile", self.keyfile, "--password", "testpass", "--message", message]
            )
        self.assertEqual(rc, 0)
        signature = buf.getvalue().splitlines()[0].strip()
        self.assertTrue(signature.startswith("0x"))
        self.assertEqual(len(bytes.fromhex(signature[2:])), 65)

        recovered = Account.recover_message(
            encode_defunct(text=message), signature=bytes.fromhex(signature[2:])
        )
        self.assertEqual(recovered, Account.from_key(priv).address)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc = cli.main(
                [
                    "verify-message",
                    "--address",
                    addr,
                    "--signature",
                    signature,
                    "--message",
                    message,
                ]
            )
        self.assertEqual(rc, 0)
        self.assertIn("valid", buf2.getvalue())

        # a tampered message must not verify
        buf3 = io.StringIO()
        with redirect_stdout(buf3):
            rc = cli.main(
                [
                    "verify-message",
                    "--address",
                    addr,
                    "--signature",
                    signature,
                    "--message",
                    "hello confam TAMED",
                ]
            )
        self.assertEqual(rc, 1)
        self.assertIn("INVALID", buf3.getvalue())

    def test_send_tx_signs_locally_and_broadcasts(self):
        ks = self.create_keystore()
        priv = Account.decrypt(ks, "testpass")
        sender = Account.from_key(priv).address
        StubRpcHandler.received = []

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(
                [
                    "send-tx",
                    "--keyfile",
                    self.keyfile,
                    "--password",
                    "testpass",
                    "--to",
                    "0x000000000000000000000000000000000000dEaD",
                    "--amount",
                    "0.01 ether",
                ]
            )
        self.assertEqual(rc, 0)
        self.assertIn("sent:  0x", buf.getvalue())

        calls = [c["method"] for c in StubRpcHandler.received]
        self.assertIn("eth_chainId", calls)
        self.assertIn("eth_getTransactionCount", calls)
        self.assertIn("eth_estimateGas", calls)
        self.assertIn("eth_sendRawTransaction", calls)

        raw_call = next(c for c in StubRpcHandler.received if c["method"] == "eth_sendRawTransaction")
        raw = raw_call["params"][0]
        recovered = Account.recover_transaction(raw)
        self.assertEqual(recovered.lower(), sender.lower())

    def test_parse_amount_units(self):
        self.assertEqual(cli._parse_amount("1 wei"), 1)
        self.assertEqual(cli._parse_amount("1000 gwei"), 10**12)
        self.assertEqual(cli._parse_amount("1 ether"), 10**18)
        with self.assertRaises(SystemExit):
            cli._parse_amount("5 dogecoins")

    def test_bad_amount_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main(
                [
                    "send-tx",
                    "--keyfile",
                    self.keyfile,
                    "--password",
                    "testpass",
                    "--to",
                    "0x000000000000000000000000000000000000dEaD",
                    "--amount",
                    "oops",
                ]
            )
        self.assertIn("bad amount", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()