"""In-process sliding-window rate limiter (per API replica)."""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = clock() + window_seconds

    def _prune(self, hits: deque[float], now: float) -> None:
        while hits and now - hits[0] >= self._window:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        """Drop every key whose hits have all expired, so varying keys cannot grow memory."""
        for key in list(self._hits):
            hits = self._hits[key]
            self._prune(hits, now)
            if not hits:
                del self._hits[key]
        self._next_sweep = now + self._window

    def hit(self, key: str) -> float | None:
        """Count one attempt. None = allowed; otherwise the seconds until a slot frees up."""
        now = self._clock()
        if now >= self._next_sweep:
            self._sweep(now)
        hits = self._hits.get(key)
        if hits is not None:
            self._prune(hits, now)
            if len(hits) >= self._limit:
                return hits[0] + self._window - now
        else:
            hits = self._hits[key] = deque()
        hits.append(now)
        return None
