"""The platform master key (key-encryption key), loaded from the environment."""

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ei_ai.settings import SettingsError

_KEY_BYTES = 32
_HEX_KEY = re.compile(r"[0-9a-fA-F]{64}")
_KEK_ID_LABEL = b"ei-ai/kek-id/v1"


@dataclass(frozen=True)
class MasterKey:
    """A 256-bit key; ``repr``/``str`` show only the non-secret ``kek_id``."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != _KEY_BYTES:
            raise ValueError("the master key must be 32 bytes")

    @property
    def kek_id(self) -> str:
        """A non-secret fingerprint (16 hex characters) of this key."""
        return hmac.new(self.key, _KEK_ID_LABEL, hashlib.sha256).hexdigest()[:16]

    def aead(self) -> AESGCM:
        return AESGCM(self.key)

    def __repr__(self) -> str:
        return f"MasterKey(kek_id={self.kek_id})"

    __str__ = __repr__


def master_key_from_env(env: Mapping[str, str]) -> MasterKey:
    """Build the master key from EI_AI_MASTER_KEY or EI_AI_MASTER_KEY_FILE (exactly one).

    Raises ``SettingsError`` naming the variable, never its value.
    """
    value = env.get("EI_AI_MASTER_KEY", "").strip()
    path = env.get("EI_AI_MASTER_KEY_FILE", "").strip()
    if value and path:
        raise SettingsError("set only one of EI_AI_MASTER_KEY and EI_AI_MASTER_KEY_FILE")
    if not value and not path:
        raise SettingsError("EI_AI_MASTER_KEY or EI_AI_MASTER_KEY_FILE is required")
    if value:
        if _HEX_KEY.fullmatch(value) is None:
            raise SettingsError("EI_AI_MASTER_KEY must be 64 hexadecimal characters")
        return MasterKey(bytes.fromhex(value))
    try:
        content = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise SettingsError("EI_AI_MASTER_KEY_FILE cannot be read") from None
    if _HEX_KEY.fullmatch(content) is None:
        raise SettingsError("EI_AI_MASTER_KEY_FILE must hold 64 hexadecimal characters")
    return MasterKey(bytes.fromhex(content))
