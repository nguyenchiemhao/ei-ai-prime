"""Test-only helpers for the sign-in routes: the app with a real directory, CSRF headers, cookies.

Never imported by ``src``. The server sets every cookie ``Secure`` and the tests talk plain
``http://test``, so cookies travel in an explicit ``Cookie`` header instead of the client's jar.
"""

import uuid
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.api.csrf import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from ei_ai.auth.credentials import upsert_credential
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.passwords import hash_password
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.db.tenant import tenant_transaction
from ei_ai.main import create_app
from ei_ai.readiness import Readiness

ORIGIN = "http://localhost:3000"
CSRF_TOKEN = "csrf-test-token-value"
PASSWORD = "correct horse battery staple"


async def _ok() -> None:
    return None


def auth_client(
    engine: AsyncEngine,
    directory: SignInDirectory,
    rate_limiter: RateLimiter | None = None,
    environment: str = "test",
) -> httpx.AsyncClient:
    """A client of the production app: default verifiers (the session cookie), a real directory."""
    app = create_app(
        readiness=Readiness(database=_ok, valkey=_ok),
        engine=engine,
        admin_base_url=ORIGIN,
        sign_in_directory=directory,
        rate_limiter=rate_limiter,
        environment=environment,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def request_headers(session: str | None = None, csrf: bool = True) -> dict[str, str]:
    """``Cookie`` (CSRF token and, if given, the session) plus the matching CSRF header."""
    cookies = [f"{CSRF_COOKIE}={CSRF_TOKEN}"] if csrf else []
    if session is not None:
        cookies.append(f"{SESSION_COOKIE}={session}")
    headers = {"Cookie": "; ".join(cookies)} if cookies else {}
    if csrf:
        headers[CSRF_HEADER] = CSRF_TOKEN
    return headers


def set_cookies(response: httpx.Response) -> dict[str, tuple[str, set[str]]]:
    """Cookie name -> (value, lower-cased attributes such as ``httponly`` or ``max-age=0``)."""
    cookies: dict[str, tuple[str, set[str]]] = {}
    for header in response.headers.get_list("set-cookie"):
        pair, *attributes = (part.strip() for part in header.split(";"))
        name, _, value = pair.partition("=")
        cookies[name] = (value, {attribute.lower() for attribute in attributes if attribute})
    return cookies


def session_cookie(response: httpx.Response) -> str:
    return set_cookies(response)[SESSION_COOKIE][0]


async def sign_in(
    client: httpx.AsyncClient, email: str, password: str, session: str | None = None
) -> httpx.Response:
    return await client.post(
        "/auth/sign-in",
        json={"email": email, "password": password},
        headers=request_headers(session),
    )


async def give_password(
    engine: AsyncEngine, org_id: uuid.UUID, user_id: uuid.UUID, password: str = PASSWORD
) -> None:
    hashed = await hash_password(password)
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        await upsert_credential(conn, org_id, user_id, hashed)


async def in_tenant(
    engine: AsyncEngine, org_id: uuid.UUID, sql: str, params: dict[str, Any] | None = None
) -> list[Any]:
    """Run one statement in a tenant transaction; the rows it returns (empty for no result)."""
    async with engine.connect() as conn, tenant_transaction(conn, org_id):
        result = await conn.execute(text(sql), {"org": org_id, **(params or {})})
        return list(result.all()) if result.returns_rows else []


async def audit_count(
    engine: AsyncEngine, org_id: uuid.UUID, action: str, actor: str, target: uuid.UUID
) -> int:
    rows = await in_tenant(
        engine,
        org_id,
        "SELECT count(*) FROM audit_events WHERE org_id = :org AND action = :action"
        " AND actor = :actor AND target_type = 'user' AND target_id = :target",
        {"action": action, "actor": actor, "target": target},
    )
    count: int = rows[0][0]
    return count
