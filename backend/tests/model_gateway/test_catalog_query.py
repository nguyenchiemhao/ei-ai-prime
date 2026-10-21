"""R1-3: the catalog read keeps the explicit Organization filter (layer 1) on top of RLS
(layer 2, D46). RLS alone would still isolate, so only this check notices a dropped filter."""

import re

from ei_ai.model_gateway.catalog import _RESOLVE


def _where(sql: str) -> str:
    return " ".join(sql.split()).partition(" WHERE ")[2]


def test_resolve_filters_both_tables_by_the_callers_organization() -> None:
    where = _where(str(_RESOLVE))

    conditions = [c.strip() for c in re.split(r"\bAND\b", where)]
    assert "m.org_id = :org" in conditions
    assert "o.id = :org" in conditions
    assert " OR " not in f" {where} "
