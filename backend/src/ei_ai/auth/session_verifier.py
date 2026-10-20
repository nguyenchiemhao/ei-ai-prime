"""The admin session cookie as an identity verifier (D32): the production Principal source.

The Organization of the Principal is the cookie's Organization, proven by the secret matching a
live session inside that Organization only (``auth.sessions.verify_session``). The cookie is
never logged (D52).
"""

from collections.abc import Callable
from datetime import timedelta

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.principal import InvalidCredentials, Principal
from ei_ai.auth.sessions import SESSION_COOKIE, verify_session


class SessionCookieVerifier:
    """``ei_session`` absent: not this verifier's kind (``None``). Present but not a live
    session (malformed, unknown, signed out, idle-expired, another Organization's id):
    ``InvalidCredentials``.
    """

    def __init__(self, engine_getter: Callable[[], AsyncEngine], idle: timedelta) -> None:
        # A getter: the app creates its engine at startup, after the verifier is built.
        self._engine_getter = engine_getter
        self._idle = idle

    @property
    def idle(self) -> timedelta:
        """How long a session stays valid without a request."""
        return self._idle

    async def verify(self, request: Request) -> Principal | None:
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie is None:
            return None
        principal = await verify_session(self._engine_getter(), cookie, self._idle)
        if principal is None:
            raise InvalidCredentials
        return principal
