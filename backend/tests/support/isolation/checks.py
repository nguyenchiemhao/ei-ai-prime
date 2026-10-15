"""The cross-tenant assertions of the isolation suite (AC1).

Every check calls a route as ``me`` (a user of one Organization) with the ids of ``other`` (the
second Organization) and proves that nothing of ``other`` comes back or changes. Each failure
message starts with ``<METHOD> <path> (<me>-><other>):`` and names the step that failed. Messages
never contain fixture values: CI logs are shared (D52).
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.tenancy.context import ORG_HEADERS, ORG_QUERY_PARAMS
from support.tenants import OrgRows, TwoOrgs

from .cases import OwnTenantRoute, PublicRoute, ResourceRoute
from .client import TOKENS
from .markers import (
    CapturedLogs,
    assert_no_markers,
    assert_nothing_copied,
    capture_logs,
    count_markers,
)
from .snapshot import Snapshot, snapshot_org
from .valkey import KeyState, assert_org_keys_unchanged, open_valkey, snapshot_org_keys

REFUSED = (403, 404)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _where(case: ResourceRoute | OwnTenantRoute | PublicRoute, me: OrgRows, other: OrgRows) -> str:
    return f"{case.method} {case.path} ({me.label}->{other.label})"


def _headers_text(response: httpx.Response) -> str:
    return "\n".join(f"{name}: {value}" for name, value in response.headers.items())


def _resources(case: ResourceRoute | OwnTenantRoute | PublicRoute) -> Mapping[str, str]:
    return case.query_resources if isinstance(case, OwnTenantRoute) else case.resources


async def _call(
    client: httpx.AsyncClient,
    case: ResourceRoute | OwnTenantRoute | PublicRoute,
    *,
    resource_rows: OrgRows,
    body_rows: OrgRows,
    token: str | None,
    forged: OrgRows | None = None,
) -> httpx.Response:
    """One request. Path parameters and id query parameters take ``resource_rows`` ids; the body
    is built from ``body_rows``; ``forged`` adds that Organization's id to every Organization
    header and query parameter the tenant context knows (D32: all of them must be ignored)."""
    ids = {name: str(resource_rows.row_id(table)) for name, table in _resources(case).items()}
    path_names = set(_PLACEHOLDER.findall(case.path))
    url = _PLACEHOLDER.sub(lambda match: ids[match.group(1)], case.path)
    params = [(name, value) for name, value in ids.items() if name not in path_names]
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if forged is not None:
        headers.update({name: str(forged.org_id) for name in ORG_HEADERS})
        params += [(name, str(forged.org_id)) for name in ORG_QUERY_PARAMS]
    build_body = None if isinstance(case, PublicRoute) else case.body
    body = build_body(body_rows) if build_body is not None else None
    return await client.request(
        case.method, url, headers=headers, params=urlencode(params), json=body
    )


def _assert_clean(
    response: httpx.Response, logs: CapturedLogs, other: OrgRows, where: str, step: str
) -> None:
    assert_no_markers(response.text, other, f"{where}: {step}: response body")
    assert_no_markers(_headers_text(response), other, f"{where}: {step}: response headers")
    assert_no_markers(logs.text, other, f"{where}: {step}: logs")


@dataclass
class _OtherState:
    """Everything of the other Organization that a call as someone else must leave alone."""

    rows: Snapshot
    keys: KeyState


async def _capture(engine: AsyncEngine, other: OrgRows) -> _OtherState:
    async with open_valkey() as valkey:
        return _OtherState(
            await snapshot_org(engine, other), await snapshot_org_keys(valkey, other)
        )


async def _assert_unchanged(
    engine: AsyncEngine, other: OrgRows, before: _OtherState, where: str
) -> None:
    assert await snapshot_org(engine, other) == before.rows, (
        f"{where}: data of Organization {other.label} changed"
    )
    async with open_valkey() as valkey:
        await assert_org_keys_unchanged(valkey, other, before.keys, where)


def _unknown_ids(other: OrgRows) -> OrgRows:
    """Rows with the shape of ``other`` and ids that exist nowhere."""
    return replace(
        other,
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        workspace_membership_id=uuid.uuid4(),
    )


async def _warm_up(
    client: httpx.AsyncClient, case: ResourceRoute | OwnTenantRoute, other: OrgRows
) -> None:
    """The other Organization uses the route first, with its own ids and token, so state that a
    route keeps between requests (a cache, a store) is filled before the cross call. A leak that
    needs the owner to have read the resource first is invisible to a cold route."""
    await _call(client, case, resource_rows=other, body_rows=other, token=TOKENS[other.label])


async def _assert_resource_route_isolated(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    case: ResourceRoute,
    me: OrgRows,
    other: OrgRows,
    token: str,
    where: str,
) -> None:
    await _warm_up(client, case, other)
    before = await _capture(engine, other)

    with capture_logs() as logs:
        cross = await _call(
            client, case, resource_rows=other, body_rows=other, token=token, forged=other
        )
    assert cross.status_code in REFUSED, (
        f"{where}: cross-Organization call answered {cross.status_code}, expected 403 or 404"
    )
    _assert_clean(cross, logs, other, where, "cross-Organization call")

    unknown_rows = _unknown_ids(other)
    unknown = await _call(
        client, case, resource_rows=unknown_rows, body_rows=unknown_rows, token=token, forged=other
    )
    assert (unknown.status_code, unknown.content) == (cross.status_code, cross.content), (
        f"{where}: an id of the other Organization and an unknown id answer differently"
        f" ({cross.status_code} vs {unknown.status_code} or different bodies): existence oracle"
    )

    await _assert_unchanged(engine, other, before, where)
    await assert_nothing_copied(engine, me, other, where)

    positive = await _call(client, case, resource_rows=me, body_rows=me, token=token)
    assert positive.status_code == case.ok_status, (
        f"{where}: positive control (own ids) answered {positive.status_code},"
        f" expected {case.ok_status}"
    )

    await _assert_anonymous_refused(client, case, me, where)


async def _assert_own_tenant_route_isolated(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    case: OwnTenantRoute,
    me: OrgRows,
    other: OrgRows,
    token: str,
    where: str,
) -> None:
    await _warm_up(client, case, other)
    before = await _capture(engine, other)
    expects_data = case.method.upper() == "GET" and case.ok_status == 200

    with capture_logs() as logs:
        cross = await _call(
            client, case, resource_rows=other, body_rows=me, token=token, forged=other
        )
    if case.query_resources:
        assert cross.status_code in REFUSED, (
            f"{where}: cross-Organization call answered {cross.status_code}, expected 403 or 404"
        )
    else:
        assert cross.status_code == case.ok_status, (
            f"{where}: call with forged Organization fields answered {cross.status_code},"
            f" expected {case.ok_status}"
        )
    _assert_clean(cross, logs, other, where, "cross-Organization call")
    if expects_data and not case.query_resources:
        assert count_markers(cross.text, me) > 0, (
            f"{where}: call with forged Organization fields returned none of"
            f" Organization {me.label}'s data"
        )

    await _assert_unchanged(engine, other, before, where)
    await assert_nothing_copied(engine, me, other, where)

    positive = await _call(client, case, resource_rows=me, body_rows=me, token=token)
    assert positive.status_code == case.ok_status, (
        f"{where}: positive control (own ids) answered {positive.status_code},"
        f" expected {case.ok_status}"
    )
    if expects_data:
        assert count_markers(positive.text, me) > 0, (
            f"{where}: positive control returned none of Organization {me.label}'s data"
        )

    await _assert_anonymous_refused(client, case, me, where)


async def _assert_anonymous_refused(
    client: httpx.AsyncClient,
    case: ResourceRoute | OwnTenantRoute,
    me: OrgRows,
    where: str,
) -> None:
    anonymous = await _call(client, case, resource_rows=me, body_rows=me, token=None)
    assert anonymous.status_code == 401, (
        f"{where}: call without credentials answered {anonymous.status_code}, expected 401"
    )


async def assert_route_isolated(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    case: ResourceRoute | OwnTenantRoute,
    me: OrgRows,
    other: OrgRows,
    token: str,
) -> None:
    """Call the route as a user of ``me`` with the ids of ``other``; see the module docstring."""
    where = _where(case, me, other)
    if isinstance(case, ResourceRoute):
        await _assert_resource_route_isolated(client, engine, case, me, other, token, where)
    else:
        await _assert_own_tenant_route_isolated(client, engine, case, me, other, token, where)


async def assert_public_route_clean(
    client: httpx.AsyncClient, case: PublicRoute, orgs: TwoOrgs
) -> None:
    """Anonymous calls, claiming to be each Organization in turn (its id in every Organization
    header and query parameter, its fixture ids in the path), return nothing of either
    Organization, in body, headers or logs."""
    where = f"{case.method} {case.path} (public)"
    responses = []
    with capture_logs() as logs:
        for claimed in (orgs.a, orgs.b):
            responses.append(
                await _call(
                    client,
                    case,
                    resource_rows=claimed,
                    body_rows=claimed,
                    token=None,
                    forged=claimed,
                )
            )
    for response in responses:
        for rows in (orgs.a, orgs.b):
            _assert_clean(response, logs, rows, where, "anonymous call")
