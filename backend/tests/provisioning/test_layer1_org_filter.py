"""Layer 1 of D46 in the platform-plane SQL: every statement names the Organization itself.

Row-level security (layer 2) hides a missing ``org_id`` filter from every behavioural test, so
this static check reads the SQL literals passed to ``text(...)`` and requires the explicit filter.
"""

import ast
import re
from pathlib import Path

from support.tenants import DELETE_ORDER

SRC = Path(__file__).resolve().parents[2] / "src" / "ei_ai"
MODULES = (
    "provisioning/rows.py",
    "provisioning/service.py",
    "auth/set_password.py",
    "audit/events.py",
)
_TABLE = re.compile(r"\b(?:FROM|UPDATE|INTO|JOIN)\s+([a-z_]+)", re.IGNORECASE)


def sql_literals(source: str) -> list[str]:
    """The string literals passed as the first argument of ``text(...)`` calls."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "text"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append(node.args[0].value)
    return found


def missing_org_filter(sql: str) -> bool:
    """True when the statement touches a tenant table without naming the Organization."""
    tables = {table.lower() for table in _TABLE.findall(sql)} & set(DELETE_ORDER)
    if not tables:
        return False
    if sql.lstrip().upper().startswith("INSERT"):
        return ":org" not in sql
    keys = ["id = :org"] if tables == {"organizations"} else ["org_id = :org"]
    return not any(key in sql for key in keys)


def unfiltered_statements(sources: dict[str, str]) -> list[str]:
    """``module: statement`` for every tenant-table statement without the explicit filter."""
    return [
        f"{module}: {sql}"
        for module, source in sources.items()
        for sql in sql_literals(source)
        if missing_org_filter(sql)
    ]


def test_every_tenant_statement_carries_the_org_filter() -> None:
    sources = {module: (SRC / module).read_text(encoding="utf-8") for module in MODULES}

    assert all(sql_literals(source) for source in sources.values())
    assert unfiltered_statements(sources) == []


def test_the_check_reports_a_statement_without_the_filter() -> None:
    sources = {
        "bad.py": (
            'text("SELECT 1 FROM workspaces WHERE id = :ws")\n'
            'text("UPDATE set_password_tokens SET used_at = now() WHERE token_hash = :hash")\n'
            'text("SELECT id FROM users u JOIN memberships m ON m.user_id = u.id")\n'
            'text("INSERT INTO users (email) VALUES (:email)")\n'
        ),
        "good.py": (
            'text("SELECT 1 FROM organizations WHERE id = :org")\n'
            'text("DELETE FROM set_password_tokens WHERE org_id = :org AND user_id = :u")\n'
            'text("INSERT INTO workspaces (org_id, name) VALUES (:org, :name)")\n'
            'text("SELECT uuid_generate_v7()")\n'
        ),
    }

    assert [line.split(":")[0] for line in unfiltered_statements(sources)] == ["bad.py"] * 4
