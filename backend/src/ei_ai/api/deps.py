"""Shared FastAPI dependencies of the tenant routes."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ei_ai.db.tenant import tenant_session
from ei_ai.tenancy.context import TenantContext, require_tenant


async def tenant_db(
    request: Request, tenant: Annotated[TenantContext, Depends(require_tenant)]
) -> AsyncIterator[AsyncSession]:
    """A session inside a tenant transaction for the verified Organization (D46 layer 2)."""
    async with tenant_session(request.app.state.engine, tenant.org_id) as session:
        yield session


# scope="function": the transaction commits when the route function returns, before the response is
# sent. With the default request scope the commit would run after the response has started, and a
# failing commit could not change a 2xx the client has already received. Tenant routes must use
# this alias, not Depends(tenant_db) directly.
TenantSession = Annotated[AsyncSession, Depends(tenant_db, scope="function")]
