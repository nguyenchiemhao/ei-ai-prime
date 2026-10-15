"""Every route of the app and every registered job needs one entry here.

A new route without an entry fails CI with
``route has no isolation test declared: <METHOD> <path>``. See README, "Writing isolation
tests", for which kind to pick and how to fill it in.
"""

from support.isolation.cases import JobCase, OwnTenantRoute, PublicRoute, RouteCase

ROUTE_CASES: tuple[RouteCase, ...] = (
    OwnTenantRoute("GET", "/organization"),
    PublicRoute("GET", "/healthz", "liveness probe, no tenant data"),
    PublicRoute("GET", "/readyz", "readiness probe, component names only"),
)

JOB_CASES: tuple[JobCase, ...] = ()
