"""The CI guard of AC1: every route declares exactly one permission, and the declarations equal
the reviewed table (``tests/rbac/route_permissions.py``).

A new route is red until it uses ``requires``, ``requires_org``, ``signed_in`` or ``public`` and
is added to the reviewed table; a changed permission is red until the table changes too, which a
reviewer sees in the diff.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from ei_ai.auth.dependencies import current_principal
from ei_ai.rbac.declarations import PUBLIC, SIGNED_IN, declared
from ei_ai.rbac.permissions import Permission
from ei_ai.tenancy.context import require_tenant

RouteKey = tuple[str, str]


@dataclass(frozen=True)
class DeclaredRoute:
    method: str
    path: str
    declarations: tuple[str, ...]
    takes_identity: bool
    tenant_scoped: bool

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


def _dependants(dependant: Any) -> Iterator[Any]:
    yield dependant
    for child in dependant.dependencies:
        yield from _dependants(child)


def declared_routes(app: FastAPI) -> list[DeclaredRoute]:
    """One entry per HTTP method of every API route of the app (the documentation routes of
    FastAPI itself are left out)."""
    framework = {
        path
        for path in (
            app.openapi_url,
            app.docs_url,
            app.redoc_url,
            app.swagger_ui_oauth2_redirect_url,
        )
        if path
    }
    found: list[DeclaredRoute] = []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute) and context.path in framework:
            continue
        calls = [d.call for d in _dependants(context.dependant)]
        declarations = tuple(d for d in (declared(call) for call in calls) if d is not None)
        for method in sorted(context.methods or ()):
            found.append(
                DeclaredRoute(
                    method=method,
                    path=str(context.path),
                    declarations=declarations,
                    takes_identity=current_principal in calls,
                    tenant_scoped=require_tenant in calls,
                )
            )
    return found


def _declaration_problems(route: DeclaredRoute) -> list[str]:
    if not route.declarations:
        return [f"route has no permission declared: {route.label}"]
    if len(route.declarations) > 1:
        return [f"route declares more than one permission: {route.label}"]
    if route.declarations[0] == PUBLIC:
        return [f"public route takes an identity: {route.label}"] if route.takes_identity else []
    if not route.tenant_scoped:
        return [f"permission route is not tenant scoped: {route.label}"]
    declaration = route.declarations[0]
    if (
        declaration != SIGNED_IN
        and Permission(declaration).scope == "workspace"
        and "{workspace_id}" not in route.path
    ):
        return [f"workspace route has no {{workspace_id}} in its path: {route.label}"]
    return []


def declaration_problems(app: FastAPI, reviewed: Mapping[RouteKey, str]) -> list[str]:
    """Everything wrong with the route declarations; empty means the guard is green."""
    routes = declared_routes(app)
    problems: list[str] = []
    for route in routes:
        route_problems = _declaration_problems(route)
        problems += route_problems
        if route_problems:
            continue
        declaration = route.declarations[0]
        expected = reviewed.get((route.method, route.path))
        if expected != declaration:
            problems.append(
                f"route permission differs from the reviewed table: {route.label}"
                f" (declared {declaration}, reviewed {expected or 'nothing'})"
            )
    existing = {(route.method, route.path) for route in routes}
    problems += [
        f"reviewed route that does not exist: {method} {path}"
        for method, path in reviewed
        if (method, path) not in existing
    ]
    return problems
