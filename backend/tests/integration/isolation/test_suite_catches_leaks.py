"""The suite proves it bites: every kind of leak, built as a probe, makes a check fail.

A green isolation suite means little unless a route that skips the tenant filter turns it red.
Each test mounts one leaky probe (``probes.py``, test-only) on a copy of the app and runs the real
check helper against it.
"""

import pytest
from fastapi import APIRouter
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.registry import JobRegistry
from ei_ai.main import create_app
from support.isolation.cases import (
    JobCase,
    OwnTenantRoute,
    PublicRoute,
    ResourceRoute,
    RouteCase,
    key,
)
from support.isolation.checks import assert_public_route_clean, assert_route_isolated
from support.isolation.client import TOKENS, isolation_client
from support.isolation.fields import forbidden_request_fields
from support.isolation.jobs import assert_job_isolated, job_coverage_problems
from support.isolation.routes import UnsupportedRoute, coverage_problems, discover_routes
from support.isolation.valkey import assert_only_tenant_keys
from support.tenants import OrgRows, TwoOrgs

from . import probes
from .cases import ROUTE_CASES
from .sample_jobs import Recorder, sample_registry


def _problems(*routers: APIRouter, cases: tuple[RouteCase, ...] = ROUTE_CASES) -> list[str]:
    app = create_app()
    for router in routers:
        app.include_router(router)
    return coverage_problems(discover_routes(app), cases)


# --- declarations (AC2) ---------------------------------------------------------------------------


def test_undeclared_route_is_reported_with_the_required_message() -> None:
    assert _problems(probes.undeclared_router()) == [
        "route has no isolation test declared: GET /probe/undeclared"
    ]


def test_public_declaration_of_an_authenticated_route_is_reported() -> None:
    cases = (*ROUTE_CASES, PublicRoute("GET", "/probe/undeclared", "wrongly public"))

    assert _problems(probes.undeclared_router(), cases=cases) == [
        "route declared public but requires an identity: GET /probe/undeclared"
    ]


def test_tenant_case_kind_for_a_public_route_is_reported() -> None:
    others = tuple(case for case in ROUTE_CASES if key(case) != ("GET", "/readyz"))
    cases = (*others, OwnTenantRoute("GET", "/readyz"))

    assert _problems(cases=cases) == [
        "public route declared with an isolation case kind for tenant routes: GET /readyz"
    ]


async def test_public_route_with_a_path_parameter_needs_a_fixture_resource(
    two_orgs: TwoOrgs,
) -> None:
    cases = (
        *ROUTE_CASES,
        PublicRoute("GET", "/probe/branding", "branding"),
        PublicRoute("GET", "/probe/branding/{workspace_id}", "branding"),
    )

    assert _problems(probes.public_branding_router(two_orgs), cases=cases) == [
        "path parameter {workspace_id} of GET /probe/branding/{workspace_id}"
        " has no fixture resource in its isolation case"
    ]


def test_a_public_route_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        PublicRoute("GET", "/healthz", "  ")


def test_case_for_a_route_that_does_not_exist_is_reported() -> None:
    cases = (*ROUTE_CASES, OwnTenantRoute("GET", "/gone"))

    assert _problems(cases=cases) == ["isolation case for a route that does not exist: GET /gone"]


def test_authenticated_route_without_require_tenant_is_reported() -> None:
    cases = (*ROUTE_CASES, OwnTenantRoute("GET", "/probe/principal-only"))

    assert _problems(probes.principal_only_router(), cases=cases) == [
        "authenticated route does not depend on require_tenant: GET /probe/principal-only"
    ]


def test_path_parameter_without_a_fixture_resource_is_reported() -> None:
    cases = (*ROUTE_CASES, ResourceRoute("GET", "/probe/always-not-found/{workspace_id}", {}))

    assert _problems(probes.always_not_found_router(), cases=cases) == [
        "path parameter {workspace_id} of GET /probe/always-not-found/{workspace_id}"
        " has no fixture resource in its isolation case"
    ]


def test_id_query_parameter_without_a_fixture_resource_is_reported() -> None:
    cases = (*ROUTE_CASES, OwnTenantRoute("GET", "/probe/filter"))

    assert _problems(probes.filter_router(), cases=cases) == [
        "id query parameter {workspace_id} of GET /probe/filter"
        " has no fixture resource in its isolation case"
    ]


def test_string_query_parameters_named_like_ids_need_a_fixture_resource() -> None:
    cases = (*ROUTE_CASES, OwnTenantRoute("GET", "/probe/str-filter"))

    assert _problems(probes.str_filter_router(), cases=cases) == [
        "id query parameter {workspace_id} of GET /probe/str-filter"
        " has no fixture resource in its isolation case",
        "id query parameter {id} of GET /probe/str-filter"
        " has no fixture resource in its isolation case",
    ]


async def test_public_route_resource_must_match_its_fixture_table(two_orgs: TwoOrgs) -> None:
    # A wrong mapping would make the public check call the route with ids it cannot resolve and
    # pass vacuously, so the parameter must name the table it maps to.
    cases = (
        *ROUTE_CASES,
        PublicRoute("GET", "/probe/branding", "branding"),
        PublicRoute(
            "GET",
            "/probe/branding/{workspace_id}",
            "branding",
            resources={"workspace_id": "memberships"},
        ),
    )

    assert _problems(probes.public_branding_router(two_orgs), cases=cases) == [
        "public route parameter {workspace_id} of GET /probe/branding/{workspace_id} maps to"
        " memberships; the parameter must be called membership_id"
    ]


def test_a_route_type_the_suite_cannot_test_is_reported() -> None:
    app = create_app()

    async def stream() -> None:  # pragma: no cover - never connected
        return None

    app.add_api_websocket_route("/probe/ws", stream)

    with pytest.raises(UnsupportedRoute, match="/probe/ws: route type APIWebSocketRoute is not"):
        discover_routes(app)


def test_a_duplicate_declaration_is_reported() -> None:
    cases = (*ROUTE_CASES, PublicRoute("GET", "/healthz", "a second, weaker declaration"))

    assert _problems(cases=cases) == ["duplicate isolation case: GET /healthz"]


def test_request_fields_of_routes_hidden_from_openapi_are_reported() -> None:
    app = create_app()
    app.include_router(probes.hidden_fields_router())
    hidden = [route for route in discover_routes(app) if not route.in_schema]

    assert forbidden_request_fields(app.openapi(), hidden) == [
        "GET /probe/hidden-query: request field org_id names an Organization (D32)",
        "POST /probe/hidden-body: request body declares id (the server generates ids)",
        "POST /probe/hidden-nested: request field org_id names an Organization (D32)",
    ]


def test_org_field_in_a_request_model_is_reported() -> None:
    app = create_app()
    app.include_router(probes.request_fields_router())

    assert forbidden_request_fields(app.openapi()) == [
        "GET /probe/query-tenant: request field tenant_id names an Organization (D32)",
        "POST /probe/bulk: request body declares id (the server generates ids)",
        "POST /probe/nested-org: request field org_id names an Organization (D32)",
        "POST /probe/org-map: request field org_id names an Organization (D32)",
        "POST /probe/with-id: request body declares id (the server generates ids)",
        "POST /probe/with-org: request field org_id names an Organization (D32)",
    ]


# --- cross-tenant calls (AC1) ---------------------------------------------------------------------


async def _run_route_check(
    engine: AsyncEngine,
    orgs: TwoOrgs,
    router: APIRouter,
    case: ResourceRoute | OwnTenantRoute,
) -> None:
    async with isolation_client(engine, orgs, [router]) as client:
        await assert_route_isolated(client, engine, case, orgs.a, orgs.b, TOKENS["A"])


async def test_check_fails_on_tenant_taken_from_header(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("GET", "/probe/org-from-header")

    with pytest.raises(AssertionError, match=r"cross-Organization call: response body: 1 marker"):
        await _run_route_check(app_engine, two_orgs, probes.org_from_header_router(), case)


async def test_check_fails_on_unscoped_resource_lookup(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = ResourceRoute("GET", "/probe/workspaces/{workspace_id}", {"workspace_id": "workspaces"})

    with pytest.raises(AssertionError, match=r"cross-Organization call answered 200, expected 403"):
        await _run_route_check(app_engine, two_orgs, probes.unscoped_lookup_router(two_orgs), case)


@pytest.mark.parametrize("logger_name", ["ei_ai.probe", "uvicorn.error"])
async def test_check_fails_on_a_route_that_logs_the_forged_value(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, logger_name: str
) -> None:
    case = OwnTenantRoute("GET", "/probe/logs-forged")

    with pytest.raises(AssertionError, match=r"cross-Organization call: logs: 1 marker"):
        await _run_route_check(app_engine, two_orgs, probes.logging_router(logger_name), case)


async def test_check_fails_on_a_route_that_echoes_the_forged_value_in_a_header(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("GET", "/probe/header-echo")

    with pytest.raises(AssertionError, match=r"call: response headers: 1 marker"):
        await _run_route_check(app_engine, two_orgs, probes.header_echo_router(), case)


async def test_check_fails_on_a_route_that_answers_without_credentials(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("POST", "/probe/open")

    with pytest.raises(AssertionError, match=r"without credentials answered 200, expected 401"):
        await _run_route_check(app_engine, two_orgs, probes.open_post_router(), case)


async def test_check_fails_on_an_own_tenant_route_that_returns_none_of_the_callers_data(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("GET", "/probe/empty")

    with pytest.raises(AssertionError, match=r"returned none of Organization A"):
        await _run_route_check(app_engine, two_orgs, probes.empty_answer_router(), case)


async def test_check_fails_on_a_cache_that_ignores_the_organization(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    # The leak needs the owner to read first: the check must warm the route up as the other side.
    case = ResourceRoute("GET", "/probe/cached/{workspace_id}", {"workspace_id": "workspaces"})

    with pytest.raises(AssertionError, match=r"cross-Organization call answered 200, expected 403"):
        await _run_route_check(app_engine, two_orgs, probes.cached_lookup_router(), case)


async def test_check_fails_on_existence_oracle(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    case = ResourceRoute("GET", "/probe/oracle/{workspace_id}", {"workspace_id": "workspaces"})

    with pytest.raises(AssertionError, match=r"answer differently .*existence oracle"):
        await _run_route_check(app_engine, two_orgs, probes.oracle_router(two_orgs), case)


async def test_check_fails_on_write_into_other_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("POST", "/probe/rename-from-header")

    with pytest.raises(AssertionError, match=r"data of Organization B changed"):
        await _run_route_check(app_engine, two_orgs, probes.rename_from_header_router(), case)


async def test_check_fails_on_a_route_that_copies_other_organization_data_into_its_own(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = OwnTenantRoute("POST", "/probe/copy-from-header")

    with pytest.raises(AssertionError, match=r"rows of Organization A: 1 marker"):
        await _run_route_check(app_engine, two_orgs, probes.copy_from_header_router(), case)


async def _drop_org_keys(valkey: aioredis.Redis, *orgs: OrgRows) -> None:
    for org in orgs:
        async for stale in valkey.scan_iter(match=f"org:{org.org_id}:*"):
            await valkey.delete(stale)


async def test_check_fails_on_a_route_that_changes_the_other_organizations_cache(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, valkey: aioredis.Redis
) -> None:
    # Every key carries a valid prefix, so the key-family scan is satisfied; only the comparison
    # of the other Organization's Valkey state before and after the cross call sees the write.
    case = OwnTenantRoute("POST", "/probe/visits")
    try:
        with pytest.raises(AssertionError, match=r"Valkey keys of Organization B changed"):
            await _run_route_check(app_engine, two_orgs, probes.visits_from_header_router(), case)
    finally:
        await _drop_org_keys(valkey, two_orgs.a, two_orgs.b)


async def test_job_check_fails_on_a_handler_that_changes_the_other_organizations_cache(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, valkey: aioredis.Redis
) -> None:
    case = JobCase("probe.count-for", _target)
    try:
        with pytest.raises(AssertionError, match=r"Valkey keys of Organization B changed"):
            await assert_job_isolated(
                app_engine, probes.counting_job_registry(), case, two_orgs.a, two_orgs.b
            )
    finally:
        await _drop_org_keys(valkey, two_orgs.a, two_orgs.b)


async def test_valkey_scan_catches_a_route_that_writes_a_raw_key(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, valkey: aioredis.Redis
) -> None:
    # The route passes every cross-tenant check; only the scan of Valkey sees the raw key.
    case = OwnTenantRoute("POST", "/probe/raw-counter")
    try:
        await _run_route_check(app_engine, two_orgs, probes.raw_valkey_key_router(), case)

        with pytest.raises(AssertionError, match=r"outside the org:<uuid>: prefix .*'probe'"):
            await assert_only_tenant_keys(valkey, "after the route check")
    finally:
        await valkey.delete(probes.RAW_VALKEY_KEY)


async def test_check_fails_on_public_route_with_tenant_data(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = PublicRoute("GET", "/probe/public-names", "leaky")

    async with isolation_client(
        app_engine, two_orgs, [probes.public_names_router(two_orgs)]
    ) as client:
        with pytest.raises(AssertionError, match=r"anonymous call: response body: 2 marker"):
            await assert_public_route_clean(client, case, two_orgs)


async def test_check_fails_on_public_route_that_trusts_an_organization_header(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = PublicRoute("GET", "/probe/branding", "branding by header")

    async with isolation_client(
        app_engine, two_orgs, [probes.public_branding_router(two_orgs)]
    ) as client:
        with pytest.raises(AssertionError, match=r"anonymous call: response body: 1 marker"):
            await assert_public_route_clean(client, case, two_orgs)


async def test_check_fails_on_public_route_that_returns_any_workspace_by_id(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = PublicRoute(
        "GET",
        "/probe/branding/{workspace_id}",
        "branding by workspace",
        resources={"workspace_id": "workspaces"},
    )

    async with isolation_client(
        app_engine, two_orgs, [probes.public_branding_router(two_orgs)]
    ) as client:
        with pytest.raises(AssertionError, match=r"anonymous call: response body: 1 marker"):
            await assert_public_route_clean(client, case, two_orgs)


async def test_check_fails_when_positive_control_fails(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = ResourceRoute(
        "GET", "/probe/always-not-found/{workspace_id}", {"workspace_id": "workspaces"}
    )

    with pytest.raises(AssertionError, match=r"positive control \(own ids\) answered 404"):
        await _run_route_check(app_engine, two_orgs, probes.always_not_found_router(), case)


async def test_leak_messages_never_contain_fixture_values(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = ResourceRoute("GET", "/probe/workspaces/{workspace_id}", {"workspace_id": "workspaces"})

    with pytest.raises(AssertionError) as failure:
        await _run_route_check(app_engine, two_orgs, probes.unscoped_lookup_router(two_orgs), case)

    message = str(failure.value)
    assert not any(marker in message for marker in two_orgs.b.markers())


# --- background jobs (AC3) ------------------------------------------------------------------------


def _target(rows: OrgRows) -> dict[str, object]:
    return {"target": str(rows.org_id)}


async def test_job_check_fails_on_handler_that_switches_tenant(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = JobCase("probe.switch-tenant", _target)

    with pytest.raises(AssertionError, match=r"data of Organization B changed"):
        await assert_job_isolated(
            app_engine, probes.switching_job_registry(), case, two_orgs.a, two_orgs.b
        )


async def test_job_check_fails_on_handler_that_copies_other_organization_data_into_its_own(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = JobCase("probe.copy-other", _target)

    with pytest.raises(AssertionError, match=r"rows of Organization A: 1 marker"):
        await assert_job_isolated(
            app_engine, probes.copying_job_registry(), case, two_orgs.a, two_orgs.b
        )


async def test_job_check_passes_for_a_well_behaved_job(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = JobCase("sample.process", lambda rows: {"workspace_id": str(rows.workspace_id)})
    registry = sample_registry(Recorder())

    await assert_job_isolated(app_engine, registry, case, two_orgs.a, two_orgs.b)
    await assert_job_isolated(app_engine, registry, case, two_orgs.b, two_orgs.a)


async def test_job_check_fails_when_the_positive_control_fails(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    case = JobCase("sample.write-then-fail", lambda rows: {"secret": "x"})

    with pytest.raises(RuntimeError):
        await assert_job_isolated(
            app_engine, sample_registry(Recorder()), case, two_orgs.a, two_orgs.b
        )


def test_undeclared_job_is_reported() -> None:
    assert job_coverage_problems(probes.undeclared_job_registry(), ()) == [
        "job has no isolation test declared: probe.undeclared"
    ]


def test_case_for_a_job_that_does_not_exist_is_reported() -> None:
    case = JobCase("probe.gone", _target)

    assert job_coverage_problems(JobRegistry(), (case,)) == [
        "isolation case for a job that does not exist: probe.gone"
    ]


def test_probes_are_not_part_of_the_production_app() -> None:
    paths = {route.path for route in discover_routes(create_app())}

    assert not any(path.startswith("/probe") for path in paths)
