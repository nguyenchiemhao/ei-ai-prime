"""Request fields that must not exist (D32, data-model.md tenant flow step 5).

A request never names an Organization (the token does) and never chooses a primary key (the
database generates ids). Both are read from the OpenAPI schema of the app: parameters of every
kind and request-body properties at any depth. Routes left out of the schema
(``include_in_schema=False``) are checked from their dependency tree instead.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from ei_ai.tenancy.context import is_org_field

from .routes import DiscoveredRoute

_OPERATIONS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved: dict[str, Any] = components.get(ref.rsplit("/", 1)[-1], {})
        return resolved
    return schema


def _properties(
    schema: dict[str, Any], components: dict[str, Any], depth: int, seen: frozenset[str]
) -> Iterator[tuple[str, int]]:
    """(property name, depth) of every property reachable from ``schema``. A list of objects
    (``items``) and a map of objects (``additionalProperties``) add no depth: the properties of
    ``list[Item]`` are the top-level properties of the body."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return
        seen = seen | {ref}
    schema = _resolve(schema, components)
    for name, sub in schema.get("properties", {}).items():
        yield name, depth
        yield from _properties(sub, components, depth + 1, seen)
    for container in ("items", "additionalProperties"):
        if isinstance(schema.get(container), dict):
            yield from _properties(schema[container], components, depth, seen)
    for combinator in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(combinator, []):
            yield from _properties(sub, components, depth, seen)


def _problems(
    label: str, parameter_names: Sequence[str], body: Iterator[tuple[str, int]]
) -> set[str]:
    problems = set()
    names = list(parameter_names)
    for name, depth in body:
        names.append(name)
        if name == "id" and depth == 0:
            problems.add(f"{label}: request body declares id (the server generates ids)")
    problems.update(
        f"{label}: request field {name} names an Organization (D32)"
        for name in names
        if is_org_field(name)
    )
    return problems


def forbidden_request_fields(
    openapi: dict[str, Any], hidden_routes: Sequence[DiscoveredRoute] = ()
) -> list[str]:
    """Problems found in the request side of every operation; empty means none. Pass the routes
    that are not in the OpenAPI schema as ``hidden_routes``."""
    components = openapi.get("components", {}).get("schemas", {})
    problems: set[str] = set()
    for path, item in openapi.get("paths", {}).items():
        for method in _OPERATIONS:
            operation = item.get(method)
            if operation is None:
                continue
            parameters = [
                p["name"] for p in [*item.get("parameters", []), *operation.get("parameters", [])]
            ]
            body = (
                found
                for content in operation.get("requestBody", {}).get("content", {}).values()
                for found in _properties(content.get("schema", {}), components, 0, frozenset())
            )
            problems |= _problems(f"{method.upper()} {path}", parameters, body)
    for route in hidden_routes:
        body = (
            found
            for schema in route.body_schemas
            for found in _properties(
                schema, {**components, **schema.get("$defs", {})}, 0, frozenset()
            )
        )
        problems |= _problems(route.label, route.param_names, body)
    return sorted(problems)
