"""POST /auth/forgot-password and /auth/set-password on the real database (AC1, AC4; R16, R18, R45).

The reset line is the one allowed print, in local/test only. Setting a password ends the user's
sessions and clears a lockout in the same transaction as the redeem.
"""

import re
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.audit.events import (
    SYSTEM_ACTOR,
    USER_PASSWORD_SET,
    USER_SET_PASSWORD_LINK_ISSUED,
    user_actor,
)
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.auth.set_password import format_token, issue_token
from ei_ai.db.tenant import tenant_transaction
from support.sign_in import (
    PASSWORD,
    audit_count,
    auth_client,
    give_password,
    in_tenant,
    request_headers,
    session_cookie,
    sign_in,
)
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

NEW_PASSWORD = "a brand new long passphrase"
RESET_LINE = re.compile(
    r"^Reset link \(valid 24 h, shown once\): "
    r"http://\S+/reset#token=[0-9a-f-]{36}\.[A-Za-z0-9_-]{43}$"
)


async def _forgot(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post(
        "/auth/forgot-password", json={"email": email}, headers=request_headers()
    )


async def _set(client: httpx.AsyncClient, token: str, password: str) -> httpx.Response:
    return await client.post(
        "/auth/set-password", json={"token": token, "password": password}, headers=request_headers()
    )


async def _token(engine: AsyncEngine, rows: OrgRows) -> str:
    async with engine.connect() as conn, tenant_transaction(conn, rows.org_id):
        secret = await issue_token(conn, rows.org_id, rows.user_id)
    return format_token(rows.org_id, secret)


def _link_token(out: str) -> str:
    lines = [line for line in out.splitlines() if line]
    assert len(lines) == 1
    assert RESET_LINE.match(lines[0])
    return lines[0].split("#token=")[1]


async def _unused_tokens(engine: AsyncEngine, rows: OrgRows) -> int:
    found = await in_tenant(
        engine,
        rows.org_id,
        "SELECT count(*) FROM set_password_tokens"
        " WHERE org_id = :org AND user_id = :user AND used_at IS NULL",
        {"user": rows.user_id},
    )
    count: int = found[0][0]
    return count


async def test_forgot_password_prints_reset_line_in_local(
    client: httpx.AsyncClient,
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a

    response = await _forgot(client, a.email)

    assert response.status_code == 202
    assert response.content == b""
    token = _link_token(capsys.readouterr().out)
    assert token.startswith(str(a.org_id))
    assert (
        await audit_count(
            app_engine, a.org_id, USER_SET_PASSWORD_LINK_ISSUED, SYSTEM_ACTOR, a.user_id
        )
        == 1
    )
    # The printed link works.
    assert (await _set(client, token, NEW_PASSWORD)).status_code == 204


async def test_forgot_password_unknown_email_same_answer_and_no_output(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = await _forgot(client, f"{uuid.uuid4()}@example.invalid")

    assert response.status_code == 202
    assert response.content == b""
    assert capsys.readouterr().out == ""


async def test_forgot_password_production_issues_nothing(
    app_engine: AsyncEngine,
    directory: SignInDirectory,
    two_orgs: TwoOrgs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    before = await _unused_tokens(app_engine, a)
    async with auth_client(app_engine, directory, environment="production") as client:
        response = await _forgot(client, a.email)

    assert response.status_code == 202
    assert response.content == b""
    assert capsys.readouterr().out == ""
    assert await _unused_tokens(app_engine, a) == before
    assert (
        await audit_count(
            app_engine, a.org_id, USER_SET_PASSWORD_LINK_ISSUED, SYSTEM_ACTOR, a.user_id
        )
        == 0
    )


async def test_forgot_invalidates_previous_link(
    client: httpx.AsyncClient,
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    old = await _token(app_engine, a)

    await _forgot(client, a.email)
    new = _link_token(capsys.readouterr().out)

    assert (await _set(client, old, NEW_PASSWORD)).status_code == 400
    assert (await _set(client, new, NEW_PASSWORD)).status_code == 204


async def test_forgot_password_rate_limited_separately_from_sign_in(
    app_engine: AsyncEngine, directory: SignInDirectory, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    async with auth_client(app_engine, directory, RateLimiter(2)) as client:
        for _ in range(2):
            assert (await _forgot(client, a.email)).status_code == 202
        limited = await _forgot(client, a.email)
        sign_in_response = await sign_in(client, a.email, "whatever")

    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}
    assert sign_in_response.status_code == 401  # its own bucket


async def test_set_password_too_short_422_and_token_unused(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    token = await _token(app_engine, a)

    short = await _set(client, token, "x" * 11)
    long = await _set(client, token, "x" * 129)
    # The policy is checked before the token, so a bad token with a short password is also 422.
    short_bad_token = await _set(client, f"{a.org_id}.{'x' * 43}", "short")

    assert short.status_code == 422
    assert short.json() == {"detail": "password_too_short"}
    assert long.status_code == 422
    assert long.json() == {"detail": "password_too_long"}
    assert short_bad_token.json() == {"detail": "password_too_short"}
    assert await _unused_tokens(app_engine, a) == 1
    assert (await _set(client, token, "x" * 12)).status_code == 204


async def test_set_password_then_sign_in_works(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    token = await _token(app_engine, a)

    response = await _set(client, token, NEW_PASSWORD)

    assert response.status_code == 204
    assert response.content == b""
    assert (await sign_in(client, a.email, NEW_PASSWORD)).status_code == 200
    assert (await sign_in(client, a.email, PASSWORD)).status_code == 401
    assert (
        await audit_count(app_engine, a.org_id, USER_PASSWORD_SET, user_actor(a.user_id), a.user_id)
        == 1
    )
    stored = await in_tenant(
        app_engine,
        a.org_id,
        "SELECT password_hash FROM user_credentials WHERE org_id = :org AND user_id = :user",
        {"user": a.user_id},
    )
    assert stored[0][0].startswith("$argon2id$")


async def test_set_password_revokes_sessions_and_clears_lock(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    cookie = session_cookie(await sign_in(client, a.email, PASSWORD))
    for _ in range(5):
        await sign_in(client, a.email, "wrong wrong wrong wrong")
    assert (await sign_in(client, a.email, PASSWORD)).status_code == 401  # locked
    token = await _token(app_engine, a)

    assert (await _set(client, token, NEW_PASSWORD)).status_code == 204

    who = await client.get("/auth/session", headers=request_headers(cookie))
    assert who.status_code == 401
    credential = await in_tenant(
        app_engine,
        a.org_id,
        "SELECT failed_attempts, locked_until FROM user_credentials"
        " WHERE org_id = :org AND user_id = :user",
        {"user": a.user_id},
    )
    assert tuple(credential[0]) == (0, None)
    assert (await sign_in(client, a.email, NEW_PASSWORD)).status_code == 200


async def test_set_password_reused_token_400(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    token = await _token(app_engine, a)
    assert (await _set(client, token, NEW_PASSWORD)).status_code == 204

    reused = await _set(client, token, NEW_PASSWORD)
    other_org = await _set(client, f"{b.org_id}.{token.split('.')[1]}", NEW_PASSWORD)
    malformed = await _set(client, "not-a-token", NEW_PASSWORD)

    for response in (reused, other_org, malformed):
        assert response.status_code == 400
        assert response.json() == {"detail": "invalid_token"}


async def test_set_password_requires_csrf_and_string_fields(client: httpx.AsyncClient) -> None:
    no_csrf = await client.post("/auth/set-password", json={"token": "x", "password": NEW_PASSWORD})
    wrong_type = await client.post(
        "/auth/set-password", json={"token": "x", "password": 7}, headers=request_headers()
    )

    assert no_csrf.status_code == 403
    assert wrong_type.status_code == 422
    assert wrong_type.json() == {"detail": "invalid_request"}
