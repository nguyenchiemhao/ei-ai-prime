"""The verified identity of a request and the interface that produces it.

No production verifier exists yet: the admin session (FND-05) and the Channel JWT (WGT-03) each add
one. Until then every tenant route fails closed with 401.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Request


@dataclass(frozen=True)
class Principal:
    """Who is calling and for which Organization, as proven by a verified token or session."""

    user_id: UUID
    org_id: UUID


class InvalidCredentials(Exception):
    """The request carries a credential of this verifier's kind, and it is not valid."""


class IdentityVerifier(Protocol):
    async def verify(self, request: Request) -> Principal | None:
        """The Principal for a valid credential; ``None`` when the request has no credential of
        this kind (the next verifier is tried); ``InvalidCredentials`` when it is invalid."""
        ...
