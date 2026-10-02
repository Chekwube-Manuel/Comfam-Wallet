"""Comprehensive tests for Solana and SPL token support."""

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from confam.cli import main
from confam.errors import KeystoreError, ValidationError
from confam.solana.base58 import b58decode, b58encode, b58decode_check, b58encode_check
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
    compile_message,
    encode_compact_u16,
    sign_and_serialize_transaction,
)
from confam.solana.units import (
    format_lamports,
    format_spl_amount,
    parse_sol_amount,
    parse_spl_amount,
)


class SolanaRpcStubHandler(BaseHTTPRequestHandler):
    """Stub RPC handler for Solana JSON-RPC endpoints."""

    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        SolanaRpcStubHandler.received.append(body)
        method = body["method"]

        if method == "getBalance":
            result = {"context": {"slot": 12345}, "value": 2_500_000_000}  # 2.5 SOL
        elif method == "getSlot":
            result = 12345678
        elif method == "getVersion":
            result = {"solana-core": "2.0.0"}
        elif method == "getLatestBlockhash":
            result = {
                "context": {"slot": 12345},
                "value": {
                    "blockhash": "4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM",
                    "lastValidBlockHeight": 123456,
                },
            }
        elif method == "sendTransaction":
            result = "5VERv8NMvzbJMEdV8xnrLkEaMaWRnHUsAhDAVUsBHpe9YZSaqdcDqpUMaV5hTuY1LFKG8vgopA22QyPBJJoeepBX"
        elif method == "getSignatureStatuses":
            result = {
                "context": {"slot": 12345},
                "value": [{"confirmationStatus": "confirmed", "confirmations": 5, "slot": 12345, "err": None}],
            }
        elif method == "getTokenAccountsByOwner":
            result = {
                "context": {"slot": 12345},
                "value": [
                    {
                        "pubkey": "AyMKJE3K9zYtAWWMvQRAyrZzDsGYdLVL9WzDXwBbmkg8",
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                                        "tokenAmount": {
                                            "amount": "150000000",
                                            "decimals": 6,
                                            "uiAmountString": "150",
                                        },
                                    }
                                }
                            }
                        },
                    }
                ],
            }
        elif method == "getTokenSupply":
            result = {
                "context": {"slot": 12345},
                "value": {"amount": "1000000000000", "decimals": 6, "uiAmountString": "1000000"},
            }
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


class SolanaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SolanaRpcStubHandler.received = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SolanaRpcStubHandler)
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
        self.keyfile = os.path.join(self.tmp.name, "sol_wallet.json")
        self._old_rpc = os.environ.get("CONFAM_SOLANA_RPC_URL")
        os.environ["CONFAM_SOLANA_RPC_URL"] = self.rpc

    def tearDown(self):
        if self._old_rpc is None:
            os.environ.pop("CONFAM_SOLANA_RPC_URL", None)
        else:
            os.environ["CONFAM_SOLANA_RPC_URL"] = self._old_rpc
        self.tmp.cleanup()

    def test_base58_encoding_decoding(self):
        data = b"Hello Solana in Confam!"
        encoded = b58encode(data)
        decoded = b58decode(encoded)
        self.assertEqual(data, decoded)

        # Leading zeroes preserved
        zero_data = b"\x00\x00\x00\x01\x02\x03"
        self.assertEqual(b58decode(b58encode(zero_data)), zero_data)

    def test_keypair_generation_and_signatures(self):
        kp = SolanaKeypair.generate()
        self.assertEqual(len(kp.public_key_bytes), 32)
        self.assertEqual(len(kp.secret_key_bytes), 64)
        self.assertTrue(len(kp.address) >= 32)

        msg = b"Confam Wallet Authenticity Proof"
        sig = kp.sign(msg)
        self.assertEqual(len(sig), 64)
        self.assertTrue(SolanaKeypair.verify(kp.public_key_bytes, msg, sig))
        self.assertFalse(SolanaKeypair.verify(kp.public_key_bytes, b"Tampered", sig))

    def test_solana_keystore_create_and_unlock(self):
        kp, ks = create_solana_wallet(self.keyfile, "solpass")
        self.assertTrue(os.path.exists(self.keyfile))
        self.assertEqual(ks["type"], "solana")

        # Wrong password rejected
        with self.assertRaises(KeystoreError):
            unlock_solana_keystore(self.keyfile, "wrongpass")

        # Unlock
        unlocked = unlock_solana_keystore(self.keyfile, "solpass")
        self.assertEqual(unlocked.address, kp.address)

        # Overwrite protection
        with self.assertRaises(KeystoreError):
            create_solana_wallet(self.keyfile, "newpass", force=False)

    def test_solana_key_export_and_import(self):
        kp, _ = create_solana_wallet(self.keyfile, "solpass")
        exported_b58 = export_solana_key(self.keyfile, "solpass")
        self.assertEqual(exported_b58, kp.to_base58())

        # Import into new keyfile
        import_path = os.path.join(self.tmp.name, "imported_sol.json")
        imp_kp, _ = import_solana_key(exported_b58, import_path, "newpass")
        self.assertEqual(imp_kp.address, kp.address)

        # Import via JSON array format [1, 2, ...]
        json_path = os.path.join(self.tmp.name, "json_sol.json")
        json_arr_str = json.dumps(kp.to_json_array())
        json_kp, _ = import_solana_key(json_arr_str, json_path, "pass3")
        self.assertEqual(json_kp.address, kp.address)

    def test_solana_units(self):
        self.assertEqual(parse_sol_amount("1 sol"), 1_000_000_000)
        self.assertEqual(parse_sol_amount("0.5 sol"), 500_000_000)
        self.assertEqual(parse_sol_amount("500 lamports"), 500)
        self.assertEqual(parse_sol_amount("2"), 2_000_000_000)  # default unit
        self.assertEqual(format_lamports(1_500_000_000), "1.5")
        self.assertEqual(format_lamports(500), "0.0000005")

        with self.assertRaises(ValidationError):
            parse_sol_amount("0.0000000001 sol")  # fractional lamport
        with self.assertRaises(ValidationError):
            parse_sol_amount("-1 sol")

        # SPL token units
        self.assertEqual(parse_spl_amount("100.5", decimals=6), 100_500_000)
        self.assertEqual(format_spl_amount(100_500_000, decimals=6), "100.5")

    def test_solana_tx_compilation_and_serialization(self):
        kp = SolanaKeypair.generate()
        recipient = SolanaKeypair.generate()
        blockhash_b58 = "4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM"

        ix = build_sol_transfer_instruction(kp.public_key_bytes, recipient.public_key_bytes, 100_000_000)
        wire_tx = sign_and_serialize_transaction(kp, [ix], blockhash_b58)
        self.assertTrue(len(wire_tx) > 100)

        # Extract signature and message from wire bytes
        # wire: compact-u16(1) + 64 bytes signature + message
        sig_len = wire_tx[0]
        self.assertEqual(sig_len, 1)
        sig = wire_tx[1:65]
        msg = wire_tx[65:]
        self.assertTrue(SolanaKeypair.verify(kp.public_key_bytes, msg, sig))

    def test_cli_solana_commands(self):
        # Create
        rc = main(["solana", "create", "--keyfile", self.keyfile, "--password", "testsolpass"])
        self.assertEqual(rc, 0)

        # Address
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["solana", "address", "--keyfile", self.keyfile, "--password", "testsolpass"])
        self.assertEqual(rc, 0)
        addr = buf.getvalue().strip()
        self.assertTrue(len(addr) >= 32)

        # Balance
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc = main(["solana", "balance", "--keyfile", self.keyfile, "--password", "testsolpass"])
        self.assertEqual(rc, 0)
        self.assertIn("2.5 SOL", buf2.getvalue())

        # Status
        buf3 = io.StringIO()
        with redirect_stdout(buf3):
            rc = main(["solana", "status"])
        self.assertEqual(rc, 0)
        self.assertIn("version:    2.0.0", buf3.getvalue())

        # Sign and verify message
        buf4 = io.StringIO()
        with redirect_stdout(buf4):
            rc = main(["solana", "sign-message", "--keyfile", self.keyfile, "--password", "testsolpass", "-m", "hello"])
        self.assertEqual(rc, 0)
        sig_b58 = buf4.getvalue().splitlines()[0].strip()

        buf5 = io.StringIO()
        with redirect_stdout(buf5):
            rc = main(["solana", "verify-message", "-a", addr, "-s", sig_b58, "-m", "hello"])
        self.assertEqual(rc, 0)
        self.assertIn("valid", buf5.getvalue())

        # Send SOL
        recipient = SolanaKeypair.generate().address
        buf6 = io.StringIO()
        with redirect_stdout(buf6):
            rc = main(["solana", "send", "--keyfile", self.keyfile, "--password", "testsolpass", "--to", recipient, "--amount", "0.5 sol", "--wait"])
        self.assertEqual(rc, 0)
        self.assertIn("signature: 5VER", buf6.getvalue())

        # Token balance
        buf7 = io.StringIO()
        with redirect_stdout(buf7):
            rc = main(["solana", "token-balance", "--keyfile", self.keyfile, "--password", "testsolpass", "--mint", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"])
        self.assertEqual(rc, 0)
        self.assertIn("150 tokens", buf7.getvalue())

        # Tokens list
        buf8 = io.StringIO()
        with redirect_stdout(buf8):
            rc = main(["solana", "tokens", "--keyfile", self.keyfile, "--password", "testsolpass"])
        self.assertEqual(rc, 0)
        self.assertIn("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", buf8.getvalue())

    def test_default_keyfile_creation_and_resolution(self):
        """When --keyfile is omitted, commands automatically resolve to CONFAM_SOLANA_KEYFILE / default."""
        custom_default = os.path.join(self.tmp.name, "auto_default_sol.json")
        os.environ["CONFAM_SOLANA_KEYFILE"] = custom_default
        try:
            # Create without --keyfile
            rc = main(["solana", "create", "--password", "autopass"])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(custom_default))

            # Address without --keyfile
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["solana", "address", "--password", "autopass"])
            self.assertEqual(rc, 0)
            self.assertTrue(len(buf.getvalue().strip()) >= 32)

            # Balance without --keyfile
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                rc = main(["solana", "balance", "--password", "autopass"])
            self.assertEqual(rc, 0)
            self.assertIn("2.5 SOL", buf2.getvalue())
        finally:
            os.environ.pop("CONFAM_SOLANA_KEYFILE", None)


if __name__ == "__main__":
    unittest.main()

