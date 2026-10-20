"""The schema guard (FND-01 AC1): judges a catalog snapshot against the tenant-isolation rules.

It runs after every migration (``ei-ai db upgrade``) and therefore in CI, so a table without
``org_id`` or without the standard row-level security policy cannot be merged (D46, layer 2).
It is a CI and review gate: it reports after the migrations were committed, it does not undo them.
Messages name the object and the rule only (D52); they never contain row data.

Rules (stable codes):
  G1  the tenant key exists, is uuid and NOT NULL
  G2  row-level security is ENABLED and FORCED
  G3  at least one policy
  G4  every permissive policy expression equals the standard tenant expression exactly and has no
      TO clause (permissive policies are OR-ed, so any other expression could widen access); the
      one exception is SIGN_IN_LOOKUP_ALLOWANCE, matched exactly
  G5  a permissive policy FOR ALL with the standard expression exists
  G6  the migration role owns the object, never the application role
  G7  the application role gets SELECT/INSERT/UPDATE/DELETE only (TRUNCATE would bypass RLS)
  G8  no application-role privilege on partitions or on ignored tables
  G9  views are security_invoker; materialised views have no application-role privilege
  G10 functions are owned by the migration role and are not SECURITY DEFINER
  G11 a foreign key between tenant tables pairs the tenant key with the tenant key
  G12 a table without the tenant key must be a listed ignored table
  G13 a restrictive policy may read app.current_org only through the standard NULLIF form
      (it can only narrow access, but without NULLIF it errors on '' instead of failing closed)
  G14 the sign-in lookup role holds exactly SELECT on users(email, id, org_id) as column
      privileges, and no other table, column or privilege (PUBLIC grants count as its own)
"""

import re
from dataclasses import dataclass

from ei_ai.db.catalog import CatalogSnapshot, FunctionInfo, PolicyInfo, TableInfo
from ei_ai.db.migrations.roles import APP_ROLE, OWNER_ROLE, SIGNIN_ROLE

DEFAULT_TENANT_KEY = "org_id"

# Tables whose tenant key is not org_id: organizations is its own tenant.
TENANT_KEY = {"organizations": "id"}

# Tables outside the rules (no tenant data), each with the reason. The app role gets nothing.
IGNORED_TABLES = {"alembic_version": "migration bookkeeping, no tenant data"}

ALLOWED_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_SETTING = "(nullif(current_setting('app.current_org'::text, true), ''::text))::uuid"
_APP_GRANTEES = frozenset({APP_ROLE, "PUBLIC"})
_SIGNIN_GRANTEES = frozenset({SIGNIN_ROLE, "PUBLIC"})
_NO_TO_CLAUSE = ("PUBLIC",)
_ANY_SETTING_READ = "current_setting('app.current_org'"


@dataclass(frozen=True)
class PolicyAllowance:
    """One reviewed permissive policy outside the standard form, matched field by field."""

    table: str
    policy: str
    roles: frozenset[str]
    command: str
    using: str  # normalised; the policy has no WITH CHECK
    reason: str

    def matches(self, table: TableInfo, policy: PolicyInfo) -> bool:
        return (
            table.name == self.table
            and policy.name == self.policy
            and policy.permissive
            and frozenset(policy.roles) == self.roles
            and policy.command == self.command
            and policy.using is not None
            and _normalise(policy.using) == self.using
            and policy.with_check is None
        )


# The only cross-tenant read (EA-22, R42, owner decision 2026-10-20): sign-in must find the
# Organizations of an email before any tenant is known. Bound to the sign-in role only, which G14
# limits to SELECT on users(email, id, org_id); every other role still sees no users row without
# app.current_org. Any change to this allowance is a review blocker.
SIGN_IN_LOOKUP_ALLOWANCE = PolicyAllowance(
    table="users",
    policy="sign_in_lookup",
    roles=frozenset({SIGNIN_ROLE}),
    command="SELECT",
    using="true",
    reason="sign-in finds the Organizations of an email before the tenant is known (R42)",
)

# G14: the sign-in role's complete set of privileges in the schema: (table, column, privilege).
SIGN_IN_COLUMN_PRIVILEGES = frozenset(
    {("users", "email", "SELECT"), ("users", "id", "SELECT"), ("users", "org_id", "SELECT")}
)
_SIGN_IN_COLUMNS_TEXT = "only SELECT on email, id, org_id of users is allowed"


@dataclass(frozen=True)
class Violation:
    code: str
    subject: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.subject}: {self.message}"


def _normalise(expression: str | None) -> str:
    collapsed = re.sub(r"\s+", " ", expression or "").strip().lower()
    return re.sub(r"\( ", "(", re.sub(r" \)", ")", collapsed))


def _standard_expression(key: str) -> str:
    return f"({key} = {_SETTING})"


def _is_standard(expression: str | None, key: str) -> bool:
    return _normalise(expression) == _standard_expression(key)


def _reads_setting_outside_standard_form(expression: str | None) -> bool:
    return _ANY_SETTING_READ in _normalise(expression).replace(_SETTING, "")


def _app_privileges(table: TableInfo) -> list[str]:
    return sorted(p.privilege for p in table.privileges if p.grantee in _APP_GRANTEES)


def _check_ownership_and_grants(table: TableInfo) -> list[Violation]:
    violations = []
    if table.owner != OWNER_ROLE:
        violations.append(
            Violation("G6", table.name, f"owned by {table.owner}, expected {OWNER_ROLE}")
        )
    extra = sorted(set(_app_privileges(table)) - ALLOWED_PRIVILEGES)
    if extra:
        violations.append(
            Violation(
                "G7", table.name, f"application role has {', '.join(extra)}; only DML is allowed"
            )
        )
    if table.kind in ("partition", "matview") and _app_privileges(table):
        rule = "G8" if table.kind == "partition" else "G9"
        violations.append(
            Violation(rule, table.name, f"application role has privileges on a {table.kind}")
        )
    if table.name in IGNORED_TABLES and _app_privileges(table):
        violations.append(
            Violation("G8", table.name, "application role has privileges on an ignored table")
        )
    return violations


def _check_view(table: TableInfo) -> list[Violation]:
    if table.kind == "view" and not table.security_invoker:
        return [Violation("G9", table.name, "view is not security_invoker")]
    return []


def _covers_all_commands(policy: PolicyInfo, key: str) -> bool:
    return (
        policy.permissive
        and policy.command == "ALL"
        and _is_standard(policy.using, key)
        and (policy.with_check is None or _is_standard(policy.with_check, key))
    )


def _check_policies(table: TableInfo, key: str) -> list[Violation]:
    violations = []
    if not table.rls_enabled:
        violations.append(Violation("G2", table.name, "row-level security is not enabled"))
    if not table.rls_forced:
        violations.append(Violation("G2", table.name, "row-level security is not forced"))
    if not table.policies:
        violations.append(Violation("G3", table.name, "no row-level security policy"))
        return violations
    for policy in table.policies:
        if not policy.permissive:
            # Restrictive policies are AND-ed: they can only narrow access, but they must still
            # fail closed when the setting is '' (G13).
            if _reads_setting_outside_standard_form(policy.using) or (
                _reads_setting_outside_standard_form(policy.with_check)
            ):
                violations.append(
                    Violation(
                        "G13",
                        table.name,
                        f"restrictive policy {policy.name} reads app.current_org"
                        " without the NULLIF form",
                    )
                )
            continue
        if SIGN_IN_LOOKUP_ALLOWANCE.matches(table, policy):
            continue
        expressions = [e for e in (policy.using, policy.with_check) if e]
        if not expressions or not all(_is_standard(e, key) for e in expressions):
            violations.append(
                Violation(
                    "G4", table.name, f"policy {policy.name} is not the standard tenant expression"
                )
            )
        elif policy.roles != _NO_TO_CLAUSE:
            violations.append(
                Violation(
                    "G4",
                    table.name,
                    f"policy {policy.name} has a TO clause;"
                    " only the reviewed sign-in lookup policy may",
                )
            )
    if not any(_covers_all_commands(policy, key) for policy in table.policies):
        violations.append(
            Violation("G5", table.name, f"no standard policy FOR ALL on the tenant key {key}")
        )
    return violations


def _check_tenant_key(table: TableInfo, key: str) -> list[Violation]:
    column = table.column(key)
    if column is None:
        return [Violation("G12", table.name, f"no {key} column and not a listed ignored table")]
    violations = []
    if column.type != "uuid":
        violations.append(Violation("G1", table.name, f"{key} is {column.type}, expected uuid"))
    if not column.not_null:
        violations.append(Violation("G1", table.name, f"{key} is nullable"))
    return violations


def _check_foreign_keys(table: TableInfo, tenant_keys: dict[str, str]) -> list[Violation]:
    violations = []
    for fk in table.foreign_keys:
        target = tenant_keys.get(fk.ref_table)
        if target is None or fk.ref_table == "organizations":
            continue  # the Organization root is referenced by id alone
        if (
            dict(zip(fk.columns, fk.ref_columns, strict=True)).get(tenant_keys[table.name])
            != target
        ):
            violations.append(
                Violation(
                    "G11", table.name, f"foreign key {fk.name} to {fk.ref_table} lacks {target}"
                )
            )
    return violations


def _check_function(function: FunctionInfo) -> list[Violation]:
    violations = []
    if function.owner != OWNER_ROLE:
        violations.append(
            Violation("G10", function.name, f"owned by {function.owner}, expected {OWNER_ROLE}")
        )
    if function.security_definer:
        violations.append(Violation("G10", function.name, "function is SECURITY DEFINER"))
    return violations


def _check_sign_in_privileges(snapshot: CatalogSnapshot) -> list[Violation]:
    """G14 over the whole schema: any privilege beyond the three lookup columns, or one missing."""
    violations = []
    held: set[tuple[str, str, str]] = set()
    for table in snapshot.tables:
        table_level = {p.privilege for p in table.privileges if p.grantee in _SIGNIN_GRANTEES}
        for privilege in sorted(table_level):
            violations.append(
                Violation("G14", table.name, f"sign-in role has the table privilege {privilege}")
            )
        for granted in table.column_privileges:
            if granted.grantee not in _SIGNIN_GRANTEES:
                continue
            entry = (table.name, granted.column, granted.privilege)
            if entry not in SIGN_IN_COLUMN_PRIVILEGES:
                violations.append(
                    Violation(
                        "G14",
                        table.name,
                        f"sign-in role has {granted.privilege} on column {granted.column};"
                        f" {_SIGN_IN_COLUMNS_TEXT}",
                    )
                )
                continue
            held.add(entry)
            if granted.grantable:
                violations.append(
                    Violation(
                        "G14",
                        table.name,
                        f"sign-in role may grant {granted.privilege} on column {granted.column}",
                    )
                )
    for table_name, column, privilege in sorted(SIGN_IN_COLUMN_PRIVILEGES - held):
        violations.append(
            Violation("G14", table_name, f"sign-in role lacks {privilege} on column {column}")
        )
    return violations


def guarded_table_names(snapshot: CatalogSnapshot) -> list[str]:
    """Names of the tables the rules apply to (every table that is not ignored)."""
    return [t.name for t in snapshot.tables if t.kind == "table" and t.name not in IGNORED_TABLES]


def find_violations(snapshot: CatalogSnapshot) -> list[Violation]:
    """All rule violations in the snapshot, ordered by object (empty means the schema is sound)."""
    tenant_keys = {
        name: TENANT_KEY.get(name, DEFAULT_TENANT_KEY) for name in guarded_table_names(snapshot)
    }
    violations: list[Violation] = []
    for table in snapshot.tables:
        violations += _check_ownership_and_grants(table)
        violations += _check_view(table)
        if table.name not in tenant_keys:
            continue
        key = tenant_keys[table.name]
        violations += _check_tenant_key(table, key)
        violations += _check_policies(table, key)
        violations += _check_foreign_keys(table, tenant_keys)
    for function in snapshot.functions:
        violations += _check_function(function)
    violations += _check_sign_in_privileges(snapshot)
    return violations
