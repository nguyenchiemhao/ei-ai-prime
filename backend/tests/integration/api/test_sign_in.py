"""POST /auth/sign-in and /auth/sign-out on the real database (AC1, AC2, AC3, AC5).

Every rejection answers alike, lockout holds end to end, the session cookie is the only identity,
and nothing secret reaches a log, a print or a response.
"""

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.api.csrf import CSRF_COOKIE, SESSION_COOKIE
from ei_ai.audit.events import (
    SYSTEM_ACTOR,
    USER_LOCKED_OUT,
    USER_SIGNED_IN,
    USER_SIGNED_OUT,
    user_actor,
)
from ei_ai.auth import sign_in as sign_in_flow
from ei_ai.auth.directory import SignInDirectory
from ei_ai.auth.passwords import verify_password
from ei_ai.auth.rate_limit import RateLimiter
from ei_ai.auth.set_password import issue_token
from ei_ai.auth.tokens import format_token, hash_secret, parse_token
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from support.sign_in import (
    CSRF_TOKEN,
    PASSWORD,
    audit_count,
    auth_client,
    give_password,
    in_tenant,
    request_headers,
    session_cookie,
    set_cookies,
    sign_in,
)
from support.tenants import OrgRows, TwoOrgs

pytestmark = pytest.mark.integration

WRONG = "not the right password at all"
NEW_SECRET_PASSWORD = "yet another long passphrase"
PARALLEL = 8


def _secret(cookie: str) -> str:
    parsed = parse_token(cookie)
    assert parsed is not None
    return parsed[1]


async def _who(client: httpx.AsyncClient, cookie: str) -> httpx.Response:
    return await client.get("/auth/session", headers=request_headers(cookie))


async def _credential(engine: AsyncEngine, org: uuid.UUID, user: uuid.UUID) -> tuple[int, object]:
    rows = await in_tenant(
        engine,
        org,
        "SELECT failed_attempts, locked_until FROM user_credentials"
        " WHERE org_id = :org AND user_id = :user",
        {"user": user},
    )
    return rows[0][0], rows[0][1]


async def _session_exists(engine: AsyncEngine, org: uuid.UUID, cookie: str) -> bool:
    rows = await in_tenant(
        engine,
        org,
        "SELECT 1 FROM admin_sessions WHERE org_id = :org AND token_hash = :hash",
        {"hash": hash_secret(_secret(cookie))},
    )
    return bool(rows)


async def _add_user(engine: AsyncEngine, org: OrgRows, email: str) -> uuid.UUID:
    """A second user in ``org`` with ``email``, member of the fixture Workspace."""
    user_id = uuid.uuid4()
    params = {"user": user_id, "email": email, "ws": org.workspace_id}
    for sql in (
        "INSERT INTO users (id, org_id, email, display_name) VALUES (:user, :org, :email, 'Twin')",
        "INSERT INTO memberships (org_id, user_id) VALUES (:org, :user)",
        "INSERT INTO workspace_memberships (org_id, workspace_id, user_id, role)"
        " VALUES (:org, :ws, :user, 'member')",
    ):
        await in_tenant(engine, org.org_id, sql, params)
    return user_id


async def test_sign_in_sets_session_and_returns_default_workspace(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)

    response = await sign_in(client, f"  {a.email.upper()} ", PASSWORD)

    assert response.status_code == 200
    assert response.json() == {"default_workspace_id": str(a.workspace_id)}
    assert response.headers["cache-control"] == "no-store"
    cookie = session_cookie(response)
    assert cookie.startswith(f"{a.org_id}.")
    assert await _session_exists(app_engine, a.org_id, cookie)
    who = await _who(client, cookie)
    assert who.status_code == 200
    assert who.json()["user"]["id"] == str(a.user_id)
    assert await audit_count(app_engine, a.org_id, USER_SIGNED_IN, user_actor(a.user_id), a.user_id)
    assert await _credential(app_engine, a.org_id, a.user_id) == (0, None)


async def test_sign_in_without_any_workspace_returns_null_default(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    await in_tenant(
        app_engine, a.org_id, "DELETE FROM workspace_memberships WHERE org_id = :org", {}
    )

    response = await sign_in(client, a.email, PASSWORD)

    assert response.status_code == 200
    assert response.json() == {"default_workspace_id": None}


async def test_cookie_flags(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)

    cookies = set_cookies(await sign_in(client, a.email, PASSWORD))

    _, flags = cookies[SESSION_COOKIE]
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= flags
    assert not any(flag.startswith(("max-age", "expires", "domain")) for flag in flags)
    csrf, csrf_flags = cookies[CSRF_COOKIE]
    assert csrf and csrf != CSRF_TOKEN
    assert "httponly" not in csrf_flags


async def test_rejections_are_identical(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    await give_password(app_engine, a.org_id, a.user_id)
    await in_tenant(app_engine, b.org_id, "DELETE FROM user_credentials WHERE org_id = :org", {})

    answers = [
        await sign_in(client, a.email, WRONG),
        await sign_in(client, f"{uuid.uuid4()}@example.invalid", PASSWORD),
        await sign_in(client, b.email, PASSWORD),  # no credential
    ]
    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE user_credentials SET locked_until = now() + interval '15 minutes'"
        " WHERE org_id = :org",
        {},
    )
    answers += [await sign_in(client, a.email, WRONG), await sign_in(client, a.email, PASSWORD)]

    for answer in answers:
        assert answer.status_code == 401
        assert answer.json() == {"detail": "invalid_credentials"}
        assert "set-cookie" not in answer.headers
    shapes = {(r.status_code, r.content, tuple(sorted(r.headers.keys()))) for r in answers}
    assert len(shapes) == 1


async def test_one_dummy_verify_only_when_nothing_was_hashed(
    client: httpx.AsyncClient,
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = two_orgs.a, two_orgs.b
    await give_password(app_engine, a.org_id, a.user_id)
    await in_tenant(app_engine, b.org_id, "DELETE FROM user_credentials WHERE org_id = :org", {})
    calls: list[None] = []

    async def counting_dummy() -> None:
        calls.append(None)

    monkeypatch.setattr(sign_in_flow, "dummy_verify", counting_dummy)

    async def dummies(email: str, password: str) -> int:
        calls.clear()
        assert (await sign_in(client, email, password)).status_code in (200, 401)
        return len(calls)

    assert await dummies(a.email, WRONG) == 0
    assert await dummies(a.email, PASSWORD) == 0
    assert await dummies(f"{uuid.uuid4()}@example.invalid", PASSWORD) == 1
    assert await dummies(b.email, PASSWORD) == 1  # no credential
    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE user_credentials SET locked_until = now() + interval '15 minutes'"
        " WHERE org_id = :org",
        {},
    )
    assert await dummies(a.email, PASSWORD) == 1  # locked


async def test_sixth_attempt_after_lockout_rejected_even_with_right_password(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)

    for _ in range(5):
        assert (await sign_in(client, a.email, WRONG)).status_code == 401
    _, locked_until = await _credential(app_engine, a.org_id, a.user_id)
    sixth = await sign_in(client, a.email, PASSWORD)

    assert locked_until is not None
    assert sixth.status_code == 401
    assert sixth.json() == {"detail": "invalid_credentials"}
    assert await _credential(app_engine, a.org_id, a.user_id) == (0, locked_until)
    locked_out = await audit_count(app_engine, a.org_id, USER_LOCKED_OUT, SYSTEM_ACTOR, a.user_id)
    assert locked_out == 1
    assert not await audit_count(
        app_engine, a.org_id, USER_SIGNED_IN, user_actor(a.user_id), a.user_id
    )

    await in_tenant(
        app_engine,
        a.org_id,
        "UPDATE user_credentials SET locked_until = now() - interval '1 second'"
        " WHERE org_id = :org",
        {},
    )
    assert (await sign_in(client, a.email, PASSWORD)).status_code == 200


@pytest.fixture
async def wide_engine() -> AsyncIterator[AsyncEngine]:
    """An application engine with enough connections for parallel sign-ins."""
    engine = create_async_engine(
        to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=PARALLEL, max_overflow=0
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The passwords the sign-in actually checked (the real verify still runs)."""
    calls: list[str] = []

    async def counting_verify(hashed: str, password: str) -> bool:
        calls.append(password)
        return await verify_password(hashed, password)

    monkeypatch.setattr(sign_in_flow, "verify_password", counting_verify)
    return calls


async def _four_failures(engine: AsyncEngine, org: OrgRows) -> None:
    await in_tenant(
        engine,
        org.org_id,
        "UPDATE user_credentials SET failed_attempts = 4, failure_window_started_at = now()"
        " WHERE org_id = :org",
    )


async def test_parallel_wrong_attempts_check_one_password_and_lock_once(
    wide_engine: AsyncEngine,
    directory: SignInDirectory,
    two_orgs: TwoOrgs,
    verify_calls: list[str],
) -> None:
    """AC3 under parallel requests: with 4 failures counted, only the attempt holding the 5th slot
    has its password checked; the others are refused unchecked, and the account locks once."""
    a = two_orgs.a
    await give_password(wide_engine, a.org_id, a.user_id)
    await _four_failures(wide_engine, a)

    async with auth_client(wide_engine, directory) as client:
        answers = await asyncio.gather(*(sign_in(client, a.email, WRONG) for _ in range(PARALLEL)))

    assert {(r.status_code, r.content) for r in answers} == {
        (401, b'{"detail":"invalid_credentials"}')
    }
    assert verify_calls == [WRONG]
    _, locked_until = await _credential(wide_engine, a.org_id, a.user_id)
    assert locked_until is not None
    assert await audit_count(wide_engine, a.org_id, USER_LOCKED_OUT, SYSTEM_ACTOR, a.user_id) == 1


async def test_right_password_racing_wrong_ones_never_signs_in_after_the_lock(
    wide_engine: AsyncEngine, directory: SignInDirectory, two_orgs: TwoOrgs
) -> None:
    """Whichever attempt wins the 5th slot, a session exists only if the account did not lock."""
    a = two_orgs.a
    await give_password(wide_engine, a.org_id, a.user_id)

    async with auth_client(wide_engine, directory) as client:
        for _ in range(3):
            await _four_failures(wide_engine, a)
            await in_tenant(wide_engine, a.org_id, "DELETE FROM audit_events WHERE org_id = :org")
            attempts = [PASSWORD] + [WRONG] * (PARALLEL - 1)
            answers = await asyncio.gather(*(sign_in(client, a.email, p) for p in attempts))

            signed_in = answers[0].status_code == 200
            locked_out = await audit_count(
                wide_engine, a.org_id, USER_LOCKED_OUT, SYSTEM_ACTOR, a.user_id
            )
            sessions = await audit_count(
                wide_engine, a.org_id, USER_SIGNED_IN, user_actor(a.user_id), a.user_id
            )
            assert all(r.status_code == 401 for r in answers[1:])
            assert (locked_out, sessions) == ((0, 1) if signed_in else (1, 0))
            _, locked_until = await _credential(wide_engine, a.org_id, a.user_id)
            assert (locked_until is None) is signed_in
            await in_tenant(
                wide_engine,
                a.org_id,
                "UPDATE user_credentials SET locked_until = NULL WHERE org_id = :org",
            )


async def test_right_password_counted_before_the_locking_attempt_does_not_sign_in(
    wide_engine: AsyncEngine,
    directory: SignInDirectory,
    two_orgs: TwoOrgs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministic race: the right password takes the 4th slot and is still being checked when
    a wrong one takes the 5th and locks. The right one must not sign in afterwards."""
    a = two_orgs.a
    await give_password(wide_engine, a.org_id, a.user_id)
    await in_tenant(
        wide_engine,
        a.org_id,
        "UPDATE user_credentials SET failed_attempts = 3, failure_window_started_at = now()"
        " WHERE org_id = :org",
    )
    checking, release = asyncio.Event(), asyncio.Event()

    async def gated_verify(hashed: str, password: str) -> bool:
        if password == PASSWORD:
            checking.set()
            await release.wait()
        return await verify_password(hashed, password)

    monkeypatch.setattr(sign_in_flow, "verify_password", gated_verify)

    async with auth_client(wide_engine, directory) as client:
        right = asyncio.create_task(sign_in(client, a.email, PASSWORD))
        await checking.wait()
        wrong = await sign_in(client, a.email, WRONG)
        release.set()
        right_answer = await right

    assert wrong.status_code == 401
    assert right_answer.status_code == 401
    assert right_answer.json() == {"detail": "invalid_credentials"}
    assert "set-cookie" not in right_answer.headers
    assert await audit_count(wide_engine, a.org_id, USER_LOCKED_OUT, SYSTEM_ACTOR, a.user_id) == 1
    assert not await audit_count(
        wide_engine, a.org_id, USER_SIGNED_IN, user_actor(a.user_id), a.user_id
    )


async def test_right_password_on_the_fifth_attempt_signs_in(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    for _ in range(4):
        assert (await sign_in(client, a.email, WRONG)).status_code == 401

    fifth = await sign_in(client, a.email, PASSWORD)

    assert fifth.status_code == 200
    assert await _credential(app_engine, a.org_id, a.user_id) == (0, None)
    assert not await audit_count(app_engine, a.org_id, USER_LOCKED_OUT, SYSTEM_ACTOR, a.user_id)


async def test_a_match_in_another_organization_refunds_the_locking_reservation(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    """R19: the first candidate's reservation would have locked it, but the second matched, so
    the first is restored exactly (4 failures, its window, no lock, no audit)."""
    a, b = two_orgs.a, two_orgs.b
    twin = await _add_user(app_engine, b, a.email)
    first, second = sorted([(a.org_id, a.user_id), (b.org_id, twin)])
    await give_password(app_engine, *first, password=WRONG)
    await give_password(app_engine, *second, password=PASSWORD)
    await in_tenant(
        app_engine,
        first[0],
        "UPDATE user_credentials SET failed_attempts = 4,"
        " failure_window_started_at = now() - interval '1 minute' WHERE org_id = :org",
    )
    window_sql = (
        "SELECT failed_attempts, failure_window_started_at, locked_until FROM user_credentials"
        " WHERE org_id = :org AND user_id = :user"
    )
    before = await in_tenant(app_engine, first[0], window_sql, {"user": first[1]})

    response = await sign_in(client, a.email, PASSWORD)

    assert response.status_code == 200
    assert session_cookie(response).startswith(f"{second[0]}.")
    assert await in_tenant(app_engine, first[0], window_sql, {"user": first[1]}) == before
    assert not await audit_count(app_engine, first[0], USER_LOCKED_OUT, SYSTEM_ACTOR, first[1])


async def test_same_email_two_orgs_first_matching_org_wins_and_no_failure_counted(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    twin = await _add_user(app_engine, b, a.email)
    first, second = sorted([(a.org_id, a.user_id), (b.org_id, twin)])
    await give_password(app_engine, *first, password=PASSWORD)
    await give_password(app_engine, *second, password=PASSWORD)

    both_match = await sign_in(client, a.email, PASSWORD)

    assert both_match.status_code == 200
    assert session_cookie(both_match).startswith(f"{first[0]}.")

    await give_password(app_engine, *first, password=WRONG)
    second_only = await sign_in(client, a.email, PASSWORD)

    assert second_only.status_code == 200
    assert session_cookie(second_only).startswith(f"{second[0]}.")
    assert (await _who(client, session_cookie(second_only))).json()["user"]["id"] == str(second[1])
    assert await _credential(app_engine, *first) == (0, None)
    assert await _credential(app_engine, *second) == (0, None)


async def test_a_failed_attempt_counts_on_every_unlocked_candidate(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    twin = await _add_user(app_engine, b, a.email)
    await give_password(app_engine, a.org_id, a.user_id)
    await give_password(app_engine, b.org_id, twin)

    response = await sign_in(client, a.email, WRONG)

    assert response.status_code == 401
    assert (await _credential(app_engine, a.org_id, a.user_id))[0] == 1
    assert (await _credential(app_engine, b.org_id, twin))[0] == 1


async def test_sign_in_rotates_previous_session(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    old = session_cookie(await sign_in(client, a.email, PASSWORD))

    again = await sign_in(client, a.email, PASSWORD, session=old)

    new = session_cookie(again)
    assert new != old
    assert not await _session_exists(app_engine, a.org_id, old)
    assert (await _who(client, old)).status_code == 401
    assert (await _who(client, new)).status_code == 200


async def test_sign_out_destroys_session(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    cookie = session_cookie(await sign_in(client, a.email, PASSWORD))

    response = await client.post("/auth/sign-out", headers=request_headers(cookie))

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    cookies = set_cookies(response)
    value, flags = cookies[SESSION_COOKIE]
    assert value in ("", '""')
    assert "max-age=0" in flags
    assert cookies[CSRF_COOKIE][0] not in ("", CSRF_TOKEN)
    assert not await _session_exists(app_engine, a.org_id, cookie)
    replay = await _who(client, cookie)
    assert replay.status_code == 401
    assert replay.json() == {"detail": "unauthenticated"}
    actor = user_actor(a.user_id)
    assert await audit_count(app_engine, a.org_id, USER_SIGNED_OUT, actor, a.user_id) == 1

    again = await client.post("/auth/sign-out", headers=request_headers(cookie))

    assert again.status_code == 204
    assert await audit_count(app_engine, a.org_id, USER_SIGNED_OUT, actor, a.user_id) == 1


async def test_sign_out_without_session_is_204(client: httpx.AsyncClient) -> None:
    for headers in (request_headers(), request_headers("not-a-cookie")):
        response = await client.post("/auth/sign-out", headers=headers)

        assert response.status_code == 204
        assert "max-age=0" in set_cookies(response)[SESSION_COOKIE][1]


async def test_sign_out_needs_csrf(client: httpx.AsyncClient) -> None:
    response = await client.post("/auth/sign-out", headers=request_headers(csrf=False))

    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


async def test_sign_in_rate_limited_returns_429(
    app_engine: AsyncEngine, directory: SignInDirectory, two_orgs: TwoOrgs
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    async with auth_client(app_engine, directory, RateLimiter(3)) as client:
        for _ in range(3):
            assert (await sign_in(client, a.email, WRONG)).status_code == 401

        limited = await sign_in(client, a.email, PASSWORD)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert limited.headers["cache-control"] == "no-store"
    assert "set-cookie" not in limited.headers
    assert (await _credential(app_engine, a.org_id, a.user_id))[0] == 3


async def test_forged_cookie_other_org_is_401(
    client: httpx.AsyncClient, app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    a, b = two_orgs.a, two_orgs.b
    await give_password(app_engine, a.org_id, a.user_id)
    cookie = session_cookie(await sign_in(client, a.email, PASSWORD))

    forged = await _who(client, f"{b.org_id}.{_secret(cookie)}")

    assert forged.status_code == 401
    assert forged.json() == {"detail": "unauthenticated"}
    assert str(b.org_id) not in forged.text
    assert (await _who(client, cookie)).status_code == 200


async def test_sign_in_rejects_missing_or_non_string_fields(client: httpx.AsyncClient) -> None:
    for body in ({"email": "x@example.invalid"}, {"email": 1, "password": PASSWORD}, None):
        response = await client.post("/auth/sign-in", json=body, headers=request_headers())

        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_request"}
        assert PASSWORD not in response.text


async def test_auth_routes_never_log_or_echo_secrets(
    client: httpx.AsyncClient,
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a = two_orgs.a
    await give_password(app_engine, a.org_id, a.user_id)
    unknown = f"{uuid.uuid4()}@example.invalid"
    caplog.set_level(logging.DEBUG)
    async with app_engine.connect() as conn, tenant_transaction(conn, a.org_id):
        set_secret = await issue_token(conn, a.org_id, a.user_id)
    set_token = format_token(a.org_id, set_secret)

    signed_in = await sign_in(client, a.email, PASSWORD)
    cookie = session_cookie(signed_in)
    others = [
        await sign_in(client, a.email, WRONG),
        await sign_in(client, unknown, PASSWORD),
        await client.post(
            "/auth/sign-in", json={"email": a.email, "password": 7}, headers=request_headers()
        ),
        await client.post(
            "/auth/sign-in",
            json={"email": a.email, "password": PASSWORD},
            headers={"Cookie": f"{CSRF_COOKIE}=x"},
        ),
        await _who(client, f"{a.org_id}.{'x' * 43}"),
        sign_out := await client.post("/auth/sign-out", headers=request_headers(cookie)),
        await client.post(
            "/auth/forgot-password", json={"email": unknown}, headers=request_headers()
        ),
        await client.post("/auth/forgot-password", json={"email": 7}, headers=request_headers()),
        await client.post(
            "/auth/set-password",
            json={"token": set_token, "password": "short"},
            headers=request_headers(),
        ),
        await client.post(
            "/auth/set-password",
            json={"token": f"{a.org_id}.{'y' * 43}", "password": NEW_SECRET_PASSWORD},
            headers=request_headers(),
        ),
        await client.post(
            "/auth/set-password",
            json={"token": set_token, "password": NEW_SECRET_PASSWORD},
            headers=request_headers(),
        ),
    ]
    fresh = await sign_in(client, a.email, NEW_SECRET_PASSWORD)
    session_info = await _who(client, session_cookie(fresh))

    secret = _secret(cookie)
    printed = capsys.readouterr()
    # The test client logs its own request lines (URL paths); only the app's logs count.
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")
    written = "\n".join([app_logs, printed.out, printed.err])
    for value in (PASSWORD, WRONG, NEW_SECRET_PASSWORD, a.email, unknown, secret, set_secret):
        assert value not in written
    assert "password" not in written.lower()
    for response in [signed_in, *others, session_info]:
        headers = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
        for value in (PASSWORD, WRONG, NEW_SECRET_PASSWORD, unknown, set_secret):
            assert value not in response.text
            assert value not in headers
        if response is not session_info:  # the session info shows the caller's own email
            assert a.email not in response.text
        assert a.email not in headers
        assert secret not in response.text
    assert secret not in "\n".join(f"{k}: {v}" for k, v in sign_out.headers.items())
