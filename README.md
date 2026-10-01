# Confam Wallet

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-22%20passed-brightgreen.svg)]()

A production-grade, non-custodial Ethereum CLI wallet built in Python.

Keys are generated directly on your machine using the operating system's cryptographic random number generator (CSPRNG), encrypted inside a password-protected Web3 V3 keystore (scrypt KDF), and every signature is produced locally in-memory. The network is only contacted for public reads (nonces, balances, gas estimates) and to broadcast pre-signed raw transactions. **No private key material or unencrypted secrets ever leave your machine.**

---

## Key Features & Production Hardening

- **Non-Custodial & Air-Gapped Capable**: Offline transaction signing (`sign-tx`) decoupled from network broadcast (`broadcast-tx`).
- **Lossless Financial Precision**: Powered by Python's `Decimal` arithmetic—avoids binary float truncation bugs (e.g., standard `0.29 ETH` float truncation).
- **Keystore Overwrite Guards**: Prevents accidental wallet destruction and permanent fund loss; requires explicit `--force` to overwrite.
- **Cross-Platform Security Hardening**: Restrictive file permissions (`0o600` on POSIX and NTFS inheritance lockdown on Windows).
- **EIP-1559 & Legacy Gas Market**: Automatic fee estimation with congestion buffer, priority fee floors, and fallback to legacy `gasPrice`.
- **Pre-Flight Balance Validations**: Checks sender balance for `value + (gas_limit * max_fee)` before signing to prevent stuck or rejected transactions.
- **ERC-20 Token Engine**: Query metadata (name, symbol, decimals), query balances, and transfer tokens (USDT, USDC, DAI, etc.).
- **Transaction Receipt Polling**: `--wait` flag on `send-tx` and standalone `receipt` command to inspect execution status, block inclusion, and effective gas fees.
- **Flexible Credential Ingestion**: Pass passwords via hidden interactive prompt, `CONFAM_PASSWORD` environment variable, `--password-stdin`, or `--password` CLI flag.

---

## Installation

### Option 1: Install from Wheel / Source (Recommended)

```bash
# Clone the repository
git clone https://github.com/Chekwube-Manuel/Comfam-Wallet.git
cd Comfam-Wallet

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.\.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# Install package and dependencies
pip install .
```

After installation, the `confam` command is available directly in your terminal:
```bash
confam --version
# Output: confam 1.0.0
```

### Option 2: Standalone Global CLI via `pipx`

```bash
pipx install .
```

---

## Configuration

| Environment Variable | Default Option          | Description                                  |
| -------------------- | ----------------------- | -------------------------------------------- |
| `CONFAM_RPC_URL`     | `http://127.0.0.1:8545` | Ethereum JSON-RPC endpoint (Infura, Alchemy, Anvil, etc.) |
| `CONFAM_PASSWORD`    | *(None)*                | Keystore decryption password (avoids prompts) |

You can also pass `--rpc-url` / `-r` directly to any network-dependent command to override the environment variable.

---

## CLI Command Reference

### 1. Create a New Wallet

Generates a fresh Ethereum keypair locally via OS CSPRNG and saves an encrypted Web3 V3 keystore:

```bash
confam create --keyfile .keys/wallet.json
```
*(Prompts securely for password confirmation)*

To overwrite an existing keystore intentionally:
```bash
confam create --keyfile .keys/wallet.json --force
```

### 2. Import an Existing Private Key

```bash
# Interactive prompt (hides key from terminal history and process table)
confam import-key --keyfile .keys/wallet.json

# Or pass via flag:
confam import-key --private-key 0xYOUR_HEX_KEY --keyfile .keys/wallet.json
```

### 3. Show Wallet Address

```bash
confam address --keyfile .keys/wallet.json
```

### 4. Check ETH Balance

```bash
# Query balance for keystore
confam balance --keyfile .keys/wallet.json

# Query balance for any arbitrary address
confam balance --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
```

### 5. Check Network & Gas Market

```bash
# Network status (chain ID, block number, base fee, gas price)
confam chain-info --rpc-url https://rpc.sepolia.org

# Recommended fee market rates (EIP-1559 priority fee and max fee)
confam gas-price
```

### 6. Send ETH (Build, Sign Locally, and Broadcast)

```bash
# Send with human-readable units (ether, gwei, wei)
confam send-tx \
  --keyfile .keys/wallet.json \
  --to 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 \
  --amount "0.05 ether" \
  --wait
```

Supported units: `ether`, `eth`, `gwei`, `mwei`, `kwei`, `wei`, `szabo`, `finney`. Bare numbers default to `ether`.

### 7. ERC-20 Token Balances & Transfers

```bash
# Check ERC-20 token balance (e.g. USDT, USDC)
confam token-balance \
  --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --keyfile .keys/wallet.json

# Transfer tokens (converts human decimal units automatically)
confam transfer-token \
  --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --keyfile .keys/wallet.json \
  --to 0xRecipientAddress \
  --amount "25.5" \
  --wait
```

### 8. Inspect Transaction Receipt

```bash
confam receipt --tx-hash 0xYOUR_TRANSACTION_HASH
```

### 9. Sign and Verify Messages (EIP-191 `personal_sign`)

```bash
# Sign locally
confam sign-message \
  --keyfile .keys/wallet.json \
  --message "Verify ownership for Confam"

# Verify signature
confam verify-message \
  --address 0xExpectedSigner \
  --signature 0xSignatureHex \
  --message "Verify ownership for Confam"
```

### 10. Air-Gapped / Offline Signing

Sign transactions on an offline, air-gapped machine without exposing keys to the network:

```bash
# Step 1: On offline machine, build and sign raw transaction hex
confam sign-tx \
  --keyfile .keys/cold_storage.json \
  --to 0xRecipient \
  --amount "1.0 ether" \
  --nonce 0 \
  --chain-id 1 \
  --max-fee 30000000000 \
  --priority-fee 1500000000 > raw_tx.hex

# Step 2: On online machine, broadcast the pre-signed transaction
confam broadcast-tx --raw-tx $(cat raw_tx.hex) --wait
```

### 11. Securely Export Private Key

```bash
confam export-key --keyfile .keys/wallet.json
```
*(Requires confirmation before displaying the private key)*

---

## Testing

Run the full automated test suite with `pytest`:

```bash
pytest -v
```

Or using Python's standard `unittest`:

```bash
python -m unittest discover -s tests
```

The test suite covers:
- Exact Decimal financial precision and unit conversions.
- Keystore encryption, decryption, and overwrite protection.
- EIP-191 message signing, signature verification, and tampered signature rejection.
- EIP-1559 and legacy transaction construction and local signing against a local stub JSON-RPC server.
- Pre-flight balance validation and error handling.
- ERC-20 calldata encoding and metadata parsing.
- Offline transaction signing and raw broadcast.

---

## Release & Distribution

### Building Distribution Packages

Generate standard Wheel (`.whl`) and Source Distribution (`.tar.gz`):

```bash
python -m pip install build
python -m build
```

Artifacts are output to `dist/`:
- `dist/confam_wallet-1.0.0-py3-none-any.whl`
- `dist/confam_wallet-1.0.0.tar.gz`

### Publishing to PyPI

```bash
pip install twine
twine check dist/*
twine upload dist/*
```

Users can then install directly via:
```bash
pip install confam-wallet
```

---

## License

This project is licensed under the [MIT License](LICENSE).