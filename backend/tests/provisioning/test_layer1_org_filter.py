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
    "crypto/key_rows.py",
    "provisioning/service.py",
    "members/rows.py",
    "knowledge/rows.py",
    "knowledge/folder_rows.py",
    "rbac/access.py",
    "auth/set_password.py",
    "audit/events.py",
)
# A table reference is FROM/UPDATE/INTO/JOIN <table> [AS] [<alias>]; some words after it are SQL.
_REFERENCE = re.compile(
    r"\b(?:FROM|UPDATE|INTO|JOIN)\s+([a-z_]+)(?:\s+(?:AS\s+)?([a-z_]+))?", re.IGNORECASE
)
_NOT_AN_ALIAS = frozenset(
    "where set on left right inner outer join cross values order group limit for using as select"
    " returning and or".split()
)


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
    """True when a tenant table of the statement is not itself restricted to the Organization.

    Every reference to a tenant table needs its own ``<alias>.org_id = :org`` (``org_id = :org``
    for a table without alias; ``id = :org`` for ``organizations``). A filter on a joined table
    does not count for the other tables: an equality such as ``m.org_id = w.org_id`` is no filter.
    """
    references = [
        (
            table.lower(),
            (alias or table).lower()
            if (alias or "").lower() not in _NOT_AN_ALIAS
            else table.lower(),
        )
        for table, alias in _REFERENCE.findall(sql)
    ]
    tenant = [(table, alias) for table, alias in references if table in DELETE_ORDER]
    if not tenant:
        return False
    if sql.lstrip().upper().startswith("INSERT"):
        return ":org" not in sql
    for table, alias in tenant:
        column = "id" if table == "organizations" else "org_id"
        qualified = rf"\b{re.escape(alias)}\.{column}\s*=\s*:org\b"
        bare = rf"(?<![\w.]){column}\s*=\s*:org\b"
        if not re.search(qualified, sql) and not (alias == table and re.search(bare, sql)):
            return True
    return False


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
            # one table filtered, the joined one only equated to it (the EA-23 mutation B16)
            'text("SELECT w.id FROM workspaces w JOIN memberships m ON m.org_id = w.org_id'
            ' AND m.org_id = :org WHERE w.id = :ws")\n'
            # the filter sits on a subselect alias, not on the outer table
            'text("SELECT 1 FROM users u WHERE EXISTS (SELECT 1 FROM admin_sessions s'
            ' WHERE s.org_id = :org AND s.user_id = u.id)")\n'
        ),
        "good.py": (
            'text("SELECT 1 FROM organizations WHERE id = :org")\n'
            'text("DELETE FROM set_password_tokens WHERE org_id = :org AND user_id = :u")\n'
            'text("INSERT INTO workspaces (org_id, name) VALUES (:org, :name)")\n'
            'text("SELECT uuid_generate_v7()")\n'
            'text("SELECT w.id FROM workspaces w JOIN memberships m ON m.org_id = w.org_id'
            " LEFT JOIN workspace_memberships wm ON wm.org_id = w.org_id AND wm.org_id = :org"
            ' WHERE w.org_id = :org AND m.org_id = :org")\n'
        ),
    }

    assert [line.split(":")[0] for line in unfiltered_statements(sources)] == ["bad.py"] * 6
