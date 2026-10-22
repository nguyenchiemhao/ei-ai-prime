"""EA-20 AC2, AC3 and AC5 (file part): the file store keeps only ciphertext, per Organization."""

import secrets
import stat
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.crypto.errors import DecryptionFailed, KeyDestroyed
from ei_ai.crypto.lifecycle import destroy_org_key
from ei_ai.db.tenant import tenant_transaction
from ei_ai.storage.files import FileNotFound, OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

TEXT_SAMPLE = ("Hợp đồng bảo mật của một tổ chức. " * 20).encode()
WINDOW = 32


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


def _file_path(root: Path, org: OrgRows, file_id: uuid.UUID) -> Path:
    return root / str(org.org_id) / f"{file_id}.bin"


def _contains_plaintext_window(raw: bytes, plaintext: bytes) -> bool:
    """True when the raw bytes hold the plaintext or any 32-byte window of it. The result is a
    boolean, so a failing assertion never prints plaintext."""
    step = 1 if len(plaintext) < 4096 else 997
    starts = range(0, max(len(plaintext) - WINDOW, 0) + 1, step)
    return any(plaintext[i : i + WINDOW] in raw for i in starts)


@pytest.fixture
def store(tmp_path: Path) -> OrgFileStore:
    return OrgFileStore(tmp_path, OrgCipher(TEST_MASTER_KEY))


async def test_file_on_disk_is_unreadable_and_decrypts_byte_for_byte(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore, tmp_path: Path
) -> None:
    org = two_orgs.a
    for plaintext in (secrets.token_bytes(1024 * 1024), TEXT_SAMPLE):
        async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
            file_id = await store.put(conn, _tenant(org), plaintext)
            restored = await store.get(conn, _tenant(org), file_id)

        raw = _file_path(tmp_path, org, file_id).read_bytes()
        found = _contains_plaintext_window(raw, plaintext)
        assert raw.startswith(b"EIA\x01")
        assert len(raw) == len(plaintext) + 32
        assert not found, "plaintext found on disk"
        assert restored == plaintext, "decrypted file differs from the input"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
async def test_file_permissions_are_private(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore, tmp_path: Path
) -> None:
    org = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        file_id = await store.put(conn, _tenant(org), b"private")

    path = _file_path(tmp_path, org, file_id)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == [path.name], "temp file left behind"


@pytest.mark.isolation
async def test_other_orgs_file_id_is_not_found(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_file = await store.put(conn, _tenant(b), TEXT_SAMPLE)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        with pytest.raises(FileNotFound) as foreign:
            await store.get(conn, _tenant(a), b_file)
        with pytest.raises(FileNotFound) as unknown:
            await store.get(conn, _tenant(a), uuid.uuid4())

    assert foreign.value.args == unknown.value.args == ("file not found",)


@pytest.mark.isolation
async def test_foreign_blob_under_own_directory_fails_to_decrypt(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore, tmp_path: Path
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_file = await store.put(conn, _tenant(b), TEXT_SAMPLE)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        await store.put(conn, _tenant(a), b"make A's directory")
    planted = uuid.uuid4()
    _file_path(tmp_path, a, planted).write_bytes(_file_path(tmp_path, b, b_file).read_bytes())

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        with pytest.raises(DecryptionFailed):
            await store.get(conn, _tenant(a), planted)


async def test_destroyed_key_makes_files_unreadable(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        a_file = await store.put(conn, _tenant(a), TEXT_SAMPLE)
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_file = await store.put(conn, _tenant(b), TEXT_SAMPLE)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        assert await destroy_org_key(conn, a.org_id)

    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        with pytest.raises(KeyDestroyed):
            await store.get(conn, _tenant(a), a_file)
        with pytest.raises(KeyDestroyed):
            await store.put(conn, _tenant(a), TEXT_SAMPLE)
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        assert await store.get(conn, _tenant(b), b_file) == TEXT_SAMPLE


async def test_delete_removes_only_own_file(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore, tmp_path: Path
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        a_file = await store.put(conn, _tenant(a), b"a")
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        b_file = await store.put(conn, _tenant(b), b"b")

    cross = await store.delete(_tenant(a), b_file)
    own = await store.delete(_tenant(a), a_file)
    again = await store.delete(_tenant(a), a_file)

    assert (cross, own, again) == (False, True, False)
    assert _file_path(tmp_path, b, b_file).exists()
    assert not _file_path(tmp_path, a, a_file).exists()


async def test_store_rejects_non_uuid_ids(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, store: OrgFileStore
) -> None:
    org = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        with pytest.raises(TypeError):
            await store.get(conn, _tenant(org), "../x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await store.get(conn, org.org_id, uuid.uuid4())  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await store.put(conn, org.org_id, b"x")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await store.delete(_tenant(org), "../x")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await store.delete(org.org_id, uuid.uuid4())  # type: ignore[arg-type]
