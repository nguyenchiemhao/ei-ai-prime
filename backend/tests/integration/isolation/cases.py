"""Every route of the app and every registered job needs one entry here.

A new route without an entry fails CI with
``route has no isolation test declared: <METHOD> <path>``. See README, "Writing isolation
tests", for which kind to pick and how to fill it in.
"""

from support.isolation.cases import (
    JobCase,
    OwnTenantRoute,
    PublicRoute,
    ResourceRoute,
    RouteCase,
)

ROUTE_CASES: tuple[RouteCase, ...] = (
    OwnTenantRoute("GET", "/organization"),
    OwnTenantRoute("GET", "/auth/session"),
    ResourceRoute("GET", "/workspaces/{workspace_id}", {"workspace_id": "workspaces"}),
    PublicRoute("GET", "/healthz", "liveness probe, no tenant data"),
    PublicRoute("GET", "/readyz", "readiness probe, component names only"),
    PublicRoute("GET", "/auth/csrf", "issues an anonymous CSRF token, no tenant data"),
    PublicRoute(
        "POST",
        "/auth/sign-in",
        "pre-auth sign-in; the Organization comes from the verified password, never the request",
    ),
    PublicRoute(
        "POST",
        "/auth/sign-out",
        "ends the caller's own session cookie, if any; answers 204 with no tenant data",
    ),
    PublicRoute(
        "POST",
        "/auth/forgot-password",
        "pre-auth; always 202 whatever the email, links only in local/test, no tenant data",
    ),
    PublicRoute(
        "POST",
        "/auth/set-password",
        "pre-auth; the Organization comes from the one-time token, matched inside it only",
    ),
)

JOB_CASES: tuple[JobCase, ...] = ()
