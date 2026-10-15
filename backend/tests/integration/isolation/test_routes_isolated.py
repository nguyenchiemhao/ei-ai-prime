"""AC1: every authenticated route, called as a user of one Organization with the ids of the other,
never returns or changes the other Organization's data (both directions).

The parameters are generated from the routes of the production app, so a new route is red here
until it has a declaration in ``cases.py``.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.main import create_app
from support.isolation.cases import OwnTenantRoute, PublicRoute, ResourceRoute, key
from support.isolation.checks import assert_public_route_clean, assert_route_isolated
from support.isolation.client import TOKENS, isolation_client
from support.isolation.routes import DiscoveredRoute, discover_routes
from support.tenants import TwoOrgs

from .cases import ROUTE_CASES

_DECLARED = {key(case): case for case in ROUTE_CASES}
_ROUTES = discover_routes(create_app())
_AUTHENTICATED = [route for route in _ROUTES if route.authenticated]
_PUBLIC = [route for route in _ROUTES if not route.authenticated]
_DIRECTIONS = [("A", "B"), ("B", "A")]


@pytest.mark.parametrize(
    ("route", "me", "other"),
    [
        pytest.param(route, me, other, id=f"{route.label} {me}->{other}")
        for route in _AUTHENTICATED
        for me, other in _DIRECTIONS
    ],
)
async def test_route_is_isolated(
    route: DiscoveredRoute, me: str, other: str, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = _DECLARED.get((route.method, route.path))
    if not isinstance(case, ResourceRoute | OwnTenantRoute):
        pytest.fail(f"route has no isolation test declared: {route.label}")
    rows = {"A": two_orgs.a, "B": two_orgs.b}

    async with isolation_client(app_engine, two_orgs) as client:
        await assert_route_isolated(client, app_engine, case, rows[me], rows[other], TOKENS[me])


@pytest.mark.parametrize("route", _PUBLIC, ids=lambda route: route.label)
async def test_public_route_returns_no_tenant_data(
    route: DiscoveredRoute, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = _DECLARED.get((route.method, route.path))
    if not isinstance(case, PublicRoute):
        pytest.fail(f"route has no isolation test declared: {route.label}")

    async with isolation_client(app_engine, two_orgs) as client:
        await assert_public_route_clean(client, case, two_orgs)
