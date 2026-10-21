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
    ResourceRoute("GET", "/workspaces/{workspace_id}/members", {"workspace_id": "workspaces"}),
    ResourceRoute(
        "POST",
        "/workspaces/{workspace_id}/members",
        {"workspace_id": "workspaces"},
        body=lambda r: {"email": f"invitee-{r.suffix}@example.invalid", "role": "viewer"},
        ok_status=201,
    ),
    ResourceRoute(
        "PUT",
        "/workspaces/{workspace_id}/members/{user_id}",
        {"workspace_id": "workspaces", "user_id": "users"},
        body=lambda r: {"role": "reviewer"},
    ),
    ResourceRoute(
        "DELETE",
        "/workspaces/{workspace_id}/members/{user_id}",
        {"workspace_id": "workspaces", "user_id": "users"},
        ok_status=204,
    ),
    ResourceRoute("GET", "/workspaces/{workspace_id}/collections", {"workspace_id": "workspaces"}),
    ResourceRoute(
        "POST",
        "/workspaces/{workspace_id}/collections",
        {"workspace_id": "workspaces"},
        body=lambda r: {"name": f"qa-iso-{r.suffix}", "access_level": "authenticated"},
        ok_status=201,
    ),
    ResourceRoute(
        "GET",
        "/workspaces/{workspace_id}/collections/{collection_id}",
        {"workspace_id": "workspaces", "collection_id": "collections"},
    ),
    ResourceRoute(
        "PATCH",
        "/workspaces/{workspace_id}/collections/{collection_id}",
        {"workspace_id": "workspaces", "collection_id": "collections"},
        body=lambda r: {"name": f"qa-iso-{r.suffix}"},
    ),
    ResourceRoute(
        "PUT",
        "/workspaces/{workspace_id}/collections/{collection_id}/access",
        {"workspace_id": "workspaces", "collection_id": "collections"},
        body=lambda r: {"access_level": "authenticated", "groups": []},
    ),
    ResourceRoute(
        "DELETE",
        "/workspaces/{workspace_id}/collections/{collection_id}",
        {"workspace_id": "workspaces", "collection_id": "collections"},
        ok_status=204,
    ),
    ResourceRoute(
        "POST",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders",
        {"workspace_id": "workspaces", "collection_id": "collections"},
        body=lambda r: {"name": f"qa-iso-{r.suffix}"},
        ok_status=201,
    ),
    ResourceRoute(
        "PATCH",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders/{folder_id}",
        {"workspace_id": "workspaces", "collection_id": "collections", "folder_id": "folders"},
        body=lambda r: {"name": f"qa-iso-{r.suffix}"},
    ),
    ResourceRoute(
        "DELETE",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders/{folder_id}",
        {"workspace_id": "workspaces", "collection_id": "collections", "folder_id": "folders"},
        ok_status=204,
    ),
    ResourceRoute(
        "PUT",
        "/organization/members/{user_id}/org-role",
        {"user_id": "users"},
        body=lambda r: {"org_role": "org_owner"},
    ),
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
