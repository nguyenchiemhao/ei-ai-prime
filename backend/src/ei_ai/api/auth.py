"""Admin sign-in, sign-out and session info (EA-22, contract "API").

Pre-auth routes take no identity: sign-in proves one with a password, sign-out ends the caller's
own cookie. ``GET /auth/session`` is a tenant route like any other: the Principal comes from the
session cookie verifier only (D32). The CSRF middleware guards every POST here, and every answer
is ``Cache-Control: no-store`` (``api.no_store``). Errors are codes only; unexpected failures log
the exception class, never its message (it can carry the submitted email, D52).
"""

import logging
import math
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ei_ai.api.csrf import set_csrf_cookie
from ei_ai.api.deps import TenantSession
from ei_ai.api.errors import ErrorCode
from ei_ai.auth.client_ip import client_ip
from ei_ai.auth.dependencies import UNAUTHENTICATED
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.password_reset import request_reset
from ei_ai.auth.passwords import check_policy, hash_password
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.auth.sessions import SESSION_COOKIE
from ei_ai.auth.set_password import set_password_with_token
from ei_ai.auth.sign_in import sign_in, sign_out
from ei_ai.auth.tokens import parse_token
from ei_ai.db.models import Organization, User
from ei_ai.tenancy.context import TenantContext, require_tenant
from ei_ai.workspaces.memberships import default_workspace_id, list_workspaces

logger = logging.getLogger("ei_ai.auth")

INVALID_CREDENTIALS = "invalid_credentials"
RATE_LIMITED = "rate_limited"
INVALID_TOKEN = "invalid_token"
INTERNAL_ERROR = "internal_error"

router = APIRouter()


class AuthRouteFailed(Exception):
    """An unexpected failure in an auth route, re-raised without the original message."""


async def _route_failed(_request: Request, _error: Exception) -> JSONResponse:
    # ``_guarded`` already logged the class; nothing more is logged here.
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR})


def install_failure_handler(app: FastAPI) -> None:
    """``AuthRouteFailed`` becomes a plain 500 ``{"detail": "internal_error"}`` inside the app.

    Unhandled, the server would print a traceback whose frames quote the route's source (the
    word "password" included), and the answer would bypass the no-store middleware.
    """
    app.add_exception_handler(AuthRouteFailed, _route_failed)


class SignInRequest(BaseModel):
    """No length or format rules (R36): a wrong pair is simply ``invalid_credentials``."""

    model_config = ConfigDict(strict=True)

    email: str
    password: str


class ForgotRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    email: str


class SetCredentialRequest(BaseModel):
    """The one-time token and the new secret; the policy is checked in the route (R14)."""

    model_config = ConfigDict(strict=True)

    token: str
    password: str


class SignInResponse(BaseModel):
    default_workspace_id: UUID | None


class SessionUser(BaseModel):
    id: UUID
    display_name: str
    email: str


class SessionOrganization(BaseModel):
    id: UUID
    name: str


class SessionWorkspace(BaseModel):
    id: UUID
    name: str
    role: str


class SessionInfo(BaseModel):
    user: SessionUser
    organization: SessionOrganization
    workspaces: list[SessionWorkspace]
    default_workspace_id: UUID | None


def rate_limit(scope: str) -> Callable[[Request], Awaitable[None]]:
    """A dependency counting one request of ``scope`` per client IP (R12); 429 over the limit.

    ``async`` on purpose: it runs on the event loop, never in the thread pool, because the
    limiter is not thread-safe."""

    async def check(request: Request) -> None:
        state = request.app.state
        limiter: RateLimiter = state.rate_limiter
        retry_after = limiter.hit(f"{scope}:{client_ip(request, state.trust_proxy_headers)}")
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail=RATE_LIMITED,
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )

    return check


def _directory(request: Request) -> SignInDirectory:
    directory: SignInDirectory | None = request.app.state.sign_in_directory
    if directory is None:
        raise RuntimeError("the sign-in directory is not configured")
    return directory


async def _guarded[T](operation: str, work: Awaitable[T]) -> T:
    try:
        return await work
    except Exception as error:
        # Class name only: a database error message can quote the submitted email.
        logger.error("auth_route_failed operation=%s error=%s", operation, type(error).__name__)
        raise AuthRouteFailed from None


def _set_session_cookie(response: Response, cookie: str) -> None:
    # A browser-session cookie (no Max-Age/Expires): the server enforces the idle timeout (R5, R6).
    response.set_cookie(
        SESSION_COOKIE, cookie, secure=True, httponly=True, samesite="lax", path="/"
    )


_REJECTED = {"model": ErrorCode, "description": "Wrong email or password, or locked (identical)"}
_LIMITED = {"model": ErrorCode, "description": "Too many attempts from this address"}
_CSRF = {"model": ErrorCode, "description": "Missing or wrong CSRF token or Origin (csrf_failed)"}
_INVALID = {"model": ErrorCode, "description": "Missing or non-string field (invalid_request)"}


@router.post(
    "/auth/sign-in",
    response_model=SignInResponse,
    responses={401: _REJECTED, 403: _CSRF, 422: _INVALID, 429: _LIMITED},
    dependencies=[Depends(rate_limit("sign-in"))],
    summary="Sign in with email and password",
)
async def post_sign_in(body: SignInRequest, request: Request, response: Response) -> SignInResponse:
    """Sets the ``ei_session`` cookie and a new ``ei_csrf``; every rejection answers alike."""
    signed_in = await _guarded(
        "sign_in",
        sign_in(
            request.app.state.engine,
            _directory(request),
            body.email,
            body.password,
            request.cookies.get(SESSION_COOKIE),
        ),
    )
    if signed_in is None:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)
    _set_session_cookie(response, signed_in.cookie)
    set_csrf_cookie(response)
    return SignInResponse(default_workspace_id=signed_in.default_workspace_id)


@router.post(
    "/auth/sign-out",
    status_code=204,
    response_class=Response,
    responses={403: _CSRF},
    summary="Sign out: end the session of this cookie",
)
async def post_sign_out(request: Request) -> Response:
    """Always 204 (idempotent): deletes the session, clears ``ei_session``, rotates ``ei_csrf``."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        await _guarded("sign_out", sign_out(request.app.state.engine, cookie))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
    set_csrf_cookie(response)
    return response


@router.get(
    "/auth/session",
    response_model=SessionInfo,
    responses={401: {"model": ErrorCode, "description": "No live session (unauthenticated)"}},
    summary="The signed-in user, their Organization and their Workspaces",
)
async def get_session(
    tenant: Annotated[TenantContext, Depends(require_tenant)], session: TenantSession
) -> SessionInfo:
    """Only the caller's own rows: explicit ``org_id`` filters plus row-level security (D46)."""
    user = (
        await session.execute(
            select(User.id, User.display_name, User.email).where(
                User.org_id == tenant.org_id, User.id == tenant.user_id
            )
        )
    ).one_or_none()
    organization = (
        await session.execute(
            select(Organization.id, Organization.name).where(Organization.id == tenant.org_id)
        )
    ).one_or_none()
    if user is None or organization is None:
        raise HTTPException(status_code=401, detail=UNAUTHENTICATED)
    conn = await session.connection()
    workspaces = await list_workspaces(conn, tenant.org_id, tenant.user_id)
    return SessionInfo(
        user=SessionUser(id=user.id, display_name=user.display_name, email=user.email),
        organization=SessionOrganization(id=organization.id, name=organization.name),
        workspaces=[SessionWorkspace(id=w.id, name=w.name, role=w.role) for w in workspaces],
        default_workspace_id=await default_workspace_id(conn, tenant.org_id, tenant.user_id),
    )


@router.post(
    "/auth/forgot-password",
    status_code=202,
    response_class=Response,
    responses={403: _CSRF, 422: _INVALID, 429: _LIMITED},
    dependencies=[Depends(rate_limit("forgot"))],
    summary="Ask for a reset link (always 202, whatever the email)",
)
async def post_forgot(body: ForgotRequest, request: Request) -> Response:
    """Local/test: prints one link per account found. Elsewhere: nothing. Never reveals a match."""
    state = request.app.state
    await _guarded(
        "reset_request",
        request_reset(
            state.engine,
            _directory(request),
            body.email,
            state.environment,
            state.admin_base_url,
        ),
    )
    return Response(status_code=202)


@router.post(
    "/auth/set-password",
    status_code=204,
    response_class=Response,
    responses={
        400: {"model": ErrorCode, "description": "Unknown, used, expired or malformed link"},
        403: _CSRF,
        422: {"model": ErrorCode, "description": "Password policy or invalid_request"},
        429: _LIMITED,
    },
    dependencies=[Depends(rate_limit("set-password"))],
    summary="Set a new password with a one-time link",
)
async def post_set_password(body: SetCredentialRequest, request: Request) -> Response:
    """The policy is checked before the token (a short value leaves the link usable); a malformed
    token is refused before any hashing; the hash is computed outside the transaction; redeem,
    store, end sessions and audit are one transaction."""
    violation = check_policy(body.password)
    if violation is not None:
        raise HTTPException(status_code=422, detail=violation)
    if parse_token(body.token) is None:
        raise HTTPException(status_code=400, detail=INVALID_TOKEN)
    hashed = await _guarded("hash_secret", hash_password(body.password))
    user_id = await _guarded(
        "redeem_link",
        set_password_with_token(request.app.state.engine, body.token, hashed),
    )
    if user_id is None:
        raise HTTPException(status_code=400, detail=INVALID_TOKEN)
    return Response(status_code=204)
