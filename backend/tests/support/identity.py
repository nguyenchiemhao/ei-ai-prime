"""Test-only identity verifier. Never imported by ``src`` and never wired in production."""

from fastapi import Request

from ei_ai.auth.principal import InvalidCredentials, Principal


class StaticBearerVerifier:
    """``Authorization: Bearer <token>`` looked up in a fixed table."""

    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    async def verify(self, request: Request) -> Principal | None:
        header = request.headers.get("authorization")
        if header is None:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        principal = self._principals.get(token)
        if principal is None:
            raise InvalidCredentials
        return principal
