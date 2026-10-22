"""Envelope encryption: sealed blobs and wrapped data keys (EA-20)."""

from uuid import uuid4

import pytest

from ei_ai.crypto.envelope import (
    BLOB_MAGIC,
    BLOB_OVERHEAD,
    DATA_KEY_BYTES,
    MAX_PLAINTEXT_BYTES,
    WRAPPED_KEY_BYTES,
    new_data_key,
    open_sealed,
    seal,
    unwrap_data_key,
    wrap_data_key,
)
from ei_ai.crypto.errors import DecryptionFailed
from ei_ai.crypto.master_key import MasterKey


def _master(byte: int = 1) -> MasterKey:
    return MasterKey(bytes([byte]) * 32)


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024])
def test_seal_open_round_trip(size: int) -> None:
    dek, org = new_data_key(), uuid4()
    plaintext = b"x" * size
    blob = seal(dek, org, plaintext)
    assert len(dek) == DATA_KEY_BYTES
    assert len(blob) == size + BLOB_OVERHEAD
    assert blob[:4] == BLOB_MAGIC
    assert open_sealed(dek, org, blob) == plaintext
    assert seal(dek, org, plaintext) != blob


def test_open_with_other_org_or_key_fails() -> None:
    dek, org = new_data_key(), uuid4()
    blob = seal(dek, org, b"secret")
    with pytest.raises(DecryptionFailed):
        open_sealed(dek, uuid4(), blob)
    with pytest.raises(DecryptionFailed):
        open_sealed(new_data_key(), org, blob)


def test_tampered_or_truncated_blob_fails() -> None:
    dek, org = new_data_key(), uuid4()
    blob = seal(dek, org, b"some plaintext")
    for index in (0, 5, 17, len(blob) - 1):  # magic, nonce, body, tag
        tampered = bytearray(blob)
        tampered[index] ^= 0x01
        with pytest.raises(DecryptionFailed):
            open_sealed(dek, org, bytes(tampered))
    with pytest.raises(DecryptionFailed):
        open_sealed(dek, org, blob[:31])


def test_seal_refuses_above_cap() -> None:
    with pytest.raises(ValueError):
        seal(new_data_key(), uuid4(), bytes(MAX_PLAINTEXT_BYTES + 1))


def test_wrap_unwrap_round_trip() -> None:
    master, org, dek = _master(), uuid4(), new_data_key()
    wrapped = wrap_data_key(master, org, dek)
    assert len(wrapped) == WRAPPED_KEY_BYTES
    assert wrapped != dek
    assert unwrap_data_key(master, org, wrapped) == dek
    with pytest.raises(DecryptionFailed):
        unwrap_data_key(master, uuid4(), wrapped)
    with pytest.raises(DecryptionFailed):
        unwrap_data_key(_master(2), org, wrapped)
    with pytest.raises(DecryptionFailed):
        unwrap_data_key(master, org, wrapped[:-1])
