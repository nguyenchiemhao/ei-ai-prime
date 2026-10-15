"""AC2: a new route is covered automatically, or CI fails with "route has no isolation test
declared". No database needed; the check runs against the production ``create_app()``."""

from ei_ai.main import create_app
from support.isolation.fields import forbidden_request_fields
from support.isolation.routes import coverage_problems, discover_routes, openapi_operations

from .cases import ROUTE_CASES


def test_every_route_has_an_isolation_case() -> None:
    problems = coverage_problems(discover_routes(create_app()), ROUTE_CASES)

    assert not problems, "\n".join(problems)


def test_no_stale_isolation_cases() -> None:
    problems = [
        problem
        for problem in coverage_problems(discover_routes(create_app()), ROUTE_CASES)
        if problem.startswith("isolation case for a route that does not exist")
    ]

    assert not problems, "\n".join(problems)


def test_openapi_and_router_list_the_same_operations() -> None:
    app = create_app()
    routes = discover_routes(app)

    in_openapi = openapi_operations(app)
    in_router = {(route.method, route.path) for route in routes}
    in_router_and_schema = {(route.method, route.path) for route in routes if route.in_schema}

    assert in_openapi <= in_router, (
        f"in OpenAPI but not discovered: {sorted(in_openapi - in_router)}"
    )
    assert in_router_and_schema <= in_openapi, (
        f"discovered but missing from OpenAPI: {sorted(in_router_and_schema - in_openapi)}"
    )


def test_discovery_finds_the_authenticated_routes() -> None:
    routes = discover_routes(create_app())
    authenticated = {(route.method, route.path) for route in routes if route.authenticated}

    assert ("GET", "/organization") in authenticated
    assert all(route.tenant_scoped for route in routes if route.authenticated)
    assert {("GET", "/healthz"), ("GET", "/readyz")} <= {
        (route.method, route.path) for route in routes if not route.authenticated
    }


def _request_field_problems() -> list[str]:
    app = create_app()
    hidden = [route for route in discover_routes(app) if not route.in_schema]
    return forbidden_request_fields(app.openapi(), hidden)


def test_no_request_declares_an_org_field() -> None:
    problems = [p for p in _request_field_problems() if "Organization" in p]

    assert not problems, "\n".join(problems)


def test_no_request_body_declares_an_id() -> None:
    problems = [p for p in _request_field_problems() if "declares id" in p]

    assert not problems, "\n".join(problems)
