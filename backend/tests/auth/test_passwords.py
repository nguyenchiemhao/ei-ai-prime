import asyncio
import threading
import time
from collections.abc import Coroutine
from typing import Any

import pytest

from ei_ai.auth import passwords
from ei_ai.auth.passwords import (
    MAX_CONCURRENT_HASHES,
    MAX_LENGTH,
    MIN_LENGTH,
    check_policy,
    dummy_verify,
    hash_password,
    verify_password,
)


class _SlowHasher:
    """Stands in for the Argon2 hasher: records how many calls run at the same time."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.peak = 0
        self._running = 0
        self._lock = threading.Lock()

    def _work(self, name: str) -> None:
        with self._lock:
            self.calls.append(name)
            self._running += 1
            self.peak = max(self.peak, self._running)
        time.sleep(0.05)
        with self._lock:
            self._running -= 1

    def hash(self, _password: str) -> str:
        self._work("hash")
        return "$argon2id$fake"

    def verify(self, _hashed: str, _password: str) -> bool:
        self._work("verify")
        return True


@pytest.fixture
def slow_hasher(monkeypatch: pytest.MonkeyPatch) -> _SlowHasher:
    hasher = _SlowHasher()
    monkeypatch.setattr(passwords, "_hasher", hasher)
    return hasher


def test_policy_bounds() -> None:
    assert (MIN_LENGTH, MAX_LENGTH) == (12, 128)
    assert check_policy("a" * 11) == "password_too_short"
    assert check_policy("a" * 12) is None
    assert check_policy("a" * 128) is None
    assert check_policy("a" * 129) == "password_too_long"
    assert check_policy("\N{GRINNING FACE}" * 12) is None


async def test_hash_is_argon2id() -> None:
    hashed = await hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


async def test_verify_right_and_wrong() -> None:
    hashed = await hash_password("correct horse battery")

    assert await verify_password(hashed, "correct horse battery") is True
    assert await verify_password(hashed, "wrong horse battery") is False


async def test_verify_garbage_hash_is_false() -> None:
    assert await verify_password("not-a-hash", "whatever password") is False


async def test_dummy_verify_runs() -> None:
    await dummy_verify()


@pytest.mark.parametrize("password", ["a" * 12])
async def test_hashes_are_salted(password: str) -> None:
    assert await hash_password(password) != await hash_password(password)


async def test_at_most_four_hashes_run_at_once(slow_hasher: _SlowHasher) -> None:
    """Each Argon2 call takes about 19 MiB: hash, verify and dummy verify share one small cap, so
    a burst of requests cannot exhaust the API's 512 MB (the default thread pool allows 40)."""
    work: list[Coroutine[Any, Any, object]] = [hash_password("p" * 12) for _ in range(5)]
    work += [verify_password("$argon2id$fake", "p" * 12) for _ in range(5)]
    work += [dummy_verify() for _ in range(5)]

    await asyncio.gather(*work)

    assert MAX_CONCURRENT_HASHES == 4
    assert slow_hasher.peak == MAX_CONCURRENT_HASHES
    assert len(slow_hasher.calls) == 15


async def test_dummy_verify_never_hashes(slow_hasher: _SlowHasher) -> None:
    """The dummy hash is computed at import: the first unknown-email answer is not slower."""
    await dummy_verify()

    assert slow_hasher.calls == ["verify"]
