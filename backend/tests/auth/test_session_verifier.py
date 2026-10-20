"""SessionCookieVerifier: no cookie is "not my kind", a cookie that is not a live session is 401.

The database side (live, idle-expired, other-Organization sessions) is covered by
``tests/integration/auth/test_sessions.py`` and ``tests/integration/api/test_session_info.py``.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from starlette.requests import Request

from ei_ai.auth import session_verifier
from ei_ai.auth.principal import InvalidCredentials, Principal
from ei_ai.auth.session_verifier import SessionCookieVerifier

ENGINE: Any = object()
PRINCIPAL = Principal(user_id=uuid.uuid4(), org_id=uuid.uuid4())
IDLE = timedelta(minutes=7)


def _request(cookie: str | None) -> Request:
    headers = [] if cookie is None else [(b"cookie", f"ei_session={cookie}".encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class _FakeVerify:
    def __init__(self, result: Principal | None) -> None:
        self.result = result
        self.calls: list[tuple[object, str, timedelta]] = []

    async def __call__(self, engine: object, cookie: str, idle: timedelta) -> Principal | None:
        self.calls.append((engine, cookie, idle))
        return self.result


async def test_no_cookie_is_none_and_never_touches_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeVerify(PRINCIPAL)
    monkeypatch.setattr(session_verifier, "verify_session", fake)

    assert await SessionCookieVerifier(lambda: ENGINE, IDLE).verify(_request(None)) is None
    assert fake.calls == []


async def test_live_session_gives_its_principal_with_the_configured_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeVerify(PRINCIPAL)
    monkeypatch.setattr(session_verifier, "verify_session", fake)

    principal = await SessionCookieVerifier(lambda: ENGINE, IDLE).verify(_request("org.secret"))

    assert principal == PRINCIPAL
    assert fake.calls == [(ENGINE, "org.secret", IDLE)]


async def test_cookie_without_live_session_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_verifier, "verify_session", _FakeVerify(None))

    with pytest.raises(InvalidCredentials):
        await SessionCookieVerifier(lambda: ENGINE, IDLE).verify(_request("org.secret"))


@pytest.mark.parametrize("cookie", ["", "garbage", f"{uuid.uuid4()}.short"])
async def test_malformed_cookie_is_invalid_without_a_database(cookie: str) -> None:
    with pytest.raises(InvalidCredentials):
        await SessionCookieVerifier(lambda: ENGINE, IDLE).verify(_request(cookie))


def test_idle_timeout_is_exposed() -> None:
    assert SessionCookieVerifier(lambda: ENGINE, IDLE).idle == IDLE
