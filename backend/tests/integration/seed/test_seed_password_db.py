"""The shared test password of the demo seed on the real database (EA-94 AC1, AC5, AC6; R25).

Variants of the manifests (random ids, their own email domains) are seeded with a test value of
``EI_AI_SEED_PASSWORD`` and purged afterwards.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai import cli
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.passwords import check_policy, verify_password
from ei_ai.auth.set_password import format_token, issue_token
from ei_ai.auth.sign_in import sign_in
from ei_ai.db.tenant import tenant_transaction
from ei_ai.seed.demo import DemoManifest, SeedResult, seed_manifest
from ei_ai.seed.manifest import SYSADMIN_EMAIL, load_manifests
from ei_ai.seed.summary import format_summary
from support.seed import TEST_SEED_PASSWORD
from support.sign_in import give_password, in_tenant, request_headers
from support.tenants import DELETE_ORDER, count_org_rows

pytestmark = pytest.mark.integration

SHORT_PASSWORD = "Short@12"


async def _seed_all(engine: AsyncEngine, manifests: tuple[DemoManifest, ...]) -> list[SeedResult]:
    return [await seed_manifest(engine, m, TEST_SEED_PASSWORD) for m in manifests]


def _email(manifest: DemoManifest, name: str) -> str:
    return next(member.email for member in manifest.members if member.name == name)


def _sysadmin(manifest: DemoManifest) -> str:
    local = SYSADMIN_EMAIL.split("@", 1)[0]
    return next(m.email for m in manifest.members if m.email.startswith(f"{local}@"))


async def _user_id(engine: AsyncEngine, org_id: uuid.UUID, email: str) -> uuid.UUID:
    rows = await in_tenant(
        engine,
        org_id,
        "SELECT id FROM users WHERE org_id = :org AND email = :email",
        {"email": email},
    )
    user_id: uuid.UUID = rows[0][0]
    return user_id


async def _hashes(engine: AsyncEngine, org_id: uuid.UUID) -> dict[str, str]:
    rows = await in_tenant(
        engine,
        org_id,
        "SELECT u.email, c.password_hash FROM user_credentials c"
        " JOIN users u ON u.org_id = c.org_id AND u.id = c.user_id WHERE c.org_id = :org",
    )
    return {row.email: row.password_hash for row in rows}


async def test_no_set_password_token_is_issued(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    await _seed_all(app_engine, variants)

    for manifest in variants:
        org_id = manifest.organization_id
        links = await in_tenant(
            app_engine,
            org_id,
            "SELECT count(*) FROM audit_events WHERE org_id = :org"
            " AND action = 'user.set_password_link_issued'",
        )
        assert (await count_org_rows(app_engine, org_id))["set_password_tokens"] == 0
        assert links[0][0] == 0


async def test_changed_password_is_kept(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD)
    linh = _email(mekong, "Linh Tran")
    await give_password(app_engine, org_id, await _user_id(app_engine, org_id, linh))
    changed = await _hashes(app_engine, org_id)

    result = await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD)

    assert await _hashes(app_engine, org_id) == changed
    assert not await verify_password(changed[linh], TEST_SEED_PASSWORD)
    assert result.passwords_applied == 0
    assert result.audit_events == 0
    events = await in_tenant(
        app_engine,
        org_id,
        "SELECT count(*) FROM audit_events WHERE org_id = :org AND action = 'user.password_set'",
    )
    assert events[0][0] == 10


async def test_credentials_are_argon2_with_distinct_salts(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    await _seed_all(app_engine, variants)
    hashes = [
        password_hash
        for manifest in variants
        for password_hash in (await _hashes(app_engine, manifest.organization_id)).values()
    ]

    assert len(hashes) == 11
    assert all(password_hash.startswith("$argon2id$") for password_hash in hashes)
    assert len(set(hashes)) == len(hashes)
    for password_hash in hashes:
        assert await verify_password(password_hash, TEST_SEED_PASSWORD)


async def test_output_and_audit_never_contain_the_password(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    first = await _seed_all(app_engine, variants)
    second = await _seed_all(app_engine, variants)
    outputs = [
        format_summary(manifest, result)
        for results in (first, second)
        for manifest, result in zip(variants, results, strict=True)
    ]

    for text_out in [*outputs, *(repr(result) for result in first + second)]:
        assert TEST_SEED_PASSWORD not in text_out
        assert "$argon2" not in text_out
    for manifest in variants:
        rows = await in_tenant(
            app_engine,
            manifest.organization_id,
            "SELECT e::text AS line FROM audit_events e WHERE e.org_id = :org",
        )
        assert rows
        assert not any(TEST_SEED_PASSWORD in row.line for row in rows)
        assert not any("$argon2" in row.line for row in rows)


async def test_sysadmin_has_a_credential_only_in_mekong(
    app_engine: AsyncEngine, variants: tuple[DemoManifest, ...]
) -> None:
    mekong, song_han = variants
    await _seed_all(app_engine, variants)

    mekong_hashes = await _hashes(app_engine, mekong.organization_id)
    song_han_hashes = await _hashes(app_engine, song_han.organization_id)
    song_han_owner = await in_tenant(
        app_engine,
        song_han.organization_id,
        "SELECT m.org_role FROM memberships m JOIN users u"
        " ON u.org_id = m.org_id AND u.id = m.user_id"
        " WHERE m.org_id = :org AND u.email = :email",
        {"email": _sysadmin(song_han)},
    )

    assert _sysadmin(mekong) == _sysadmin(song_han)
    assert _sysadmin(mekong) in mekong_hashes
    assert set(song_han_hashes) == {_email(song_han, "Ngân Trịnh")}
    assert [row.org_role for row in song_han_owner] == ["org_owner"]


async def test_seeded_accounts_sign_in_and_land_on_their_default_workspace(
    app_engine: AsyncEngine, directory: SignInDirectory, variants: tuple[DemoManifest, ...]
) -> None:
    mekong, song_han = variants
    first, second = await _seed_all(app_engine, variants)
    people_ops, engineering = (ws_id for _, ws_id, _ in first.workspaces)
    customer_care = second.workspaces[0][1]
    expected = [
        (_email(mekong, "Linh Tran"), mekong.organization_id, people_ops),
        (_email(mekong, "Duy Lâm"), mekong.organization_id, people_ops),
        (_email(mekong, "Quang Le"), mekong.organization_id, people_ops),
        (_email(mekong, "Vy Huỳnh"), mekong.organization_id, engineering),
        (_sysadmin(mekong), mekong.organization_id, people_ops),
        (_email(song_han, "Ngân Trịnh"), song_han.organization_id, customer_care),
    ]

    for email, org_id, workspace_id in expected:
        signed_in = await sign_in(app_engine, directory, email, TEST_SEED_PASSWORD, None)

        assert signed_in is not None, email
        assert (signed_in.org_id, signed_in.default_workspace_id) == (org_id, workspace_id), email


async def test_seed_password_does_not_fall_through_to_the_second_org(
    app_engine: AsyncEngine, directory: SignInDirectory, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await _seed_all(app_engine, variants)
    sysadmin = _sysadmin(mekong)
    await give_password(app_engine, org_id, await _user_id(app_engine, org_id, sysadmin))

    signed_in = await sign_in(app_engine, directory, sysadmin, TEST_SEED_PASSWORD, None)

    assert signed_in is None


async def test_policy_still_rejects_the_short_seed_password(
    app_engine: AsyncEngine, client: httpx.AsyncClient, variants: tuple[DemoManifest, ...]
) -> None:
    mekong = variants[0]
    org_id = mekong.organization_id
    await seed_manifest(app_engine, mekong, TEST_SEED_PASSWORD)
    user_id = await _user_id(app_engine, org_id, _email(mekong, "Minh Pham"))
    async with app_engine.connect() as conn, tenant_transaction(conn, org_id):
        secret = await issue_token(conn, org_id, user_id)

    response = await client.post(
        "/auth/set-password",
        json={"token": format_token(org_id, secret), "password": SHORT_PASSWORD},
        headers=request_headers(),
    )

    assert check_policy(SHORT_PASSWORD) == "password_too_short"
    assert response.status_code == 422
    assert response.json() == {"detail": "password_too_short"}


async def test_missing_password_exits_1_before_the_database(
    app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("EI_AI_ENV", "test")
    monkeypatch.delenv("EI_AI_SEED_PASSWORD", raising=False)
    org_ids = [manifest.organization_id for manifest in load_manifests()]
    before = [await count_org_rows(app_engine, org_id) for org_id in org_ids]

    code = cli.main(["seed", "demo"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "configuration error: EI_AI_SEED_PASSWORD is required\n"
    assert [await count_org_rows(app_engine, org_id) for org_id in org_ids] == before
    assert set(before[0]) == set(DELETE_ORDER)
