"""The pure lockout rule: 5 failures within 15 minutes lock the account for 15 minutes."""

from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=15)
LOCK = timedelta(minutes=15)
MAX_FAILURES = 5


@dataclass(frozen=True)
class FailureState:
    failed_attempts: int
    window_started_at: datetime | None
    locked_until: datetime | None


def next_failure_state(state: FailureState, now: datetime) -> tuple[FailureState, bool]:
    """The state after one more failed sign-in, and whether that failure just locked the account.

    A failure outside the current window opens a new window at 1. The failure that reaches
    ``MAX_FAILURES`` sets ``locked_until`` and resets the counters.
    """
    started = state.window_started_at
    if started is None or now - started > WINDOW:
        attempts, started = 1, now
    else:
        attempts = state.failed_attempts + 1
    if attempts >= MAX_FAILURES:
        return FailureState(0, None, now + LOCK), True
    return FailureState(attempts, started, state.locked_until), False
