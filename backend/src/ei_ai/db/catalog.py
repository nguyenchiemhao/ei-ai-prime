"""A read-only snapshot of the schema facts the schema guard judges (tables, RLS, grants).

The snapshot is plain data, so the rules in ``schema_guard`` are unit-tested on synthetic snapshots
and run unchanged on the real catalog.
"""

from dataclasses import dataclass

import psycopg

Kind = str  # "table" | "partition" | "view" | "matview"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    not_null: bool


@dataclass(frozen=True)
class PolicyInfo:
    name: str
    command: str  # ALL, SELECT, INSERT, UPDATE, DELETE
    using: str | None
    with_check: str | None
    permissive: bool = True  # restrictive policies are AND-ed and can only narrow access
    roles: tuple[str, ...] = ("PUBLIC",)  # the TO clause, sorted; ("PUBLIC",) when there is none


@dataclass(frozen=True)
class ForeignKeyInfo:
    name: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True)
class Privilege:
    grantee: str  # a role name or "PUBLIC"
    privilege: str  # SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, ...


@dataclass(frozen=True)
class ColumnPrivilege:
    """A privilege granted on one column only (``GRANT SELECT (email) ON users TO ...``)."""

    column: str
    grantee: str  # a role name or "PUBLIC"
    privilege: str  # SELECT, INSERT, UPDATE, REFERENCES
    grantable: bool = False  # WITH GRANT OPTION


@dataclass(frozen=True)
class TableInfo:
    name: str
    kind: Kind
    owner: str
    rls_enabled: bool
    rls_forced: bool
    security_invoker: bool  # views only
    columns: tuple[ColumnInfo, ...] = ()
    policies: tuple[PolicyInfo, ...] = ()
    foreign_keys: tuple[ForeignKeyInfo, ...] = ()
    privileges: tuple[Privilege, ...] = ()
    column_privileges: tuple[ColumnPrivilege, ...] = ()

    def column(self, name: str) -> ColumnInfo | None:
        return next((column for column in self.columns if column.name == name), None)


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    owner: str
    security_definer: bool


@dataclass(frozen=True)
class CatalogSnapshot:
    tables: tuple[TableInfo, ...]
    functions: tuple[FunctionInfo, ...] = ()


# Objects that belong to an extension (for example pgvector) are not ours to judge.
_NOT_EXTENSION_MEMBER = (
    "NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = '{catalog}'::regclass"
    " AND d.objid = {oid} AND d.deptype = 'e')"
)

_RELATIONS = f"""
SELECT c.oid, c.relname,
       CASE WHEN c.relispartition THEN 'partition'
            WHEN c.relkind IN ('r', 'p') THEN 'table'
            WHEN c.relkind = 'v' THEN 'view'
            ELSE 'matview' END,
       pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity,
       COALESCE('security_invoker=true' = ANY (c.reloptions)
                OR 'security_invoker=on' = ANY (c.reloptions), false)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm')
  AND {_NOT_EXTENSION_MEMBER.format(catalog="pg_class", oid="c.oid")}
ORDER BY c.relname
"""

_COLUMNS = """
SELECT attrelid, attname, format_type(atttypid, atttypmod), attnotnull
FROM pg_attribute WHERE attrelid = ANY (%s) AND attnum > 0 AND NOT attisdropped
ORDER BY attrelid, attnum
"""

_POLICIES = """
SELECT c.oid, p.polname,
       CASE p.polcmd WHEN 'r' THEN 'SELECT' WHEN 'a' THEN 'INSERT' WHEN 'w' THEN 'UPDATE'
                     WHEN 'd' THEN 'DELETE' ELSE 'ALL' END,
       pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid), p.polpermissive,
       ARRAY(SELECT CASE WHEN r = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(r) END
             FROM unnest(p.polroles) r ORDER BY 1)
FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.oid = ANY (%s)
ORDER BY c.oid, p.polname
"""

_FOREIGN_KEYS = """
SELECT k.conrelid, k.conname,
       ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, o)
             JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n ORDER BY u.o),
       r.relname,
       ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(n, o)
             JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.n ORDER BY u.o)
FROM pg_constraint k JOIN pg_class r ON r.oid = k.confrelid
WHERE k.contype = 'f' AND k.conrelid = ANY (%s)
ORDER BY k.conrelid, k.conname
"""

_PRIVILEGES = """
SELECT c.oid, CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
       a.privilege_type
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.oid = ANY (%s) AND a.grantee <> c.relowner
ORDER BY c.oid, 2, a.privilege_type
"""

# Column ACLs are separate from the table ACL: a column grant never shows up in relacl.
_COLUMN_PRIVILEGES = """
SELECT a.attrelid, a.attname,
       CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(x.grantee) END,
       x.privilege_type, x.is_grantable
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
CROSS JOIN LATERAL aclexplode(a.attacl) x
WHERE a.attrelid = ANY (%s) AND a.attnum > 0 AND NOT a.attisdropped AND x.grantee <> c.relowner
ORDER BY a.attrelid, a.attname, 3, x.privilege_type
"""

_FUNCTIONS = f"""
SELECT p.proname, pg_get_userbyid(p.proowner), p.prosecdef
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = %s AND {_NOT_EXTENSION_MEMBER.format(catalog="pg_proc", oid="p.oid")}
ORDER BY p.proname
"""


def read_catalog(conn: psycopg.Connection, schema: str = "public") -> CatalogSnapshot:
    """Read the facts of one schema. Needs no special privilege beyond being able to connect."""
    relations = conn.execute(_RELATIONS, (schema,)).fetchall()
    oids = [row[0] for row in relations]
    columns: dict[int, list[ColumnInfo]] = {}
    for oid, name, type_name, not_null in conn.execute(_COLUMNS, (oids,)):
        columns.setdefault(oid, []).append(ColumnInfo(name, type_name, not_null))
    policies: dict[int, list[PolicyInfo]] = {}
    for oid, name, command, using, with_check, permissive, roles in conn.execute(
        _POLICIES, (oids,)
    ):
        policies.setdefault(oid, []).append(
            PolicyInfo(name, command, using, with_check, permissive, tuple(roles))
        )
    foreign_keys: dict[int, list[ForeignKeyInfo]] = {}
    for oid, name, cols, ref_table, ref_cols in conn.execute(_FOREIGN_KEYS, (oids,)):
        foreign_keys.setdefault(oid, []).append(
            ForeignKeyInfo(name, tuple(cols), ref_table, tuple(ref_cols))
        )
    privileges: dict[int, list[Privilege]] = {}
    for oid, grantee, privilege in conn.execute(_PRIVILEGES, (oids,)):
        privileges.setdefault(oid, []).append(Privilege(grantee, privilege))
    column_privileges: dict[int, list[ColumnPrivilege]] = {}
    for oid, column, grantee, privilege, grantable in conn.execute(_COLUMN_PRIVILEGES, (oids,)):
        column_privileges.setdefault(oid, []).append(
            ColumnPrivilege(column, grantee, privilege, grantable)
        )
    tables = tuple(
        TableInfo(
            name=name,
            kind=kind,
            owner=owner,
            rls_enabled=enabled,
            rls_forced=forced,
            security_invoker=invoker,
            columns=tuple(columns.get(oid, ())),
            policies=tuple(policies.get(oid, ())),
            foreign_keys=tuple(foreign_keys.get(oid, ())),
            privileges=tuple(privileges.get(oid, ())),
            column_privileges=tuple(column_privileges.get(oid, ())),
        )
        for oid, name, kind, owner, enabled, forced, invoker in relations
    )
    functions = tuple(
        FunctionInfo(name, owner, definer)
        for name, owner, definer in conn.execute(_FUNCTIONS, (schema,))
    )
    return CatalogSnapshot(tables=tables, functions=functions)
