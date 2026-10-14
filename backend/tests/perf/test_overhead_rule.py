"""The pure rule behind the RLS benchmark (no database, runs with the unit tests)."""

import pytest

from support.overhead import overhead_percent, within_rls_budget


@pytest.mark.parametrize(
    ("baseline", "with_rls", "ok"),
    [
        (0.009, 0.020, True),  # tiny query: well under 1 ms added
        (2.27, 3.27, True),  # exactly 1 ms added
        (2.27, 3.28, False),  # just over 1 ms, baseline below 10 ms: relative share is not used
        (9.9, 11.0, False),  # 1.1 ms added, baseline below 10 ms
        (10.0, 11.0, True),  # 10 ms baseline, 10 % (and 1 ms)
        (10.0, 11.01, False),  # 10 ms baseline, over 10 % and over 1 ms
        (50.0, 55.0, True),  # 5 ms added but 10 % of 50 ms
        (50.0, 55.1, False),
        (20.0, 20.5, True),
    ],
)
def test_rls_budget_rule(baseline: float, with_rls: float, ok: bool) -> None:
    assert within_rls_budget(baseline, with_rls) is ok


def test_overhead_percent() -> None:
    assert overhead_percent(2.0, 2.5) == pytest.approx(25.0)
