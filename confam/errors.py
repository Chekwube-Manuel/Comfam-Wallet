"""Custom exception classes for Confam Wallet."""


class ConfamError(Exception):
    """Base exception for all Confam errors."""
    pass


class RpcError(ConfamError):
    """Raised when an Ethereum JSON-RPC call fails or cannot be reached."""
    pass


class KeystoreError(ConfamError):
    """Raised for keystore loading, decryption, or creation errors."""
    pass


class ValidationError(ConfamError):
    """Raised when user input (addresses, amounts, signatures) is invalid."""
    pass


class TransactionError(ConfamError):
    """Raised when transaction construction, simulation, or execution fails."""
    pass

