"""How a route declares its permission (D48), checked before the route body runs.

Every route uses exactly one of these dependencies. The declaration travels on the dependency
(``__ei_declaration__``), so the CI guard in ``tests/support/rbac`` reads it from the real route
table and fails when a route has none or when it differs from the reviewed table.

* ``requires(permission)``: a Workspace route (path parameter ``workspace_id``). A caller who
  cannot see the Workspace gets 404 ``not_found``, identical to an unknown id; a caller who sees
  it but lacks the permission gets 403 ``forbidden``.
* ``requires_org(permission)``: an Organization route; 403 ``forbidden`` without it.
* ``signed_in()``: a session is enough (the caller's own data).
* ``public(reason)``: no identity (probes, sign-in).

The service layer calls ``ensure`` again, so a service called from another entry point is checked
too. Nothing here reads a role, permission or Organization from the request (D32).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ei_ai.api.deps import TenantSession
from ei_ai.rbac.access import (
    OrgAccess,
    PermissionDenied,
    WorkspaceAccess,
    load_org_access,
    load_workspace_access,
)
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import TenantContext, require_tenant

NOT_FOUND = "not_found"
FORBIDDEN = "forbidden"

DECLARATION_ATTR = "__ei_declaration__"
SIGNED_IN = "signed_in"
PUBLIC = "public"


def declared(call: object) -> str | None:
    """The declaration a dependency carries: a permission code, ``signed_in`` or ``public``."""
    value = getattr(call, DECLARATION_ATTR, None)
    return value if isinstance(value, str) else None


def _declare[F: Callable[..., Any]](call: F, declaration: str) -> F:
    setattr(call, DECLARATION_ATTR, declaration)
    return call


def _scope_check(permission: Permission, scope: str) -> None:
    if permission.scope != scope:
        raise ValueError(f"{permission.value} is a {permission.scope} permission, not {scope}")


def requires(
    permission: Permission,
) -> Callable[..., Awaitable[WorkspaceAccess]]:
    """Dependency of a Workspace route; returns the caller's ``WorkspaceAccess``."""
    _scope_check(permission, "workspace")

    async def check(
        workspace_id: uuid.UUID,
        tenant: Annotated[TenantContext, Depends(require_tenant)],
        session: TenantSession,
    ) -> WorkspaceAccess:
        access = await load_workspace_access(await session.connection(), tenant, workspace_id)
        if access is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        if permission not in access.permissions:
            raise HTTPException(status_code=403, detail=FORBIDDEN)
        return access

    return _declare(check, permission.value)


def requires_org(permission: Permission) -> Callable[..., Awaitable[OrgAccess]]:
    """Dependency of an Organization route; returns the caller's ``OrgAccess``."""
    _scope_check(permission, "org")

    async def check(
        tenant: Annotated[TenantContext, Depends(require_tenant)], session: TenantSession
    ) -> OrgAccess:
        access = await load_org_access(await session.connection(), tenant)
        if permission not in access.permissions:
            raise HTTPException(status_code=403, detail=FORBIDDEN)
        return access

    return _declare(check, permission.value)


def signed_in() -> Callable[..., Awaitable[TenantContext]]:
    """Dependency of a route that needs a verified session and nothing more."""

    async def check(tenant: Annotated[TenantContext, Depends(require_tenant)]) -> TenantContext:
        return tenant

    return _declare(check, SIGNED_IN)


def public(reason: str) -> Callable[..., Awaitable[None]]:
    """Dependency of a route that takes no identity; ``reason`` says why that is safe."""
    if not reason.strip():
        raise ValueError("a public route needs a reason")

    async def check() -> None:
        return None

    return _declare(check, PUBLIC)


async def _forbidden(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": FORBIDDEN})


def install_permission_handler(app: FastAPI) -> None:
    """``PermissionDenied`` from the service layer becomes 403 ``{"detail": "forbidden"}``."""
    app.add_exception_handler(PermissionDenied, _forbidden)
