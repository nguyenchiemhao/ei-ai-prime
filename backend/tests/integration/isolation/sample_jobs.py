"""Sample job handlers that stand in for "processing an Organization's document".

There is no documents table yet, so the fixture Workspace plays the document. A test registry is
built per test; these handlers are never registered in the production ``JOBS``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import text

from ei_ai.jobs.envelope import JobContext
from ei_ai.jobs.registry import JobRegistry


@dataclass
class Recorder:
    """What the sample handlers saw."""

    tenant_settings: list[str | None] = field(default_factory=list)
    rows_seen: list[int] = field(default_factory=list)
    rows_changed: list[int] = field(default_factory=list)


async def _setting(context: JobContext) -> str | None:
    result = await context.session.execute(text("SELECT current_setting('app.current_org', true)"))
    value = result.scalar()
    return None if value is None else str(value)


def sample_registry(recorder: Recorder) -> JobRegistry:
    registry = JobRegistry()

    @registry.register("sample.read")
    async def read(context: JobContext, payload: Mapping[str, object]) -> None:
        recorder.tenant_settings.append(await _setting(context))
        found = await context.session.execute(
            text("SELECT id FROM workspaces WHERE id = :id"), {"id": payload["workspace_id"]}
        )
        recorder.rows_seen.append(len(found.all()))

    @registry.register("sample.update")
    async def update(context: JobContext, payload: Mapping[str, object]) -> None:
        result = await context.session.execute(
            text("UPDATE workspaces SET name = 'renamed-by-job' WHERE id = :id"),
            {"id": payload["workspace_id"]},
        )
        recorder.rows_changed.append(result.rowcount)  # type: ignore[attr-defined]

    @registry.register("sample.delete")
    async def delete(context: JobContext, payload: Mapping[str, object]) -> None:
        result = await context.session.execute(
            text("DELETE FROM workspaces WHERE id = :id"), {"id": payload["workspace_id"]}
        )
        recorder.rows_changed.append(result.rowcount)  # type: ignore[attr-defined]

    @registry.register("sample.insert-for")
    async def insert_for(context: JobContext, payload: Mapping[str, object]) -> None:
        await context.session.execute(
            text("INSERT INTO workspaces (org_id, name) VALUES (:org, 'forged-by-job')"),
            {"org": payload["target_org"]},
        )

    @registry.register("sample.write-then-fail")
    async def write_then_fail(context: JobContext, payload: Mapping[str, object]) -> None:
        await context.session.execute(
            text("INSERT INTO workspaces (org_id, name) VALUES (:org, 'written-before-failure')"),
            {"org": context.org_id},
        )
        raise RuntimeError(f"boom {payload['secret']}")

    @registry.register("sample.process")
    async def process(context: JobContext, payload: Mapping[str, object]) -> None:
        """The well-behaved "document" job: reads and renames the Workspace it is given."""
        await context.session.execute(
            text("UPDATE workspaces SET name = name || '' WHERE id = :id"),
            {"id": payload["workspace_id"]},
        )

    return registry
