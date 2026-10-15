"""The registry of job kinds: unique, well-formed names; unknown kinds fail without leaking."""

import uuid
from collections.abc import Mapping
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.jobs.registry import JOBS, JobRegistry
from ei_ai.jobs.runner import run_tenant_job


async def _noop(context: JobContext, payload: Mapping[str, object]) -> None:
    return None


def test_a_registered_handler_is_found_by_its_kind() -> None:
    registry = JobRegistry()
    registry.register("ingest.document")(_noop)

    assert registry.handler("ingest.document") is _noop
    assert registry.kinds() == ("ingest.document",)


def test_kinds_are_listed_in_name_order() -> None:
    registry = JobRegistry()
    registry.register("b.job")(_noop)
    registry.register("a.job")(_noop)

    assert registry.kinds() == ("a.job", "b.job")


def test_a_kind_cannot_be_registered_twice() -> None:
    registry = JobRegistry()
    registry.register("ingest.document")(_noop)

    with pytest.raises(ValueError, match="already registered: ingest.document"):
        registry.register("ingest.document")(_noop)


@pytest.mark.parametrize("kind", ["", "Ingest", "1job", "has space", "a:b", "abc\n"])
def test_a_malformed_kind_is_refused(kind: str) -> None:
    with pytest.raises(ValueError, match="job kind"):
        JobRegistry().register(kind)


def test_an_unknown_kind_names_only_the_kind() -> None:
    with pytest.raises(KeyError, match="no.such.job"):
        JobRegistry().handler("no.such.job")


def test_the_production_registry_starts_empty() -> None:
    assert JOBS.kinds() == ()


async def test_the_runner_resolves_the_handler_before_opening_anything() -> None:
    envelope = JobEnvelope(kind="no.such.job", org_id=uuid.uuid4(), payload={})

    with pytest.raises(KeyError, match="no.such.job"):
        await run_tenant_job(cast(AsyncEngine, None), envelope, JobRegistry())


async def test_the_runner_refuses_an_organization_that_is_not_a_uuid() -> None:
    registry = JobRegistry()
    registry.register("ingest.document")(_noop)
    envelope = JobEnvelope(kind="ingest.document", org_id="org-1", payload={})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="org_id must be a uuid.UUID"):
        await run_tenant_job(cast(AsyncEngine, None), envelope, registry)
