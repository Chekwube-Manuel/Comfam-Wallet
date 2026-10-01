# Confam Wallet

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/confam-wallet.svg)](https://pypi.org/project/confam-wallet/)
[![Tests](https://img.shields.io/badge/tests-29%20passed-brightgreen.svg)]()

A production-grade, non-custodial multi-chain CLI wallet for **Ethereum** and **Solana** built in Python.

Keys are generated directly on your machine using the operating system's cryptographic random number generator (CSPRNG), encrypted inside password-protected keystores (scrypt KDF), and every signature is produced locally in-memory. The network is only contacted for public reads (nonces, balances, blockhashes, gas estimates) and to broadcast pre-signed raw transactions. **No private key material or unencrypted secrets ever leave your machine.**

---

## Supported Ecosystems

| Network | Cryptography | Native Asset | Token Standard |
| :--- | :--- | :--- | :--- |
| **Ethereum & EVM Chains** | `secp256k1` / Keccak-256 | ETH (or native gas) | ERC-20 (USDT, USDC, DAI, etc.) |
| **Solana** | `Ed25519` (RFC 8032) / SHA-512 | SOL (Lamports) | SPL Tokens (USDC, USDT, etc.) |

---

## Key Features & Production Hardening

- **Multi-Chain Architecture**: Seamlessly manage both Ethereum (EVM) and Solana (Ed25519) from a single CLI.
- **Non-Custodial & Air-Gapped Capable**: Offline transaction signing (`sign-tx`) decoupled from network broadcast (`broadcast-tx`).
- **Lossless Financial Precision**: Powered by Python's `Decimal` arithmetic—avoids binary float truncation bugs (e.g. `0.29 ETH` or `0.05 SOL`).
- **Keystore Overwrite Guards**: Prevents accidental wallet destruction and permanent fund loss; requires explicit `--force` to overwrite.
- **Cross-Platform Security Hardening**: Restrictive file permissions (`0o600` on POSIX and NTFS inheritance lockdown on Windows).
- **EIP-1559 & Legacy Gas Market**: Automatic fee estimation with congestion buffer, priority fee floors, and fallback to legacy `gasPrice`.
- **Pre-Flight Balance Validations**: Checks sender balance before signing to prevent stuck or rejected transactions.
- **Token Engines**: Full support for ERC-20 tokens on EVM and SPL tokens on Solana.
- **Transaction Receipt Polling**: `--wait` flag on transfers to inspect execution status, block inclusion, and confirmation.
- **Flexible Credential Ingestion**: Pass passwords via hidden interactive prompt, `CONFAM_PASSWORD` environment variable, `--password-stdin`, or `--password` CLI flag.

---

## Installation

### From PyPI (Recommended)

```bash
pip install confam-wallet
```

Or install globally as an isolated CLI via `pipx`:

```bash
pipx install confam-wallet
```

### From Source

```bash
git clone https://github.com/Chekwube-Manuel/Comfam-Wallet.git
cd Comfam-Wallet
python -m venv .venv

# Windows:
.\.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -e .
```

Verify installation:
```bash
confam --version
# Output: confam 1.1.0
```

---

## Configuration

| Environment Variable | Default Option | Description |
| :--- | :--- | :--- |
| `CONFAM_RPC_URL` | `http://127.0.0.1:8545` | Ethereum / EVM JSON-RPC endpoint |
| `CONFAM_SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | Solana JSON-RPC endpoint |
| `CONFAM_PASSWORD` | *(None)* | Keystore decryption password (avoids prompts) |

You can also pass `--rpc-url` / `-r` directly to any command to override the default endpoint.

---

## Solana (SOL & SPL Token) CLI Reference

All Solana commands are namespaced under `confam solana`:

### 1. Create a Solana Wallet

Generates a fresh Ed25519 keypair locally via OS CSPRNG and saves an encrypted keystore:

```bash
confam solana create --keyfile .keys/sol_wallet.json
```

### 2. Import an Existing Solana Key

Accepts Base58-encoded secret keys or standard Solana CLI JSON arrays (`[1, 2, ...]`, Phantom / Solflare compatible):

```bash
# Interactive prompt (hides key from shell history and process list)
confam solana import-key --keyfile .keys/sol_wallet.json

# Or via flag:
confam solana import-key --keyfile .keys/sol_wallet.json --private-key "5VERv8..."
```

### 3. Show Solana Address

```bash
confam solana address --keyfile .keys/sol_wallet.json
```

### 4. Check SOL Balance

```bash
# Check keystore balance
confam solana balance --keyfile .keys/sol_wallet.json

# Check any arbitrary Solana address
confam solana balance --address 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
```

### 5. Check Solana Cluster Status

```bash
confam solana status --rpc-url https://api.mainnet-beta.solana.com
```

### 6. Send Native SOL Transfer

```bash
confam solana send \
  --keyfile .keys/sol_wallet.json \
  --to 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM \
  --amount "0.5 sol" \
  --wait
```
*(Amounts accept `sol` or `lamports`. Bare numbers default to `sol`.)*

### 7. Query SPL Token Balance

```bash
# Query USDC balance on Solana (Mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)
confam solana token-balance \
  --keyfile .keys/sol_wallet.json \
  --mint EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
```

### 8. List All SPL Tokens in Wallet

```bash
confam solana tokens --keyfile .keys/sol_wallet.json
```

### 9. Transfer SPL Tokens

```bash
confam solana transfer-token \
  --keyfile .keys/sol_wallet.json \
  --source SourceTokenAccountAddress \
  --to DestinationTokenAccountAddress \
  --amount "25.5" \
  --decimals 6 \
  --wait
```

### 10. Sign & Verify Messages with Ed25519

```bash
# Sign text locally
confam solana sign-message --keyfile .keys/sol_wallet.json -m "Authenticate with Confam"

# Verify signature
confam solana verify-message \
  --address 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM \
  --signature Base58SignatureHex \
  --message "Authenticate with Confam"
```

### 11. Export Solana Private Key

```bash
# Export in standard Base58
confam solana export-key --keyfile .keys/sol_wallet.json

# Export as Solana CLI JSON array [1,2,...]
confam solana export-key --keyfile .keys/sol_wallet.json --json
```

---

## Ethereum / EVM CLI Reference

### 1. Create Wallet
```bash
confam create --keyfile .keys/eth_wallet.json
```

### 2. Check Balance & Network Status
```bash
confam balance --keyfile .keys/eth_wallet.json
confam chain-info --rpc-url https://rpc.sepolia.org
confam gas-price
```

### 3. Send ETH Transfer
```bash
confam send-tx \
  --keyfile .keys/eth_wallet.json \
  --to 0x70997970C51812dc3A010C7d01b50e0d17dc79C8 \
  --amount "0.05 ether" \
  --wait
```

### 4. ERC-20 Tokens (USDT, USDC, DAI)
```bash
# Check balance
confam token-balance --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 --keyfile .keys/eth_wallet.json

# Transfer tokens
confam transfer-token \
  --token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --keyfile .keys/eth_wallet.json \
  --to 0xRecipientAddress \
  --amount "50" \
  --wait
```

### 5. Air-Gapped / Offline Signing
```bash
# Sign offline
confam sign-tx \
  --keyfile .keys/cold.json \
  --to 0xRecipient \
  --amount "1.0 ether" \
  --nonce 0 \
  --chain-id 1 \
  --max-fee 30000000000 \
  --priority-fee 1500000000 > raw_tx.hex

# Broadcast online
confam broadcast-tx --raw-tx $(cat raw_tx.hex) --wait
```

---

## Testing

Run the full automated test suite with `pytest`:

```bash
pytest -v
```

All 29 tests pass covering:
- Base58 encoding, decoding, and checksum verification.
- Ed25519 keypair generation, address derivation, signing, and verification.
- Solana encrypted keystore creation, unlocking, and overwrite guards.
- Lossless SOL, Lamport, and SPL token unit conversions.
- Wire transaction binary compilation and compact-u16 serialization.
- SPL token transfer instruction construction.
- Ethereum EIP-1559 and legacy transaction signing and receipt polling.
- Lossless Decimal financial arithmetic.

---

## License

This project is licensed under the [MIT License](LICENSE).