"""The provisioning service against the real database as ``ei_ai_app`` (FND-04 AC1, AC2, AC4).

Names carry a random suffix: CI runs these tests on a seeded database. Every Organization a test
creates is removed with ``purge_org_ids`` through the application role.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import record_event
from ei_ai.auth.set_password import hash_secret
from ei_ai.db.tenant import tenant_transaction
from ei_ai.provisioning import service
from ei_ai.provisioning.service import (
    AddedMember,
    add_workspace_member,
    create_organization,
    create_workspace,
    invite_user,
    issue_link,
)
from ei_ai.provisioning.validation import ProvisioningError
from support.crypto import TEST_MASTER_KEY
from support.tenants import (
    DELETE_ORDER,
    TwoOrgs,
    count_org_rows,
    purge_org_ids,
)

pytestmark = pytest.mark.integration

ACTOR = "platform-operator"


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def created(app_engine: AsyncEngine) -> AsyncIterator[list[uuid.UUID]]:
    """Organization ids a test created; purged afterwards."""
    ids: list[uuid.UUID] = []
    try:
        yield ids
    finally:
        await purge_org_ids(app_engine, *ids)


async def _rows(engine: AsyncEngine, org_id: uuid.UUID, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        return list((await conn.execute(text(sql), {"org": org_id, **params})).all())


async def _events(engine: AsyncEngine, org_id: uuid.UUID) -> list[tuple[str, str, str, uuid.UUID]]:
    rows = await _rows(
        engine,
        org_id,
        "SELECT actor, action, target_type, target_id FROM audit_events WHERE org_id = :org",
    )
    return sorted(tuple(row) for row in rows)


async def _new_org(
    engine: AsyncEngine, created: list[uuid.UUID], **kwargs: Any
) -> service.CreatedOrganization:
    sfx = _suffix()
    result = await create_organization(
        engine,
        name=kwargs.pop("name", f"Prov {sfx}"),
        owner_email=kwargs.pop("owner_email", f"Owner.{sfx}@Example.com"),
        master=TEST_MASTER_KEY,
        **kwargs,
    )
    created.append(result.org_id)
    return result


async def test_create_organization_creates_org_workspace_owner_and_token(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    result = await _new_org(
        app_engine, created, name=f"  Prov {sfx}  ", owner_email=f" Owner.{sfx}@Example.com "
    )
    org = result.org_id

    assert result.org_name == f"Prov {sfx}"
    assert result.workspace_name == "Default"
    assert result.owner_email == f"owner.{sfx}@example.com"
    assert await _rows(app_engine, org, "SELECT id, name FROM organizations WHERE id = :org") == [
        (org, f"Prov {sfx}")
    ]
    assert await _rows(app_engine, org, "SELECT id, name FROM workspaces WHERE org_id = :org") == [
        (result.workspace_id, "Default")
    ]
    assert await _rows(
        app_engine, org, "SELECT id, email, display_name FROM users WHERE org_id = :org"
    ) == [(result.owner_id, f"owner.{sfx}@example.com", f"owner.{sfx}")]
    assert await _rows(
        app_engine, org, "SELECT user_id, org_role FROM memberships WHERE org_id = :org"
    ) == [(result.owner_id, "org_owner")]
    assert await _rows(
        app_engine,
        org,
        "SELECT workspace_id, user_id, role FROM workspace_memberships WHERE org_id = :org",
    ) == [(result.workspace_id, result.owner_id, "workspace_admin")]
    assert await count_org_rows(app_engine, org) == {
        "chunk_embeddings": 0,
        "admin_sessions": 0,
        "user_credentials": 0,
        "audit_events": 5,
        "set_password_tokens": 1,
        "workspace_memberships": 1,
        "memberships": 1,
        "workspaces": 1,
        "users": 1,
        "model_catalog": 0,
        "organization_keys": 1,
        "collections": 0,
        "folders": 0,
        "documents": 0,
        "document_chunks": 0,
        "organizations": 1,
    }


async def test_owner_name_and_workspace_name_options(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    result = await _new_org(
        app_engine, created, owner_name="  Linh Tran ", workspace_name=" People Ops "
    )

    assert result.workspace_name == "People Ops"
    assert await _rows(
        app_engine, result.org_id, "SELECT display_name FROM users WHERE org_id = :org"
    ) == [("Linh Tran",)]


async def test_token_expires_24h_after_creation(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    result = await _new_org(app_engine, created)

    assert await _rows(
        app_engine,
        result.org_id,
        "SELECT user_id, expires_at - created_at = interval '24 hours', used_at IS NULL"
        " FROM set_password_tokens WHERE org_id = :org",
    ) == [(result.owner_id, True, True)]


async def test_only_the_hash_is_stored(app_engine: AsyncEngine, created: list[uuid.UUID]) -> None:
    result = await _new_org(app_engine, created)

    hashes = await _rows(
        app_engine, result.org_id, "SELECT token_hash FROM set_password_tokens WHERE org_id = :org"
    )
    raw = await _rows(
        app_engine,
        result.org_id,
        "SELECT count(*) FROM set_password_tokens t WHERE t.org_id = :org"
        " AND strpos(t::text, :secret) > 0",
        secret=result.secret,
    )

    assert hashes == [(hash_secret(result.secret),)]
    assert raw == [(0,)]


async def test_duplicate_name_case_and_space_insensitive(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    first = await _new_org(app_engine, created, name=f"X {sfx}")
    captured: list[uuid.UUID] = []
    real_new_org_id = service.new_org_id

    async def spy(engine: AsyncEngine) -> uuid.UUID:
        captured.append(await real_new_org_id(engine))
        created.append(captured[-1])
        return captured[-1]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "new_org_id", spy)
        with pytest.raises(ProvisioningError) as error:
            await create_organization(
                app_engine, name=f" x {sfx} ", owner_email="o@example.com", master=TEST_MASTER_KEY
            )

    assert str(error.value) == "an Organization with this name already exists"
    assert await count_org_rows(app_engine, captured[0]) == dict.fromkeys(DELETE_ORDER, 0)
    assert (await count_org_rows(app_engine, first.org_id))["organizations"] == 1


async def test_invalid_input_never_touches_the_database(app_engine: AsyncEngine) -> None:
    class _NoEngine:
        def connect(self) -> None:
            raise AssertionError("invalid input must be rejected before any database access")

    engine: Any = _NoEngine()
    cases = [
        (
            create_organization(
                engine, name=" ", owner_email="o@example.com", master=TEST_MASTER_KEY
            ),
            "Organization name",
        ),
        (
            create_organization(
                engine, name="Valid", owner_email="not-an-email", master=TEST_MASTER_KEY
            ),
            "invalid email",
        ),
        (
            create_organization(
                engine,
                name="Valid",
                owner_email="o@example.com",
                owner_name="",
                master=TEST_MASTER_KEY,
            ),
            "display name",
        ),
        (
            create_organization(
                engine,
                name="Valid",
                owner_email="o@example.com",
                workspace_name=" ",
                master=TEST_MASTER_KEY,
            ),
            "Workspace name",
        ),
        (create_workspace(engine, uuid.uuid4(), ""), "Workspace name"),
        (invite_user(engine, uuid.uuid4(), "a b@c.example", ["builder"]), "invalid email"),
        (invite_user(engine, uuid.uuid4(), "a@c.example", ["boss"]), "unknown role"),
        (invite_user(engine, uuid.uuid4(), "a@c.example", ["builder"]), "needs --workspace"),
        (
            invite_user(engine, uuid.uuid4(), "a@c.example", ["org_admin"], uuid.uuid4()),
            "needs a Workspace role",
        ),
        (
            invite_user(engine, uuid.uuid4(), "a@c.example", ["org_admin"], display_name=" "),
            "display name",
        ),
        (issue_link(engine, uuid.uuid4(), "linh@"), "invalid email"),
    ]
    for call, message in cases:
        with pytest.raises(ProvisioningError) as error:
            await call
        assert message in str(error.value)


async def test_e13_and_e14_messages() -> None:
    engine: Any = None
    with pytest.raises(ProvisioningError) as e13:
        await invite_user(engine, uuid.uuid4(), "a@c.example", ["viewer"])
    with pytest.raises(ProvisioningError) as e14:
        await invite_user(engine, uuid.uuid4(), "a@c.example", [], uuid.uuid4())

    assert str(e13.value) == "a Workspace role needs --workspace"
    assert str(e14.value) == "--workspace needs a Workspace role"


async def test_failure_after_inserts_rolls_back_everything(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    captured: list[uuid.UUID] = []
    real_new_org_id = service.new_org_id
    real_record = record_event
    calls = 0

    async def spy(engine: AsyncEngine) -> uuid.UUID:
        captured.append(await real_new_org_id(engine))
        created.append(captured[-1])
        return captured[-1]

    async def failing_third(*args: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("injected failure after every insert")
        await real_record(*args)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(service, "new_org_id", spy)
        patch.setattr(service, "record_event", failing_third)
        with pytest.raises(RuntimeError):
            await create_organization(
                app_engine,
                name=f"Rollback {_suffix()}",
                owner_email="o@example.com",
                master=TEST_MASTER_KEY,
            )

    assert calls == 3
    assert await count_org_rows(app_engine, captured[0]) == dict.fromkeys(DELETE_ORDER, 0)


async def test_each_command_writes_its_audit_events(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)
    assert await _events(app_engine, org.org_id) == sorted(
        [
            (ACTOR, "organization.created", "organization", org.org_id),
            (ACTOR, "workspace.created", "workspace", org.workspace_id),
            (ACTOR, "user.invited", "user", org.owner_id),
            (ACTOR, "member.org_role_changed", "user", org.owner_id),
            (ACTOR, "member.workspace_role_changed", "user", org.owner_id),
        ]
    )
    before = await _events(app_engine, org.org_id)

    workspace = await create_workspace(app_engine, org.org_id, f"  Second {sfx} ")
    builder = await invite_user(
        app_engine, org.org_id, f"Builder.{sfx}@example.com", ["builder"], workspace.workspace_id
    )
    admin = await invite_user(app_engine, org.org_id, f"admin.{sfx}@example.com", ["org_admin"])
    link = await issue_link(app_engine, org.org_id, f" BUILDER.{sfx}@example.com")

    assert workspace.name == f"Second {sfx}"
    assert builder.email == f"builder.{sfx}@example.com"
    assert builder.roles == ("builder",)
    assert link.user_id == builder.user_id
    assert await _events(app_engine, org.org_id) == sorted(
        [
            *before,
            (ACTOR, "workspace.created", "workspace", workspace.workspace_id),
            (ACTOR, "user.invited", "user", builder.user_id),
            (ACTOR, "member.workspace_role_changed", "user", builder.user_id),
            (ACTOR, "user.invited", "user", admin.user_id),
            (ACTOR, "member.org_role_changed", "user", admin.user_id),
            (ACTOR, "user.set_password_link_issued", "user", builder.user_id),
        ]
    )


async def test_create_organization_audits_the_founding_owners_roles(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    org = await _new_org(app_engine, created)

    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT actor, action, workspace_id, old_value, new_value FROM audit_events"
        " WHERE org_id = :org AND target_id = :user AND action LIKE 'member.%'"
        " ORDER BY action",
        user=org.owner_id,
    ) == [
        (ACTOR, "member.org_role_changed", None, None, "org_owner"),
        (ACTOR, "member.workspace_role_changed", org.workspace_id, None, "workspace_admin"),
    ]


async def test_invite_audits_each_role_with_its_workspace_and_no_old_value(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)

    invited = await invite_user(
        app_engine,
        org.org_id,
        f"both.{sfx}@example.com",
        ["org_admin", "reviewer"],
        org.workspace_id,
    )

    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT action, workspace_id, old_value, new_value FROM audit_events"
        " WHERE org_id = :org AND target_id = :user AND action LIKE 'member.%'"
        " ORDER BY action",
        user=invited.user_id,
    ) == [
        ("member.org_role_changed", None, None, "org_admin"),
        ("member.workspace_role_changed", org.workspace_id, None, "reviewer"),
    ]


async def test_invite_without_roles_writes_no_role_event(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)

    invited = await invite_user(app_engine, org.org_id, f"plain.{sfx}@example.com", [])

    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT count(*) FROM audit_events WHERE org_id = :org AND target_id = :user"
        " AND action LIKE 'member.%'",
        user=invited.user_id,
    ) == [(0,)]


async def test_invite_writes_user_membership_workspace_membership_and_token(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)

    invited = await invite_user(
        app_engine,
        org.org_id,
        f"lead.{sfx}@example.com",
        ["workspace_admin", "org_admin"],
        org.workspace_id,
        display_name=" Lead ",
    )

    assert invited.roles == ("org_admin", "workspace_admin")
    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT u.display_name, m.org_role, w.role FROM users u"
        " JOIN memberships m ON m.org_id = u.org_id AND m.user_id = u.id"
        " JOIN workspace_memberships w ON w.org_id = u.org_id AND w.user_id = u.id"
        " WHERE u.org_id = :org AND u.id = :user",
        user=invited.user_id,
    ) == [("Lead", "org_admin", "workspace_admin")]
    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT token_hash FROM set_password_tokens WHERE org_id = :org AND user_id = :user",
        user=invited.user_id,
    ) == [(hash_secret(invited.secret),)]


async def test_issue_link_replaces_the_unused_token(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    org = await _new_org(app_engine, created)

    link = await issue_link(app_engine, org.org_id, org.owner_email)

    assert link.secret != org.secret
    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT token_hash FROM set_password_tokens WHERE org_id = :org AND used_at IS NULL",
    ) == [(hash_secret(link.secret),)]


async def test_failed_command_writes_no_audit_event(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)
    await create_workspace(app_engine, org.org_id, f"Second {sfx}")
    before = await count_org_rows(app_engine, org.org_id)

    failures = [
        (create_workspace(app_engine, org.org_id, f"Second {sfx}"), "a Workspace with this"),
        (
            invite_user(app_engine, org.org_id, org.owner_email, ["viewer"], org.workspace_id),
            "a user",
        ),
        (issue_link(app_engine, org.org_id, f"nobody.{sfx}@example.com"), "user not found"),
        (
            invite_user(app_engine, org.org_id, f"n.{sfx}@example.com", ["viewer"], uuid.uuid4()),
            "Workspace not found",
        ),
    ]
    for call, message in failures:
        with pytest.raises(ProvisioningError) as error:
            await call
        assert message in str(error.value)

    assert await count_org_rows(app_engine, org.org_id) == before


async def test_duplicate_owner_email_in_invite_writes_nothing(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    org = await _new_org(app_engine, created)
    before = await count_org_rows(app_engine, org.org_id)

    with pytest.raises(ProvisioningError) as error:
        await invite_user(app_engine, org.org_id, org.owner_email.upper(), ["org_admin"])

    assert str(error.value) == "a user with this email already exists in this Organization"
    assert await count_org_rows(app_engine, org.org_id) == before


async def test_duplicate_workspace_name_is_e6(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    org = await _new_org(app_engine, created)

    with pytest.raises(ProvisioningError) as error:
        await create_workspace(app_engine, org.org_id, " Default ")

    assert str(error.value) == "a Workspace with this name already exists in this Organization"


async def test_unknown_organization_is_e8(app_engine: AsyncEngine) -> None:
    unknown = uuid.uuid4()
    calls = [
        create_workspace(app_engine, unknown, "W"),
        invite_user(app_engine, unknown, "a@example.com", ["org_admin"]),
        issue_link(app_engine, unknown, "a@example.com"),
    ]
    for call in calls:
        with pytest.raises(ProvisioningError) as error:
            await call
        assert str(error.value) == "Organization not found"
    assert await count_org_rows(app_engine, unknown) == dict.fromkeys(DELETE_ORDER, 0)


async def test_invite_with_other_org_workspace_is_not_found(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    before_a, before_b = (
        await count_org_rows(app_engine, a.org_id),
        await count_org_rows(app_engine, b.org_id),
    )

    with pytest.raises(ProvisioningError) as error:
        await invite_user(
            app_engine, a.org_id, f"x.{_suffix()}@example.com", ["builder"], b.workspace_id
        )

    assert str(error.value) == "Workspace not found in this Organization"
    assert await count_org_rows(app_engine, a.org_id) == before_a
    assert await count_org_rows(app_engine, b.org_id) == before_b


async def test_issue_link_for_other_org_email_is_not_found(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    before_a, before_b = (
        await count_org_rows(app_engine, a.org_id),
        await count_org_rows(app_engine, b.org_id),
    )
    b_tokens = await _rows(
        app_engine, b.org_id, "SELECT token_hash FROM set_password_tokens WHERE org_id = :org"
    )

    with pytest.raises(ProvisioningError) as error:
        await issue_link(app_engine, a.org_id, b.email)

    assert str(error.value) == "user not found in this Organization"
    assert await count_org_rows(app_engine, a.org_id) == before_a
    assert await count_org_rows(app_engine, b.org_id) == before_b
    assert (
        await _rows(
            app_engine, b.org_id, "SELECT token_hash FROM set_password_tokens WHERE org_id = :org"
        )
        == b_tokens
    )


async def test_audit_rows_hold_no_token_or_email(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)
    invited = await invite_user(app_engine, org.org_id, f"m.{sfx}@example.com", ["org_admin"])
    link = await issue_link(app_engine, org.org_id, invited.email)

    for needle in (org.secret, invited.secret, link.secret, org.owner_email, invited.email, "@"):
        hits = await _rows(
            app_engine,
            org.org_id,
            "SELECT count(*) FROM audit_events e WHERE e.org_id = :org"
            " AND strpos(lower(e::text), lower(:needle)) > 0",
            needle=needle,
        )
        assert hits == [(0,)], needle


async def test_add_member_adds_the_workspace_membership_and_audit_event(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)
    second = await create_workspace(app_engine, org.org_id, f"Second {sfx}")
    invited = await invite_user(app_engine, org.org_id, f"m.{sfx}@example.com", ["org_admin"])
    before = await _events(app_engine, org.org_id)

    added = await add_workspace_member(
        app_engine, org.org_id, second.workspace_id, f" M.{sfx}@Example.com ", "viewer"
    )

    assert added == AddedMember(invited.user_id, f"m.{sfx}@example.com", "viewer")
    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT workspace_id, user_id, role FROM workspace_memberships"
        " WHERE org_id = :org AND user_id = :user",
        user=invited.user_id,
    ) == [(second.workspace_id, invited.user_id, "viewer")]
    assert await _events(app_engine, org.org_id) == sorted(
        [
            *before,
            (ACTOR, "workspace.member_added", "user", invited.user_id),
            (ACTOR, "member.workspace_role_changed", "user", invited.user_id),
        ]
    )
    assert await _rows(
        app_engine,
        org.org_id,
        "SELECT workspace_id, old_value, new_value FROM audit_events"
        " WHERE org_id = :org AND action = 'member.workspace_role_changed' AND target_id = :user",
        user=invited.user_id,
    ) == [(second.workspace_id, None, "viewer")]


async def test_add_member_errors_write_nothing(
    app_engine: AsyncEngine, created: list[uuid.UUID]
) -> None:
    sfx = _suffix()
    org = await _new_org(app_engine, created)
    second = await create_workspace(app_engine, org.org_id, f"Second {sfx}")
    before = await count_org_rows(app_engine, org.org_id)
    ws, email = second.workspace_id, org.owner_email

    failures = [
        (add_workspace_member(app_engine, uuid.uuid4(), ws, email, "viewer"), "Organization not"),
        (
            add_workspace_member(app_engine, org.org_id, uuid.uuid4(), email, "viewer"),
            "Workspace not found in this Organization",
        ),
        (
            add_workspace_member(app_engine, org.org_id, ws, f"nobody.{sfx}@example.com", "viewer"),
            "user not found in this Organization",
        ),
        (
            add_workspace_member(app_engine, org.org_id, org.workspace_id, email, "viewer"),
            "the user is already a member of this Workspace",
        ),
        (add_workspace_member(app_engine, org.org_id, ws, email, "org_admin"), "--role must be"),
        (add_workspace_member(app_engine, org.org_id, ws, email, "boss"), "unknown role"),
        (add_workspace_member(app_engine, org.org_id, ws, "a@b", "viewer"), "invalid email"),
    ]
    for call, message in failures:
        with pytest.raises(ProvisioningError) as error:
            await call
        assert message in str(error.value)

    assert await count_org_rows(app_engine, org.org_id) == before


async def test_add_member_cannot_use_another_org_user_or_workspace(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    before_a, before_b = (
        await count_org_rows(app_engine, a.org_id),
        await count_org_rows(app_engine, b.org_id),
    )

    with pytest.raises(ProvisioningError) as workspace_error:
        await add_workspace_member(app_engine, a.org_id, b.workspace_id, a.email, "viewer")
    with pytest.raises(ProvisioningError) as user_error:
        await add_workspace_member(app_engine, a.org_id, a.workspace_id, b.email, "viewer")

    assert str(workspace_error.value) == "Workspace not found in this Organization"
    assert str(user_error.value) == "user not found in this Organization"
    assert await count_org_rows(app_engine, a.org_id) == before_a
    assert await count_org_rows(app_engine, b.org_id) == before_b
