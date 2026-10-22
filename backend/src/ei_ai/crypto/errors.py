"""Typed crypto errors. Messages are static: they never carry keys, data or ids."""


class CryptoError(Exception):
    """Base class of every crypto failure."""


class KeyNotFound(CryptoError):
    def __init__(self) -> None:
        super().__init__("no data key for this Organization")


class KeyDestroyed(CryptoError):
    def __init__(self) -> None:
        super().__init__("the data key of this Organization was destroyed")


class MasterKeyMismatch(CryptoError):
    def __init__(self) -> None:
        super().__init__("the master key does not match the stored data key")


class DecryptionFailed(CryptoError):
    def __init__(self) -> None:
        super().__init__("decryption failed")
