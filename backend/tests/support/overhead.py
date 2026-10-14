"""The RLS overhead rule of FND-01 (owner decision 2026-10-14), as a pure function.

At most 1 ms added per query, or at most 10 % for queries that take 10 ms or more without RLS.
"""

MAX_ADDED_MS = 1.0
MAX_RELATIVE_PERCENT = 10.0
RELATIVE_FROM_MS = 10.0


def overhead_percent(baseline_ms: float, with_rls_ms: float) -> float:
    return (with_rls_ms - baseline_ms) / baseline_ms * 100


def within_rls_budget(baseline_ms: float, with_rls_ms: float) -> bool:
    """True when the added time is within 1 ms, or, for a baseline of 10 ms or more, within 10 %."""
    if with_rls_ms - baseline_ms <= MAX_ADDED_MS:
        return True
    return (
        baseline_ms >= RELATIVE_FROM_MS
        and overhead_percent(baseline_ms, with_rls_ms) <= MAX_RELATIVE_PERCENT
    )
