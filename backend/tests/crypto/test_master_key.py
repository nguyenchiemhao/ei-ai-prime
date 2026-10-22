"""The platform master key: construction, fingerprint and environment loading (EA-20)."""

import base64
import re
from pathlib import Path

import pytest

from ei_ai.crypto.master_key import MasterKey, master_key_from_env
from ei_ai.settings import SettingsError

HEX = "ab" * 32


def test_kek_id_is_16_hex_and_key_dependent() -> None:
    first, second = MasterKey(bytes(32)), MasterKey(bytes([1]) * 32)
    assert re.fullmatch(r"[0-9a-f]{16}", first.kek_id) is not None
    assert first.kek_id != second.kek_id
    assert first.kek_id == MasterKey(bytes(32)).kek_id


def test_master_key_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        MasterKey(bytes(31))


def test_master_key_repr_hides_key() -> None:
    raw = bytes(range(32))
    key = MasterKey(raw)
    texts = [repr(key), str(key), f"{key}"]
    assert all(key.kek_id in text for text in texts)
    assert not any(raw.hex() in text for text in texts)
    assert not any(base64.b64encode(raw).decode() in text for text in texts)


def test_master_key_from_env_value_and_file(tmp_path: Path) -> None:
    expected = bytes.fromhex(HEX)
    from_value = master_key_from_env({"EI_AI_MASTER_KEY": f" {HEX}\n"})
    assert from_value.kek_id == MasterKey(expected).kek_id
    path = tmp_path / "master.key"
    path.write_text(HEX + "\n", encoding="utf-8")
    from_file = master_key_from_env({"EI_AI_MASTER_KEY_FILE": str(path)})
    assert from_file.kek_id == MasterKey(expected).kek_id


def test_settings_errors_name_variable_not_value(tmp_path: Path) -> None:
    short = tmp_path / "short.key"
    short.write_text("ab" * 31, encoding="utf-8")
    missing = str(tmp_path / "missing-secret-path.key")
    cases = [
        ({"EI_AI_MASTER_KEY": HEX, "EI_AI_MASTER_KEY_FILE": missing}, "EI_AI_MASTER_KEY", HEX),
        ({}, "EI_AI_MASTER_KEY or EI_AI_MASTER_KEY_FILE is required", ""),
        ({"EI_AI_MASTER_KEY": "a" * 63}, "EI_AI_MASTER_KEY must be 64", "a" * 63),
        ({"EI_AI_MASTER_KEY": "z" * 64}, "EI_AI_MASTER_KEY must be 64", "z" * 64),
        ({"EI_AI_MASTER_KEY_FILE": str(short)}, "EI_AI_MASTER_KEY_FILE must hold 64", "ab" * 31),
        ({"EI_AI_MASTER_KEY_FILE": missing}, "EI_AI_MASTER_KEY_FILE cannot be read", missing),
    ]
    for env, name, value in cases:
        with pytest.raises(SettingsError) as raised:
            master_key_from_env(env)
        message = str(raised.value)
        assert name in message
        assert (value not in message) if value else True
