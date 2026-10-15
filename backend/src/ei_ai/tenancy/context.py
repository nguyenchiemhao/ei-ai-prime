"""The tenant context of a request (D32, D46).

The only allowed source of ``org_id`` is the verified Principal. Anything the client sends that
looks like an Organization id is ignored, and a differing value is logged as a warning.
Request models must never declare ``org_id`` either (coding-rules, Backend).
"""

import logging
import re
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from ei_ai.auth.dependencies import current_principal
from ei_ai.auth.principal import Principal

logger = logging.getLogger("ei_ai.tenancy")

ORG_HEADERS = ("x-org-id", "x-organization-id", "x-tenant-id")
ORG_QUERY_PARAMS = ("org_id", "orgId", "organization_id", "tenant_id")


def _normalised(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


_ORG_FIELDS = frozenset(_normalised(name) for name in (*ORG_HEADERS, *ORG_QUERY_PARAMS, "org_id"))


def is_org_field(name: str) -> bool:
    """True when a request field name (header, query, cookie, path or body property) spells an
    Organization id in any case or separator style: ``org_id``, ``orgId``, ``X-Tenant-Id``.

    The tenant isolation suite fails when a route declares such a field (D32), and a background
    job payload may not carry one. Built from the lists above so they cannot drift.
    """
    return _normalised(name) in _ORG_FIELDS


@dataclass(frozen=True)
class TenantContext:
    org_id: UUID
    user_id: UUID


def _differs(supplied: str, org_id: UUID) -> bool:
    try:
        return UUID(supplied) != org_id
    except ValueError:
        return True  # malformed counts as different


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", "unknown"))  # the template, never the raw URL


def _supplied_fields(request: Request) -> list[tuple[str, str, str]]:
    """(source, configured field name, value) for every Organization-like field in the request."""
    found = [
        ("header", name, value) for name in ORG_HEADERS for value in request.headers.getlist(name)
    ]
    wanted = {name.lower(): name for name in ORG_QUERY_PARAMS}
    found += [
        ("query", wanted[key.lower()], value)
        for key, value in request.query_params.multi_items()
        if key.lower() in wanted
    ]
    return found


def require_tenant(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> TenantContext:
    """The tenant of this request: always the Principal's Organization.

    A header or query parameter naming a different Organization is ignored and logged once as
    ``tenant_override_ignored`` (source, configured field name, route template and the Principal's
    Organization; never the supplied value).
    """
    for source, field, value in _supplied_fields(request):
        if _differs(value, principal.org_id):
            logger.warning(
                "tenant_override_ignored source=%s field=%s path=%s org_id=%s",
                source,
                field,
                _route_path(request),
                principal.org_id,
            )
    return TenantContext(org_id=principal.org_id, user_id=principal.user_id)
