"""R1-6: the ORM models insert through the tenant session (RETURNING passes the policy)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.models import Membership, User
from ei_ai.db.tenant import tenant_session
from support.tenants import TwoOrgs

pytestmark = pytest.mark.integration


class _Discard(Exception):
    pass


async def test_a_user_and_its_membership_can_be_added_with_the_orm(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    org_id = two_orgs.a.org_id

    with pytest.raises(_Discard):
        async with tenant_session(app_engine, org_id) as session:
            user = User(org_id=org_id, email="orm.user@example.invalid", display_name="Orm User")
            session.add(user)
            await session.flush()  # INSERT ... RETURNING needs the SELECT policy to pass
            session.add(Membership(org_id=org_id, user_id=user.id))
            await session.flush()
            assert user.created_at is not None
            raise _Discard
