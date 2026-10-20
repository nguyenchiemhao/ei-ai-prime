"""Password policy and Argon2id hashing (OWASP minimum parameters).

Hashing is CPU-bound, so it runs in a worker thread and never blocks the event loop. Every hash
and verify (the dummy one included) shares one small capacity limiter: each call allocates about
19 MiB, and the default thread pool would let 40 run at once, beyond the API's 512 MB. The policy
counts code points, not bytes.
"""

from typing import Literal

from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 12
MAX_LENGTH = 128
MAX_CONCURRENT_HASHES = 4

_hasher = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)
_limiter = CapacityLimiter(MAX_CONCURRENT_HASHES)
# Computed once at import, so the first unknown-email answer costs one verify like every other.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def check_policy(password: str) -> Literal["password_too_short", "password_too_long"] | None:
    """The error code of the first violated rule, or None when the password is acceptable."""
    if len(password) < MIN_LENGTH:
        return "password_too_short"
    if len(password) > MAX_LENGTH:
        return "password_too_long"
    return None


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hasher.hash, password, limiter=_limiter)


def _verify(hashed: str, password: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(hash: str, password: str) -> bool:  # noqa: A002
    """True when the password matches; a wrong password or a malformed hash gives False."""
    return await to_thread.run_sync(_verify, hash, password, limiter=_limiter)


async def dummy_verify() -> None:
    """Spend one verification's time, so an unknown account answers as slowly as a known one."""
    await verify_password(_DUMMY_HASH, "not-the-dummy-password")
