from datetime import UTC, datetime, timedelta

from ei_ai.auth.lockout import LOCK, MAX_FAILURES, WINDOW, FailureState, next_failure_state

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
FRESH = FailureState(0, None, None)


def test_constants() -> None:
    assert (WINDOW, LOCK, MAX_FAILURES) == (timedelta(minutes=15), timedelta(minutes=15), 5)


def test_lockout_rule_first_failure_opens_the_window() -> None:
    state, locked = next_failure_state(FRESH, NOW)

    assert state == FailureState(1, NOW, None)
    assert locked is False


def test_lockout_rule_fifth_within_window_locks() -> None:
    state = FailureState(4, NOW, None)

    new, locked = next_failure_state(state, NOW + timedelta(minutes=14, seconds=59))

    assert locked is True
    assert new.locked_until == NOW + timedelta(minutes=14, seconds=59) + LOCK
    assert new.failed_attempts == 0
    assert new.window_started_at is None


def test_lockout_rule_fifth_after_window_restarts_at_one() -> None:
    state = FailureState(4, NOW, None)
    later = NOW + timedelta(minutes=15, seconds=1)

    new, locked = next_failure_state(state, later)

    assert new == FailureState(1, later, None)
    assert locked is False


def test_lockout_rule_counts_up_inside_window() -> None:
    state = FailureState(2, NOW, None)

    new, locked = next_failure_state(state, NOW + timedelta(minutes=1))

    assert new == FailureState(3, NOW, None)
    assert locked is False


def test_lockout_rule_lock_resets_counters() -> None:
    state = FailureState(4, NOW, None)

    new, _ = next_failure_state(state, NOW + timedelta(minutes=1))
    again, locked = next_failure_state(new, NOW + timedelta(minutes=2))

    assert again.failed_attempts == 1
    assert locked is False
