"""Route discovery and the coverage rules (AC2): every route of the app needs an isolation case.

Discovery walks the routes of the real app, including the ones FastAPI includes lazily from
routers and the ones hidden from the OpenAPI schema, and classifies each by its dependency tree.
"""

import re
import typing
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import TypeAdapter

from ei_ai.auth.dependencies import current_principal
from ei_ai.tenancy.context import is_org_field, require_tenant

from .cases import OwnTenantRoute, PublicRoute, ResourceRoute, RouteCase, key

_OPENAPI_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


class UnsupportedRoute(Exception):
    """A route type the suite cannot test yet (for example a WebSocket)."""


@dataclass(frozen=True)
class DiscoveredRoute:
    method: str
    path: str
    authenticated: bool
    tenant_scoped: bool
    path_params: tuple[str, ...]
    id_query_params: tuple[str, ...]
    in_schema: bool
    # For routes hidden from the OpenAPI schema only (fields.py reads the schema for the others):
    param_names: tuple[str, ...] = ()
    body_schemas: tuple[dict[str, Any], ...] = ()

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


def _dependants(dependant: Any) -> Iterator[Any]:
    yield dependant
    for child in dependant.dependencies:
        yield from _dependants(child)


def _is_uuid(annotation: object) -> bool:
    return annotation is uuid.UUID or uuid.UUID in typing.get_args(annotation)


def _hidden_request_fields(dependants: list[Any]) -> dict[str, Any]:
    """Parameter names and body JSON schemas of a route that the OpenAPI schema does not show."""
    kinds = ("path_params", "query_params", "header_params", "cookie_params")
    return {
        "param_names": tuple(
            f.name for d in dependants for kind in kinds for f in getattr(d, kind)
        ),
        "body_schemas": tuple(
            TypeAdapter(f.field_info.annotation).json_schema()
            for d in dependants
            for f in d.body_params
        ),
    }


_ID_NAME = re.compile(r"^id$|_id$|[a-z]Id$")


def _carries_an_id(field: Any) -> bool:
    """A query parameter that holds an id: typed ``UUID``, or named like one (``id``,
    ``workspace_id``, ``workspaceId``) whatever its type. Organization fields are left to the
    request-field check, which fails on them anyway."""
    if is_org_field(field.name):
        return False
    return _is_uuid(field.field_info.annotation) or bool(_ID_NAME.search(field.name))


def _framework_paths(app: FastAPI) -> set[str]:
    wanted = (app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url)
    return {path for path in wanted if path}


def discover_routes(app: FastAPI) -> list[DiscoveredRoute]:
    """One entry per HTTP method of every route. Raises ``UnsupportedRoute`` for a route that is
    neither an API route nor one of FastAPI's own documentation routes."""
    framework = _framework_paths(app)
    found: list[DiscoveredRoute] = []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute):
            if context.path in framework:
                continue
            kind = type(context.original_route).__name__
            raise UnsupportedRoute(
                f"{context.path}: route type {kind} is not covered by the isolation suite"
            )
        dependants = list(_dependants(context.dependant))
        calls = {d.call for d in dependants}
        query = [f for d in dependants for f in d.query_params]
        in_schema = bool(context.include_in_schema)
        hidden = {} if in_schema else _hidden_request_fields(dependants)
        for method in sorted(context.methods or ()):
            found.append(
                DiscoveredRoute(
                    method=method,
                    path=str(context.path),
                    authenticated=current_principal in calls,
                    tenant_scoped=require_tenant in calls,
                    path_params=tuple(f.name for d in dependants for f in d.path_params),
                    id_query_params=tuple(f.name for f in query if _carries_an_id(f)),
                    in_schema=in_schema,
                    **hidden,
                )
            )
    return found


def openapi_operations(app: FastAPI) -> set[tuple[str, str]]:
    """(METHOD, path) of every operation in the generated OpenAPI schema."""
    return {
        (method.upper(), path)
        for path, item in app.openapi().get("paths", {}).items()
        for method in item
        if method in _OPENAPI_METHODS
    }


def _singular(table: str) -> str:
    return table.removesuffix("s")


def _case_problems(route: DiscoveredRoute, case: RouteCase) -> list[str]:
    label = route.label
    problems: list[str] = []
    if isinstance(case, PublicRoute):
        if route.authenticated:
            return [f"route declared public but requires an identity: {label}"]
        path_resources = query_resources = case.resources
        problems += [
            f"public route parameter {{{name}}} of {label} maps to {table};"
            f" the parameter must be called {_singular(table)}_id"
            for name, table in case.resources.items()
            if name != f"{_singular(table)}_id"
        ]
    else:
        if not route.authenticated:
            problems.append(
                f"public route declared with an isolation case kind for tenant routes: {label}"
            )
        elif not route.tenant_scoped:
            problems.append(f"authenticated route does not depend on require_tenant: {label}")
        path_resources = case.resources if isinstance(case, ResourceRoute) else {}
        query_resources = (
            case.query_resources if isinstance(case, OwnTenantRoute) else path_resources
        )
    problems += [
        f"path parameter {{{name}}} of {label} has no fixture resource in its isolation case"
        for name in route.path_params
        if name not in path_resources
    ]
    problems += [
        f"id query parameter {{{name}}} of {label} has no fixture resource in its isolation case"
        for name in route.id_query_params
        if name not in query_resources
    ]
    return problems


def coverage_problems(routes: Sequence[DiscoveredRoute], cases: Sequence[RouteCase]) -> list[str]:
    """Everything wrong with the declarations; empty means every route is covered."""
    by_key = {key(case): case for case in cases}
    problems = [
        f"duplicate isolation case: {method} {path}"
        for (method, path), count in Counter(key(case) for case in cases).items()
        if count > 1
    ]
    for route in routes:
        case = by_key.get((route.method, route.path))
        if case is None:
            problems.append(f"route has no isolation test declared: {route.label}")
        else:
            problems += _case_problems(route, case)
    existing = {(route.method, route.path) for route in routes}
    problems += [
        f"isolation case for a route that does not exist: {method} {path}"
        for method, path in by_key
        if (method, path) not in existing
    ]
    return problems
