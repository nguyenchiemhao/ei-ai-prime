"""Double-submit CSRF protection for cookie-authenticated requests (EA-22)."""

import hmac
import secrets
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from ei_ai.auth.sessions import SESSION_COOKIE
from ei_ai.rbac.declarations import public

CSRF_COOKIE = "ei_csrf"
CSRF_HEADER = "X-CSRF-Token"

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "CsrfMiddleware",
    "origin_of",
    "router",
    "set_csrf_cookie",
]

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTH_PREFIX = "/auth/"

router = APIRouter()


def origin_of(base_url: str) -> str:
    """``scheme://host[:port]`` of a URL."""
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


def set_csrf_cookie(response: Response) -> str:
    """Issue a fresh token as a script-readable cookie (double submit) and return it."""
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE, token, secure=True, httponly=False, samesite="strict", path="/"
    )
    return token


class CsrfToken(BaseModel):
    csrf_token: str


@router.get(
    "/auth/csrf",
    response_model=CsrfToken,
    dependencies=[Depends(public("issues an anonymous CSRF token, no tenant data"))],
    summary="Issue an anonymous CSRF token",
)
def issue_csrf_token(response: Response) -> CsrfToken:
    """Sets the ``ei_csrf`` cookie and returns the same token; carries no tenant data."""
    return CsrfToken(csrf_token=set_csrf_cookie(response))


def _is_protected(request: Request) -> bool:
    if request.method not in _UNSAFE_METHODS:
        return False
    return request.url.path.startswith(_AUTH_PREFIX) or SESSION_COOKIE in request.cookies


class CsrfMiddleware(BaseHTTPMiddleware):
    """``allowed_origin`` is read per request: the app learns it from its settings at startup."""

    def __init__(self, app: ASGIApp, allowed_origin: Callable[[], str]) -> None:
        super().__init__(app)
        self._allowed_origin = allowed_origin

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_protected(request) and not self._passes(request):
            return JSONResponse(status_code=403, content={"detail": "csrf_failed"})
        return await call_next(request)

    def _passes(self, request: Request) -> bool:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header:
            return False
        if not hmac.compare_digest(cookie.encode(), header.encode()):
            return False
        origin = request.headers.get("origin")
        if origin is None:
            return True
        allowed = self._allowed_origin()
        return bool(allowed) and origin == allowed  # no origin configured: nothing matches
