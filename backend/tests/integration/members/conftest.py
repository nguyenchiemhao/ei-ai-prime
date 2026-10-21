"""Fixtures of the members tests: Organizations with named people, removed afterwards."""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.rbac.orgs import PersonSpec, RoleOrg, create_role_org
from support.tenants import purge_org_ids

MakeOrg = Callable[..., Awaitable[RoleOrg]]

# A typical Organization: workspace x (and y) with one person per interesting role.
PEOPLE: Mapping[str, PersonSpec] = {
    "owner": ("org_owner", {}),
    "org_admin": ("org_admin", {}),
    "ws_admin": (None, {"x": "workspace_admin"}),
    "builder": (None, {"x": "builder"}),
    "viewer": (None, {"x": "viewer", "y": "viewer"}),
    "reviewer": (None, {"x": "reviewer"}),
    "member": (None, {"x": "member"}),
    "outsider": (None, {}),
}


@pytest.fixture
async def make_org(app_engine: AsyncEngine) -> AsyncIterator[MakeOrg]:
    """``await make_org(people, workspaces=("x", "y"))``; each Organization is purged afterwards."""
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
