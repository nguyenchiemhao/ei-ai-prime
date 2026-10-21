"""Concurrent Organization-role changes keep at least one Org Owner and apply what was asked.

These tests really overlap: a pool of several connections, and a hook that holds the first
transaction open for a moment right after it took its locks (``HOLD``). With the ``FOR UPDATE`` of
``lock_owners_and_target`` removed, both transactions read the same owners and the first test
fails (recorded in the dev log).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from ei_ai.members import service
from ei_ai.members.rows import OrgRoleRow, lock_owners_and_target
from ei_ai.rbac.access import OrgAccess
from ei_ai.rbac.permissions import permissions_for
from ei_ai.tenancy.context import TenantContext
from support.rbac.orgs import RoleOrg, create_role_org
from support.sign_in import in_tenant
from support.tenants import purge_org_ids

pytestmark = pytest.mark.integration

HOLD = 0.4  # seconds a transaction keeps its locks after taking them
OWNER_ACCESS = OrgAccess("org_owner", permissions_for("org_owner", None))


@pytest.fixture
async def pooled_engine() -> AsyncIterator[AsyncEngine]:
    """Several connections, so two transactions can be open at the same time."""
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=4, max_overflow=0
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def hold_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every transaction open for ``HOLD`` seconds after its locks are taken."""

    async def locked_then_held(
        conn: object, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[OrgRoleRow]:
        rows = await lock_owners_and_target(conn, org_id, user_id)  # type: ignore[arg-type]
        await asyncio.sleep(HOLD)
        return rows

    monkeypatch.setattr(service, "lock_owners_and_target", locked_then_held)


async def _org(engine: AsyncEngine, people: dict[str, str | None]) -> RoleOrg:
    return await create_role_org(engine, {name: (role, {}) for name, role in people.items()})


def _change(
    engine: AsyncEngine, org: RoleOrg, actor: str, target: str, org_role: str | None
) -> Callable[[], Awaitable[str | None]]:
    """A service call in its own transaction; returns the role answered or the refusal code."""

    async def run() -> str | None:
        tenant = TenantContext(org_id=org.org_id, user_id=org.user(actor))
        try:
            async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
                return await service.change_org_role(
                    conn, tenant, OWNER_ACCESS, org.user(target), org_role
                )
        except service.LastOrgOwner:
            return "last_org_owner"

    return run


async def _owners(engine: AsyncEngine, org: RoleOrg) -> int:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT count(*) FROM memberships WHERE org_id = :org AND org_role = 'org_owner'",
    )
    count: int = rows[0][0]
    return count


async def test_two_owners_demoting_each_other_at_once_leave_one_owner(
    pooled_engine: AsyncEngine,
) -> None:
    org = await _org(pooled_engine, {"first": "org_owner", "second": "org_owner"})
    try:
        outcomes = await asyncio.gather(
            _change(pooled_engine, org, "second", "first", "org_admin")(),
            _change(pooled_engine, org, "first", "second", "org_admin")(),
        )

        assert sorted(str(o) for o in outcomes) == ["last_org_owner", "org_admin"]
        assert await _owners(pooled_engine, org) == 1
    finally:
        await purge_org_ids(pooled_engine, org.org_id)


async def test_a_promotion_racing_a_demotion_never_leaves_no_owner(
    pooled_engine: AsyncEngine,
) -> None:
    org = await _org(pooled_engine, {"owner": "org_owner", "other": "org_admin"})
    try:
        promoted, demoted = await asyncio.gather(
            _change(pooled_engine, org, "owner", "other", "org_owner")(),
            _change(pooled_engine, org, "owner", "owner", "org_admin")(),
        )

        assert promoted == "org_owner"
        assert demoted in ("org_admin", "last_org_owner")
        assert await _owners(pooled_engine, org) >= 1
    finally:
        await purge_org_ids(pooled_engine, org.org_id)


async def test_two_changes_of_one_user_at_once_both_apply_in_order(
    pooled_engine: AsyncEngine,
) -> None:
    """The second change is not dropped: it waits for the lock and then applies what it asked."""
    org = await _org(pooled_engine, {"one": "org_owner", "two": "org_owner", "target": None})
    try:
        outcomes = await asyncio.gather(
            _change(pooled_engine, org, "one", "target", "org_admin")(),
            _change(pooled_engine, org, "two", "target", "org_owner")(),
        )

        assert sorted(str(o) for o in outcomes) == ["org_admin", "org_owner"]
        events = await in_tenant(
            pooled_engine,
            org.org_id,
            "SELECT old_value, new_value FROM audit_events WHERE org_id = :org AND target_id = :t"
            " AND action = 'member.org_role_changed' ORDER BY id",
            {"t": org.user("target")},
        )
        assert len(events) == 2
        assert events[0][0] is None  # the first applied change started from no role
        assert events[1][0] == events[0][1]  # and the second one started where it ended
        final = await in_tenant(
            pooled_engine,
            org.org_id,
            "SELECT org_role FROM memberships WHERE org_id = :org AND user_id = :u",
            {"u": org.user("target")},
        )
        assert final == [(events[1][1],)]
    finally:
        await purge_org_ids(pooled_engine, org.org_id)
