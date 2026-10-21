"""AC1: every route of the app declares exactly one permission and CI fails when it does not.

No database needed: the guard reads the route table of the production ``create_app()``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI

from ei_ai.auth.dependencies import current_principal
from ei_ai.auth.principal import Principal
from ei_ai.main import create_app
from ei_ai.rbac.access import WorkspaceAccess
from ei_ai.rbac.declarations import public, requires
from ei_ai.rbac.permissions import Permission
from rbac.route_permissions import ROUTE_PERMISSIONS
from support.rbac.routes import declaration_problems


def _app_with(router: APIRouter) -> FastAPI:
    app = create_app()
    app.include_router(router)
    return app


def test_every_route_declares_a_permission() -> None:
    problems = [
        problem
        for problem in declaration_problems(create_app(), ROUTE_PERMISSIONS)
        if "no permission declared" in problem or "more than one" in problem
    ]

    assert not problems, "\n".join(problems)


def test_declarations_match_the_reviewed_table() -> None:
    problems = declaration_problems(create_app(), ROUTE_PERMISSIONS)

    assert not problems, "\n".join(problems)


def test_guard_catches_an_undeclared_route() -> None:
    router = APIRouter()

    @router.get("/rbac-probe/undeclared")
    async def undeclared() -> dict[str, str]:
        return {}

    problems = declaration_problems(_app_with(router), ROUTE_PERMISSIONS)

    assert problems == ["route has no permission declared: GET /rbac-probe/undeclared"]


def test_guard_catches_a_route_with_two_declarations() -> None:
    router = APIRouter()

    @router.get(
        "/rbac-probe/two/{workspace_id}",
        dependencies=[Depends(requires(Permission.MEMBERS_VIEW)), Depends(public("probe"))],
    )
    async def two() -> dict[str, str]:
        return {}

    problems = declaration_problems(_app_with(router), ROUTE_PERMISSIONS)

    assert problems == [
        "route declares more than one permission: GET /rbac-probe/two/{workspace_id}"
    ]


def test_guard_catches_a_changed_permission() -> None:
    changed = {**ROUTE_PERMISSIONS, ("GET", "/workspaces/{workspace_id}"): "members.manage"}

    problems = declaration_problems(create_app(), changed)

    assert problems == [
        "route permission differs from the reviewed table: GET /workspaces/{workspace_id}"
        " (declared workspace.access, reviewed members.manage)"
    ]


def test_guard_catches_a_route_missing_from_the_table() -> None:
    router = APIRouter()

    @router.get("/rbac-probe/new/{workspace_id}")
    async def new(
        access: Annotated[WorkspaceAccess, Depends(requires(Permission.MEMBERS_VIEW))],
    ) -> None:
        return None

    problems = declaration_problems(_app_with(router), ROUTE_PERMISSIONS)

    assert problems == [
        "route permission differs from the reviewed table: GET /rbac-probe/new/{workspace_id}"
        " (declared members.view, reviewed nothing)"
    ]


def test_guard_catches_a_reviewed_route_that_does_not_exist() -> None:
    stale = {**ROUTE_PERMISSIONS, ("GET", "/gone"): "public"}

    problems = declaration_problems(create_app(), stale)

    assert problems == ["reviewed route that does not exist: GET /gone"]


def test_guard_catches_a_public_route_with_identity() -> None:
    router = APIRouter()

    @router.get("/rbac-probe/public-with-identity", dependencies=[Depends(public("probe"))])
    async def leaky(principal: Annotated[Principal, Depends(current_principal)]) -> dict[str, str]:
        return {}

    problems = declaration_problems(_app_with(router), ROUTE_PERMISSIONS)

    assert problems == ["public route takes an identity: GET /rbac-probe/public-with-identity"]


def test_guard_catches_a_workspace_route_without_workspace_id_in_the_path() -> None:
    router = APIRouter()

    @router.get("/rbac-probe/assistants")
    async def assistants(
        access: Annotated[WorkspaceAccess, Depends(requires(Permission.ASSISTANTS_MANAGE))],
    ) -> None:
        return None

    problems = declaration_problems(_app_with(router), ROUTE_PERMISSIONS)

    assert problems == [
        "workspace route has no {workspace_id} in its path: GET /rbac-probe/assistants"
    ]
