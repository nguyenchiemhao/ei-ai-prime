"""What a developer declares for each route and job (the declarations live in
``tests/integration/isolation/cases.py``).

``ResourceRoute``  a path parameter names a tenant resource: another Organization's id must answer
                   403/404, identically to an unknown id.
``OwnTenantRoute`` no resource id in the path: the Organization comes from the token only, so forged
                   Organization fields are ignored and nothing of the other Organization appears.
``PublicRoute``    no identity required; the answer must contain no tenant data, whatever the caller
                   claims (forged Organization fields, any Organization's ids).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from support.tenants import OrgRows

BodyBuilder = Callable[[OrgRows], dict[str, object]]
ContentBuilder = Callable[[OrgRows], tuple[bytes, dict[str, str]]]


@dataclass(frozen=True)
class ResourceRoute:
    """``resources`` maps every path parameter, and every id query parameter, to the fixture
    table whose row id it takes (``OrgRows.row_id``). ``body`` builds the JSON body from the
    fixture rows whose ids it should carry. ``content`` is for routes with a raw body: it builds
    the bytes and the headers to send (instead of ``body``)."""

    method: str
    path: str
    resources: Mapping[str, str]
    body: BodyBuilder | None = None
    ok_status: int = 200
    content: ContentBuilder | None = None


@dataclass(frozen=True)
class OwnTenantRoute:
    """``query_resources`` maps id query filters to fixture tables. ``body`` is built from the
    caller's own rows: the route has no other Organization's resource to name."""

    method: str
    path: str
    query_resources: Mapping[str, str] = field(default_factory=dict)
    body: BodyBuilder | None = None
    ok_status: int = 200


@dataclass(frozen=True)
class PublicRoute:
    """A route that needs no identity. It is not an exemption: the suite calls it once per
    Organization, with that Organization's id in every Organization header and query parameter and
    its fixture ids in ``resources`` (path parameters, id query parameters), and requires that
    nothing of either Organization comes back."""

    method: str
    path: str
    reason: str
    resources: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("a public route needs a reason")


RouteCase = ResourceRoute | OwnTenantRoute | PublicRoute


@dataclass(frozen=True)
class JobCase:
    """``payload`` builds the job payload from the fixture rows it should act on."""

    kind: str
    payload: Callable[[OrgRows], dict[str, object]]


def key(case: RouteCase) -> tuple[str, str]:
    return (case.method.upper(), case.path)
