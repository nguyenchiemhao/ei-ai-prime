from ei_ai.auth.rate_limit import RateLimiter


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limit_allows_then_gives_retry_after() -> None:
    clock = _Clock()
    limiter = RateLimiter(limit=3, window_seconds=60, clock=clock)

    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]
    clock.now += 10
    assert limiter.hit("a") == 50


def test_rate_limit_window_slides() -> None:
    clock = _Clock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("a") is None
    clock.now += 30
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 30
    clock.now += 31
    assert limiter.hit("a") is None


def test_rate_limit_keys_are_independent() -> None:
    limiter = RateLimiter(limit=1, clock=_Clock())

    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None
    assert limiter.hit("b") is None


def test_rate_limit_drops_expired_keys() -> None:
    clock = _Clock()
    limiter = RateLimiter(limit=1, window_seconds=60, clock=clock)
    for i in range(100):
        limiter.hit(f"key-{i}")
    clock.now += 61

    limiter.hit("fresh")

    assert list(limiter._hits) == ["fresh"]  # noqa: SLF001
