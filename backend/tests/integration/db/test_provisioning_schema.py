"""Migration 0002 (FND-04): the constraints the provisioning code relies on.

Each case runs as the application role in a tenant transaction and is rolled back by the failure.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs, purge_org_ids

pytestmark = pytest.mark.integration

VALID_HASH = "a" * 64


async def _insert_org(engine: AsyncEngine, org_id: uuid.UUID, name: str) -> None:
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": org_id, "name": name},
        )


def _constraint(error: IntegrityError) -> str | None:
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


async def test_organization_names_are_unique_case_insensitively(app_engine: AsyncEngine) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    name = f"Org X {uuid.uuid4().hex[:8]}"
    try:
        await _insert_org(app_engine, first, name)

        with pytest.raises(IntegrityError) as error:
            await _insert_org(app_engine, second, name.lower())

        assert _constraint(error.value) == "organizations_name_lower_key"
    finally:
        await purge_org_ids(app_engine, first, second)


async def test_token_cannot_reference_other_org_user(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    with pytest.raises(IntegrityError):
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO set_password_tokens (org_id, user_id, token_hash, expires_at)"
                    " VALUES (:org, :user, :hash, now() + interval '24 hours')"
                ),
                {"org": two_orgs.a.org_id, "user": two_orgs.b.user_id, "hash": VALID_HASH},
            )


async def test_token_hash_must_be_64_lowercase_hex(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO set_password_tokens (org_id, user_id, token_hash, expires_at)"
                    " VALUES (:org, :user, :hash, now() + interval '24 hours')"
                ),
                {"org": two_orgs.a.org_id, "user": two_orgs.a.user_id, "hash": "Z" * 64},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"


async def test_audit_target_type_is_restricted(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                    " VALUES (:org, 'platform-operator', 'organization.created', 'secret', :id)"
                ),
                {"org": two_orgs.a.org_id, "id": two_orgs.a.org_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"


async def test_audit_action_must_be_a_dotted_code(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO audit_events (org_id, actor, action, target_type, target_id)"
                    " VALUES (:org, 'platform-operator', 'free text with spaces', 'user', :id)"
                ),
                {"org": two_orgs.a.org_id, "id": two_orgs.a.user_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23514"
