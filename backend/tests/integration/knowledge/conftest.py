"""Fixtures of the knowledge tests: Organizations with a Knowledge Editor and a Workspace Admin."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.db.tenant import tenant_transaction
from ei_ai.rbac.access import WorkspaceAccess, load_workspace_access
from ei_ai.tenancy.context import TenantContext
from support.rbac.orgs import PersonSpec, RoleOrg, create_role_org
from support.tenants import purge_org_ids

MakeOrg = Callable[..., Awaitable[RoleOrg]]
Work = Callable[[Any, TenantContext, WorkspaceAccess], Awaitable[Any]]

PEOPLE: Mapping[str, PersonSpec] = {
    "ke": (None, {"x": "knowledge_editor"}),
    "ws_admin": (None, {"x": "workspace_admin", "y": "workspace_admin"}),
    "viewer": (None, {"x": "viewer"}),
}


@pytest.fixture
async def make_org(app_engine: AsyncEngine) -> AsyncIterator[MakeOrg]:
    """``await make_org()``; each Organization is purged afterwards."""
    created: list[RoleOrg] = []

    async def make(
        people: Mapping[str, PersonSpec] = PEOPLE, workspaces: Sequence[str] = ("x", "y")
    ) -> RoleOrg:
        org = await create_role_org(app_engine, people, workspaces)
        created.append(org)
        return org

    try:
        yield make
    finally:
        await purge_org_ids(app_engine, *(org.org_id for org in created))


async def run_as(
    engine: AsyncEngine, org: RoleOrg, actor: str, work: Work, workspace: str = "x"
) -> Any:
    """Run ``work`` in the actor's tenant transaction with the actor's real access object."""
    tenant = TenantContext(org_id=org.org_id, user_id=org.user(actor))
    async with engine.connect() as conn, tenant_transaction(conn, org.org_id):
        access = await load_workspace_access(conn, tenant, org.workspace(workspace))
        assert access is not None, f"{actor} cannot see workspace {workspace}"
        return await work(conn, tenant, access)
