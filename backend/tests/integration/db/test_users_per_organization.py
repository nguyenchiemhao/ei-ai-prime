"""R1-1: a user belongs to ONE Organization (owner decision 2026-10-14).

Pins the fix of the cross-tenant read of user data: tenant A can neither reference nor see the
users of tenant B, and a shared email is no oracle for another tenant's data.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


class _Discard(Exception):
    """Raised to roll the tenant transaction back instead of keeping the test rows."""


async def test_a_membership_cannot_reference_another_organizations_user(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b

    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO memberships (org_id, user_id, org_role)"
                    " VALUES (:org, :user, 'org_owner')"
                ),
                {"org": a.org_id, "user": b.user_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23503"
    assert f"User {b.label}" not in str(error.value)
    assert f"{b.user_id}@example.invalid" not in str(error.value)


async def test_a_membership_for_another_organization_is_rejected_by_the_policy(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b

    with pytest.raises(DBAPIError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text("INSERT INTO memberships (org_id, user_id) VALUES (:org, :user)"),
                {"org": b.org_id, "user": b.user_id},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "42501"
    assert f"{b.user_id}@example.invalid" not in str(error.value)


async def test_users_of_another_organization_are_invisible(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    async with app_engine.connect() as conn, tenant_transaction(conn, two_orgs.a.org_id):
        rows = (await conn.execute(text("SELECT id, email, display_name FROM users"))).all()

    assert [row.id for row in rows] == [two_orgs.a.user_id]
    assert all("User B" not in row.display_name for row in rows)


async def test_an_email_that_exists_only_in_another_organization_can_be_used(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    email_of_b = f"{b.user_id}@example.invalid"

    with pytest.raises(_Discard):
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            # No unique violation: an email is unique only inside an Organization, so there is no
            # way to learn that another Organization has it.
            await conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name)"
                    " VALUES (:id, :org, :email, 'Same Email')"
                ),
                {"id": uuid.uuid4(), "org": a.org_id, "email": email_of_b},
            )
            result = await conn.execute(
                text("SELECT count(*) FROM users WHERE email = :email"), {"email": email_of_b}
            )
            assert result.scalar_one() == 1
            raise _Discard


async def test_the_same_email_twice_in_one_organization_is_rejected(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a

    with pytest.raises(IntegrityError) as error:
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            await conn.execute(
                text(
                    "INSERT INTO users (org_id, email, display_name)"
                    " VALUES (:org, :email, 'Duplicate')"
                ),
                {"org": a.org_id, "email": f"{a.user_id}@example.invalid"},
            )

    assert getattr(error.value.orig, "sqlstate", None) == "23505"


async def test_a_user_of_the_same_organization_can_get_a_membership_and_be_deleted(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a

    with pytest.raises(_Discard):
        async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
            new_user = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name)"
                    " VALUES (:id, :org, 'new.person@example.invalid', 'New Person')"
                ),
                {"id": new_user, "org": a.org_id},
            )
            await conn.execute(
                text("INSERT INTO memberships (org_id, user_id) VALUES (:org, :user)"),
                {"org": a.org_id, "user": new_user},
            )
            await conn.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": new_user})
            deleted = await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": new_user})
            assert deleted.rowcount == 1
            raise _Discard
