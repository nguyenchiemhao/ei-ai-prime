"""FastAPI dependency that turns a request into a verified Principal (or a 401)."""

import logging

from fastapi import HTTPException, Request

from ei_ai.auth.principal import IdentityVerifier, InvalidCredentials, Principal

logger = logging.getLogger("ei_ai.auth")

UNAUTHENTICATED = "unauthenticated"


def _unauthenticated() -> HTTPException:
    # An error code (frontends translate it), never text, ids or SQL.
    return HTTPException(
        status_code=401, detail=UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_principal(request: Request) -> Principal:
    """Run the configured verifiers in order; the first Principal wins. No verifier, no match or
    any failure means 401 (fail closed). Nothing about the credential is logged (D52)."""
    verifiers: tuple[IdentityVerifier, ...] = request.app.state.identity_verifiers
    for verifier in verifiers:
        try:
            principal = await verifier.verify(request)
        except InvalidCredentials:
            raise _unauthenticated() from None
        except Exception as error:
            # Class names only: messages can carry token fragments.
            logger.error(
                "identity_verifier_failed verifier=%s error=%s",
                type(verifier).__name__,
                type(error).__name__,
            )
            raise _unauthenticated() from None
        if principal is not None:
            return principal
    raise _unauthenticated()
