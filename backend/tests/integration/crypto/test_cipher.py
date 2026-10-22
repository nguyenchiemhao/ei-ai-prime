"""EA-20 AC3 and AC5 (database part): the cipher uses the verified context and the live key row."""

import asyncio
import base64
import logging
import os
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai import cli
from ei_ai.crypto.cipher import OrgCipher
from ei_ai.crypto.envelope import unwrap_data_key
from ei_ai.crypto.errors import (
    DecryptionFailed,
    KeyDestroyed,
    KeyNotFound,
    MasterKeyMismatch,
)
from ei_ai.crypto.lifecycle import destroy_org_key
from ei_ai.crypto.master_key import MasterKey
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_session, tenant_transaction
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext
from support.crypto import TEST_MASTER_KEY
from support.tenants import OrgRows, TwoOrgs, purge_org_ids

pytestmark = pytest.mark.integration

PLAINTEXT = b"confidential bytes \x00\xff of one Organization"
ORG_ID_LINE = re.compile(r"^Organization created: ([0-9a-f-]{36}) ", re.MULTILINE)


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


@pytest.fixture
def cipher() -> OrgCipher:
    return OrgCipher(TEST_MASTER_KEY)


async def test_encrypt_decrypt_round_trip_in_route_and_job_context(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    org = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        blob = await cipher.encrypt(conn, _tenant(org), PLAINTEXT)
        route_plain = await cipher.decrypt(conn, _tenant(org), blob)
    async with tenant_session(app_engine, org.org_id) as session:
        job = JobContext(org_id=org.org_id, session=session)
        job_blob = await cipher.encrypt(session, job, PLAINTEXT)
        job_plain = await cipher.decrypt(session, job, blob)

    assert blob.startswith(b"EIA\x01")
    assert PLAINTEXT not in blob
    assert blob != job_blob
    assert (route_plain, job_plain) == (PLAINTEXT, PLAINTEXT)
    assert len(blob) == len(PLAINTEXT) + 32


@pytest.mark.isolation
async def test_decrypt_with_another_orgs_context_fails_without_data(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        blob = await cipher.encrypt(conn, _tenant(a), PLAINTEXT)

    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        with pytest.raises(DecryptionFailed) as error:
            await cipher.decrypt(conn, _tenant(b), blob)

    assert PLAINTEXT.decode("latin-1") not in str(error.value)
    assert error.value.args == ("decryption failed",)


@pytest.mark.isolation
async def test_context_of_a_with_session_of_b_finds_no_key(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    a, b = two_orgs.a, two_orgs.b

    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        with pytest.raises(KeyNotFound):
            await cipher.encrypt(conn, _tenant(a), PLAINTEXT)
        with pytest.raises(KeyNotFound):
            await cipher.decrypt(conn, _tenant(a), b"EIA\x01" + bytes(40))


async def test_destroyed_key_blocks_encrypt_and_decrypt(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    a, b = two_orgs.a, two_orgs.b
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        blob = await cipher.encrypt(conn, _tenant(a), PLAINTEXT)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        first = await destroy_org_key(conn, a.org_id)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        second = await destroy_org_key(conn, a.org_id)

    assert (first, second) == (True, False)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        with pytest.raises(KeyDestroyed):
            await cipher.encrypt(conn, _tenant(a), PLAINTEXT)
        with pytest.raises(KeyDestroyed):
            await cipher.decrypt(conn, _tenant(a), blob)
        wrapped_is_null = (
            await conn.execute(
                text("SELECT wrapped_key IS NULL FROM organization_keys WHERE org_id = :org"),
                {"org": a.org_id},
            )
        ).scalar_one()
    assert wrapped_is_null is True
    async with app_engine.connect() as conn, tenant_transaction(conn, b.org_id):
        other = await cipher.decrypt(conn, _tenant(b), await cipher.encrypt(conn, _tenant(b), b"x"))
    assert other == b"x"


async def test_master_key_mismatch_is_reported(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    org = two_orgs.a
    wrong = OrgCipher(MasterKey(bytes(32)))
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        blob = await cipher.encrypt(conn, _tenant(org), PLAINTEXT)
        with pytest.raises(MasterKeyMismatch):
            await wrong.encrypt(conn, _tenant(org), PLAINTEXT)
        with pytest.raises(MasterKeyMismatch):
            await wrong.decrypt(conn, _tenant(org), blob)


async def test_cipher_rejects_a_raw_org_id(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, cipher: OrgCipher
) -> None:
    org = two_orgs.a
    async with app_engine.connect() as conn, tenant_transaction(conn, org.org_id):
        with pytest.raises(TypeError):
            await cipher.encrypt(conn, org.org_id, PLAINTEXT)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await cipher.decrypt(conn, org.org_id, b"EIA\x01")  # type: ignore[arg-type]


def _encodings(secret: bytes) -> list[str]:
    return [
        secret.hex(),
        secret.hex().upper(),
        base64.b64encode(secret).decode(),
        base64.urlsafe_b64encode(secret).decode(),
        repr(secret),
    ]


async def _purge(*org_ids: uuid.UUID) -> None:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))
    try:
        await purge_org_ids(engine, *org_ids)
    finally:
        await engine.dispose()


async def _dek_of(org_id: uuid.UUID, master: MasterKey) -> bytes:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            wrapped = (
                await conn.execute(
                    text("SELECT wrapped_key FROM organization_keys WHERE org_id = :org"),
                    {"org": org_id},
                )
            ).scalar_one()
        return unwrap_data_key(master, org_id, bytes(wrapped))
    finally:
        await engine.dispose()


async def _round_trip(org_id: uuid.UUID, master: MasterKey) -> None:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))
    try:
        cipher = OrgCipher(master)
        tenant = TenantContext(org_id=org_id, user_id=uuid.uuid4())
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            assert await cipher.decrypt(conn, tenant, await cipher.encrypt(conn, tenant, b"p"))
    finally:
        await engine.dispose()


def test_org_create_and_cipher_never_log_or_print_key_material(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    master = MasterKey(os.urandom(32))
    monkeypatch.setenv("EI_AI_MASTER_KEY", master.key.hex())
    monkeypatch.delenv("EI_AI_MASTER_KEY_FILE", raising=False)
    monkeypatch.delenv("ADMIN_BASE_URL", raising=False)
    sfx = uuid.uuid4().hex[:8]
    argv = ["org", "create", "--name", f"Leak {sfx}", "--owner", f"o.{sfx}@example.com"]

    with caplog.at_level(logging.DEBUG):
        code = cli.main(argv)
        out, err = capsys.readouterr()
        assert code == 0, err  # the CLI's own error line; it never carries key material
        match = ORG_ID_LINE.search(out)
        assert match is not None, "org create printed no org id line"
        org_id = uuid.UUID(match.group(1))
        try:
            dek = asyncio.run(_dek_of(org_id, master))
            asyncio.run(_round_trip(org_id, master))
            out2, err2 = capsys.readouterr()
            seen = "\n".join([out, err, out2, err2, caplog.text])
            leaked = [
                form for secret in (master.key, dek) for form in _encodings(secret) if form in seen
            ]
        finally:
            asyncio.run(_purge(org_id))

    any_leak = bool(leaked)  # a bool, so the failure output never shows the leaked forms
    assert not any_leak, "key material leaked"
