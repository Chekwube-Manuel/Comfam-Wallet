#!/usr/bin/env python3
"""Confam Wallet - entrypoint shim for backwards compatibility.

Redirects directly to `confam.cli:main` and re-exports core helpers.
"""

import sys
from confam.cli import (
    build_parser,
    cmd_address,
    cmd_balance,
    cmd_create,
    cmd_import_key,
    cmd_send_tx,
    cmd_sign_message,
    cmd_verify_message,
    main,
)
from confam.errors import ValidationError
from confam.keystore import load_keystore
from confam.rpc import RpcClient
from confam.units import parse_ether_amount


def _parse_amount(value: str) -> int:
    try:
        return parse_ether_amount(value)
    except ValidationError as exc:
        raise SystemExit(f"error: {exc}")


def rpc_call(method: str, params=None):
    return RpcClient().call(method, params or [])


if __name__ == "__main__":
    sys.exit(main())