"""Deliberately leaky routes and jobs, to prove the isolation suite catches each kind of leak.

Test-only: never imported by ``src`` and mounted only on the instance the self-tests build
(``support.isolation.client.build_app``), never in ``create_app``. Each probe is a small, honest
copy of a classic mistake.
"""

import logging
import os
import uuid
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.dependencies import current_principal
from ei_ai.auth.principal import Principal
from ei_ai.cache.tenant_cache import TenantCache
from ei_ai.db.tenant import tenant_session
from ei_ai.jobs.envelope import JobContext
from ei_ai.jobs.registry import JobRegistry
from ei_ai.tenancy.context import TenantContext, require_tenant
from support.tenants import TwoOrgs

Tenant = Annotated[TenantContext, Depends(require_tenant)]


def _workspace_names(orgs: TwoOrgs) -> dict[uuid.UUID, str]:
    """Both Organizations' workspaces in one dict: a store without a tenant filter."""
    return {
        orgs.a.workspace_id: orgs.a.names.workspace,
        orgs.b.workspace_id: orgs.b.names.workspace,
    }


def undeclared_router() -> APIRouter:
    """A tenant route that nobody declared in ``cases.py``."""
    router = APIRouter()

    @router.get("/probe/undeclared")
    def undeclared(tenant: Tenant) -> dict[str, str]:
        return {}

    return router


def principal_only_router() -> APIRouter:
    """Authenticated, but it never goes through ``require_tenant``."""
    router = APIRouter()

    @router.get("/probe/principal-only")
    def principal_only(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, str]:
        return {}

    return router


def filter_router() -> APIRouter:
    """A tenant route with a uuid-typed id filter."""
    router = APIRouter()

    @router.get("/probe/filter")
    def filtered(tenant: Tenant, workspace_id: uuid.UUID | None = None) -> dict[str, str]:
        return {}

    return router


def str_filter_router() -> APIRouter:
    """A tenant route whose id filter is typed ``str``, so the type does not reveal it is an id."""
    router = APIRouter()

    @router.get("/probe/str-filter")
    def str_filtered(
        tenant: Tenant, workspace_id: str | None = None, id: str | None = None
    ) -> dict[str, str]:
        return {}

    return router


def org_from_header_router() -> APIRouter:
    """D32 violation: the Organization is taken from a header, not from the token."""
    router = APIRouter()

    @router.get("/probe/org-from-header")
    async def org_from_header(request: Request, tenant: Tenant) -> dict[str, str]:
        org_id = uuid.UUID(request.headers.get("x-org-id", str(tenant.org_id)))
        async with tenant_session(request.app.state.engine, org_id) as session:
            name = (
                await session.execute(
                    text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id}
                )
            ).scalar_one()
        return {"name": str(name)}

    return router


def unscoped_lookup_router(orgs: TwoOrgs) -> APIRouter:
    """A lookup in a store without a tenant filter (both Organizations' workspaces in one dict)."""
    router = APIRouter()
    store = {
        orgs.a.workspace_id: orgs.a.names.workspace,
        orgs.b.workspace_id: orgs.b.names.workspace,
    }

    @router.get("/probe/workspaces/{workspace_id}")
    def workspace(workspace_id: uuid.UUID, tenant: Tenant) -> dict[str, str]:
        if workspace_id not in store:
            raise HTTPException(status_code=404, detail="not_found")
        return {"name": store[workspace_id]}

    return router


def cached_lookup_router() -> APIRouter:
    """Correct database lookup behind an in-process cache keyed by id only (no Organization):
    the leak appears only after the owning Organization has read the resource once."""
    router = APIRouter()
    cache: dict[uuid.UUID, str] = {}

    @router.get("/probe/cached/{workspace_id}")
    async def cached(workspace_id: uuid.UUID, request: Request, tenant: Tenant) -> dict[str, str]:
        if workspace_id not in cache:
            async with tenant_session(request.app.state.engine, tenant.org_id) as session:
                name = (
                    await session.execute(
                        text("SELECT name FROM workspaces WHERE id = :id"), {"id": workspace_id}
                    )
                ).scalar_one_or_none()
            if name is None:
                raise HTTPException(status_code=404, detail="not_found")
            cache[workspace_id] = str(name)
        return {"name": cache[workspace_id]}

    return router


def oracle_router(orgs: TwoOrgs) -> APIRouter:
    """Existence oracle: 403 for an id of another Organization, 404 for an unknown id."""
    router = APIRouter()
    owners = {orgs.a.workspace_id: orgs.a.org_id, orgs.b.workspace_id: orgs.b.org_id}

    @router.get("/probe/oracle/{workspace_id}")
    def oracle(workspace_id: uuid.UUID, tenant: Tenant) -> dict[str, bool]:
        owner = owners.get(workspace_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="not_found")
        if owner != tenant.org_id:
            raise HTTPException(status_code=403, detail="forbidden")
        return {"ok": True}

    return router


def rename_from_header_router() -> APIRouter:
    """Writes into the Organization named by a header, whatever the token says."""
    router = APIRouter()

    @router.post("/probe/rename-from-header")
    async def rename(request: Request, tenant: Tenant) -> dict[str, bool]:
        org_id = uuid.UUID(request.headers.get("x-org-id", str(tenant.org_id)))
        async with tenant_session(request.app.state.engine, org_id) as session:
            await session.execute(
                text("UPDATE organizations SET name = :name WHERE id = :id"),
                {"id": org_id, "name": f"renamed-by-probe-{uuid.uuid4()}"},
            )
        return {"ok": True}

    return router


_ORIGINAL_WORKSPACE = "SELECT name FROM workspaces WHERE name NOT LIKE 'copy of %'"


async def _workspace_name(engine: AsyncEngine, org_id: uuid.UUID) -> str:
    async with tenant_session(engine, org_id) as session:
        return str((await session.execute(text(_ORIGINAL_WORKSPACE))).scalar_one())


def copy_from_header_router() -> APIRouter:
    """Reads the workspace of the Organization named by a header and stores a copy in the caller's
    own Organization: nothing of the other Organization changes, but its data lands in ours."""
    router = APIRouter()

    @router.post("/probe/copy-from-header")
    async def copy(request: Request, tenant: Tenant) -> dict[str, bool]:
        engine = request.app.state.engine
        source = uuid.UUID(request.headers.get("x-org-id", str(tenant.org_id)))
        name = await _workspace_name(engine, source)
        async with tenant_session(engine, tenant.org_id) as session:
            await session.execute(
                text("INSERT INTO workspaces (org_id, name) VALUES (:org, :name)"),
                {"org": tenant.org_id, "name": f"copy of {name}"},
            )
        return {"ok": True}

    return router


async def _count_visit(org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Increment the visit counter of an Organization through the wrapper. Building the context by
    hand from a header is exactly the D32 violation the cross-tenant check must catch."""
    client = aioredis.from_url(os.environ["VALKEY_URL"])
    try:
        cache = TenantCache(client, TenantContext(org_id=org_id, user_id=user_id))
        await cache.incr("visits", "total", ttl_seconds=600)
    finally:
        await client.aclose()


def visits_from_header_router() -> APIRouter:
    """Counts the visit for the Organization named by a header, whatever the token says."""
    router = APIRouter()

    @router.post("/probe/visits")
    async def visits(request: Request, tenant: Tenant) -> dict[str, bool]:
        org_id = uuid.UUID(request.headers.get("x-org-id", str(tenant.org_id)))
        await _count_visit(org_id, tenant.user_id)
        return {"ok": True}

    return router


RAW_VALKEY_KEY = "probe:route-raw"


def raw_valkey_key_router() -> APIRouter:
    """A tenant route that counts calls under a Valkey key without the Organization prefix,
    writing around ``TenantCache`` (what the static import guard exists to prevent)."""
    router = APIRouter()

    @router.post("/probe/raw-counter")
    async def raw_counter(tenant: Tenant) -> dict[str, bool]:
        client = aioredis.from_url(os.environ["VALKEY_URL"])
        try:
            await client.incr(RAW_VALKEY_KEY)
            await client.expire(RAW_VALKEY_KEY, 30)
        finally:
            await client.aclose()
        return {"ok": True}

    return router


def public_names_router(orgs: TwoOrgs) -> APIRouter:
    """A route without identity that returns tenant data."""
    router = APIRouter()
    names = [orgs.a.names.organization, orgs.b.names.organization, f"{orgs.a.org_id}"]

    @router.get("/probe/public-names")
    def public_names() -> dict[str, list[str]]:
        return {"names": names}

    return router


def public_branding_router(orgs: TwoOrgs) -> APIRouter:
    """Public routes (no identity) that trust client input: a header names the Organization, and
    a path parameter picks a workspace out of a store without a tenant filter."""
    router = APIRouter()
    store = {
        orgs.a.workspace_id: orgs.a.names.workspace,
        orgs.b.workspace_id: orgs.b.names.workspace,
    }

    @router.get("/probe/branding")
    async def branding(request: Request) -> dict[str, str]:
        org_id = uuid.UUID(request.headers.get("x-org-id", str(uuid.uuid4())))
        async with tenant_session(request.app.state.engine, org_id) as session:
            name = (
                await session.execute(
                    text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id}
                )
            ).scalar_one_or_none()
        return {"name": str(name)}

    @router.get("/probe/branding/{workspace_id}")
    def branding_workspace(workspace_id: uuid.UUID) -> dict[str, str]:
        return {"name": store.get(workspace_id, "")}

    return router


def always_not_found_router() -> APIRouter:
    """A resource route that refuses everything, so a case can never pass vacuously."""
    router = APIRouter()

    @router.get("/probe/always-not-found/{workspace_id}")
    def always_not_found(workspace_id: uuid.UUID, tenant: Tenant) -> dict[str, str]:
        raise HTTPException(status_code=404, detail="not_found")

    return router


class _WithOrg(BaseModel):
    name: str
    org_id: uuid.UUID


class _Nested(BaseModel):
    name: str
    owner: _WithOrg


class _WithId(BaseModel):
    id: uuid.UUID
    name: str


def request_fields_router() -> APIRouter:
    """Request models and parameters that name an Organization or choose a primary key."""
    router = APIRouter()

    @router.post("/probe/with-org")
    def with_org(body: _WithOrg, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/nested-org")
    def nested_org(body: _Nested, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.get("/probe/query-tenant")
    def query_tenant(tenant_id: str, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/with-id")
    def with_id(body: _WithId, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/bulk")
    def bulk(body: list[_WithId], tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/org-map")
    def org_map(body: dict[str, _WithOrg], tenant: Tenant) -> dict[str, str]:
        return {}

    return router


def hidden_fields_router() -> APIRouter:
    """Routes left out of the OpenAPI schema that still break the request-field rules."""
    router = APIRouter()

    @router.get("/probe/hidden-query", include_in_schema=False)
    def hidden_query(org_id: str, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/hidden-body", include_in_schema=False)
    def hidden_body(body: _WithId, tenant: Tenant) -> dict[str, str]:
        return {}

    @router.post("/probe/hidden-nested", include_in_schema=False)
    def hidden_nested(body: _Nested, tenant: Tenant) -> dict[str, str]:
        return {}

    return router


async def _own_organization_name(request: Request, tenant: TenantContext) -> dict[str, str]:
    async with tenant_session(request.app.state.engine, tenant.org_id) as session:
        name = (
            await session.execute(
                text("SELECT name FROM organizations WHERE id = :id"), {"id": tenant.org_id}
            )
        ).scalar_one()
    return {"name": str(name)}


def logging_router(logger_name: str) -> APIRouter:
    """Correct data, but it logs the Organization header it was sent (D52 violation)."""
    router = APIRouter()

    @router.get("/probe/logs-forged")
    async def logs_forged(request: Request, tenant: Tenant) -> dict[str, str]:
        logging.getLogger(logger_name).warning("x-org-id=%s", request.headers.get("x-org-id"))
        return await _own_organization_name(request, tenant)

    return router


def header_echo_router() -> APIRouter:
    """Correct data, but it echoes the Organization header in a response header."""
    router = APIRouter()

    @router.get("/probe/header-echo")
    async def header_echo(request: Request, response: Response, tenant: Tenant) -> dict[str, str]:
        response.headers["x-echo"] = request.headers.get("x-org-id", "none")
        return await _own_organization_name(request, tenant)

    return router


def open_post_router() -> APIRouter:
    """A write route that forgot authentication altogether."""
    router = APIRouter()

    @router.post("/probe/open")
    def open_post() -> dict[str, bool]:
        return {"ok": True}

    return router


def empty_answer_router() -> APIRouter:
    """An authenticated GET that returns no data of the caller (a vacuous case)."""
    router = APIRouter()

    @router.get("/probe/empty")
    def empty(tenant: Tenant) -> dict[str, str]:
        return {}

    return router


def switching_job_registry() -> JobRegistry:
    """A handler that switches the tenant of its own transaction to the one in its payload."""
    registry = JobRegistry()

    @registry.register("probe.switch-tenant")
    async def switch(context: JobContext, payload: Mapping[str, object]) -> None:
        await context.session.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": payload["target"]}
        )
        await context.session.execute(
            text("UPDATE organizations SET name = 'renamed-by-job' WHERE id = :org"),
            {"org": payload["target"]},
        )

    return registry


def copying_job_registry() -> JobRegistry:
    """A handler that reads the Organization in its payload (switching the tenant of its own
    transaction) and writes a copy into its own Organization."""
    registry = JobRegistry()

    @registry.register("probe.copy-other")
    async def copy(context: JobContext, payload: Mapping[str, object]) -> None:
        await context.session.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": payload["target"]}
        )
        name = (await context.session.execute(text(_ORIGINAL_WORKSPACE))).scalar_one()
        await context.session.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": str(context.org_id)}
        )
        await context.session.execute(
            text("INSERT INTO workspaces (org_id, name) VALUES (:org, :name)"),
            {"org": context.org_id, "name": f"copy of {name}"},
        )

    return registry


def counting_job_registry() -> JobRegistry:
    """A handler that bumps the counter of the Organization named in its payload."""
    registry = JobRegistry()

    @registry.register("probe.count-for")
    async def count_for(context: JobContext, payload: Mapping[str, object]) -> None:
        await _count_visit(uuid.UUID(str(payload["target"])), uuid.uuid4())

    return registry


def undeclared_job_registry() -> JobRegistry:
    """A registered job that nobody declared in ``cases.py``."""
    registry = JobRegistry()

    @registry.register("probe.undeclared")
    async def undeclared(context: JobContext, payload: Mapping[str, object]) -> None:
        return None

    return registry
