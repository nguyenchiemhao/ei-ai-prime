"""The isolation check for background jobs (AC3), reused by every story that registers a job.

A job queued for one Organization must run in that Organization's tenant context: whatever
payload it is given, it cannot read or change the other Organization's data, and it leaves no
tenant context behind on the pooled connection.
"""

from collections.abc import Sequence
from contextlib import suppress

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.envelope import envelope_for
from ei_ai.jobs.registry import JobRegistry
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.tenancy.context import TenantContext
from support.tenants import OrgRows

from .cases import JobCase
from .markers import assert_no_markers, assert_nothing_copied, capture_logs
from .snapshot import snapshot_org
from .valkey import assert_org_keys_unchanged, open_valkey, snapshot_org_keys


def job_coverage_problems(registry: JobRegistry, cases: Sequence[JobCase]) -> list[str]:
    """Everything wrong with the job declarations; empty means every registered job is covered."""
    declared = {case.kind for case in cases}
    problems = [
        f"job has no isolation test declared: {kind}"
        for kind in registry.kinds()
        if kind not in declared
    ]
    problems += [
        f"isolation case for a job that does not exist: {kind}"
        for kind in sorted(declared - set(registry.kinds()))
    ]
    return problems


def _tenant(rows: OrgRows) -> TenantContext:
    return TenantContext(org_id=rows.org_id, user_id=rows.user_id)


async def assert_job_isolated(
    engine: AsyncEngine, registry: JobRegistry, case: JobCase, me: OrgRows, other: OrgRows
) -> None:
    """Run the job for ``me`` with a payload naming ``other``'s rows, then with its own rows."""
    where = f"job {case.kind} ({me.label}->{other.label})"
    before = await snapshot_org(engine, other)
    async with open_valkey() as valkey:
        keys_before = await snapshot_org_keys(valkey, other)

    cross = envelope_for(_tenant(me), case.kind, case.payload(other))
    with capture_logs() as logs, suppress(Exception):
        # Completing or failing are both fine: only what the job could see or change matters.
        await run_tenant_job(engine, cross, registry)
    assert_no_markers(logs.text, other, f"{where}: logs")
    assert await snapshot_org(engine, other) == before, (
        f"{where}: data of Organization {other.label} changed"
    )

    async with open_valkey() as valkey:
        await assert_org_keys_unchanged(valkey, other, keys_before, where)
    await assert_nothing_copied(engine, me, other, where)

    own = envelope_for(_tenant(me), case.kind, case.payload(me))
    await run_tenant_job(engine, own, registry)  # positive control: a case cannot pass vacuously

    async with engine.connect() as conn:
        leftover = (
            await conn.execute(text("SELECT current_setting('app.current_org', true)"))
        ).scalar()
    assert leftover in (None, ""), f"{where}: the connection kept a tenant context"
