"""AES-256-GCM envelope encryption: wrapped data keys and sealed blobs.

Blob format: ``BLOB_MAGIC || nonce (12) || ciphertext || tag (16)``. The associated data
binds every key and blob to its Organization.
"""

import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ei_ai.crypto.errors import DecryptionFailed
from ei_ai.crypto.master_key import MasterKey

DATA_KEY_BYTES = 32
NONCE_BYTES = 12
WRAPPED_KEY_BYTES = 60
BLOB_MAGIC = b"EIA\x01"
BLOB_OVERHEAD = 32
MAX_PLAINTEXT_BYTES = 64 * 1024 * 1024

_TAG_BYTES = 16
_DEK_AAD = b"ei-ai:dek:v1:"
_DATA_AAD = b"ei-ai:data:v1:"


def new_data_key() -> bytes:
    return os.urandom(DATA_KEY_BYTES)


def wrap_data_key(master: MasterKey, org_id: UUID, dek: bytes) -> bytes:
    """Encrypt a data key under the master key: ``nonce || ciphertext || tag`` (60 bytes)."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce + master.aead().encrypt(nonce, dek, _DEK_AAD + org_id.bytes)


def unwrap_data_key(master: MasterKey, org_id: UUID, wrapped: bytes) -> bytes:
    if len(wrapped) != WRAPPED_KEY_BYTES:
        raise DecryptionFailed() from None
    try:
        return master.aead().decrypt(
            wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:], _DEK_AAD + org_id.bytes
        )
    except InvalidTag:
        raise DecryptionFailed() from None


def seal(dek: bytes, org_id: UUID, plaintext: bytes | bytearray) -> bytes:
    """Encrypt ``plaintext`` for the Organization; ``ValueError`` above the size cap."""
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise ValueError("plaintext is larger than the maximum size")
    nonce = os.urandom(NONCE_BYTES)
    return BLOB_MAGIC + nonce + AESGCM(dek).encrypt(nonce, plaintext, _DATA_AAD + org_id.bytes)


def open_sealed(dek: bytes, org_id: UUID, blob: bytes) -> bytes:
    header = len(BLOB_MAGIC) + NONCE_BYTES
    if len(blob) < header + _TAG_BYTES or not blob.startswith(BLOB_MAGIC):
        raise DecryptionFailed() from None
    try:
        return AESGCM(dek).decrypt(
            blob[len(BLOB_MAGIC) : header], blob[header:], _DATA_AAD + org_id.bytes
        )
    except (InvalidTag, ValueError):
        raise DecryptionFailed() from None
