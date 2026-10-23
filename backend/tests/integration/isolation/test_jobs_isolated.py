"""AC3: a background job runs with the tenant context of its own Organization and cannot read or
write the data of another one. The sample handlers stand in for "processing an Organization's
document" (see ``sample_jobs.py``); the production ``JOBS`` kinds (KB-02 document ingestion)
are checked through their ``JobCase`` in ``cases.py``.
"""

import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.jobs.envelope import JobEnvelope
from ei_ai.jobs.registry import JOBS
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.storage.files import OrgFileStore
from support.crypto import TEST_MASTER_KEY
from support.fake_embedder import FakeEmbedder
from support.isolation.cases import JobCase
from support.isolation.jobs import assert_job_isolated, job_coverage_problems
from support.isolation.snapshot import snapshot_org
from support.tenants import OrgRows, TwoOrgs

from .cases import JOB_CASES
from .sample_jobs import Recorder, sample_registry


def _envelope(kind: str, org: OrgRows, **payload: object) -> JobEnvelope:
    return JobEnvelope(kind=kind, org_id=org.org_id, payload=payload)


async def _tenant_setting(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        value = (
            await conn.execute(text("SELECT current_setting('app.current_org', true)"))
        ).scalar()
    return None if value is None else str(value)


async def test_job_runs_with_the_tenant_context_of_its_envelope(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    recorder = Recorder()
    envelope = _envelope("sample.read", two_orgs.a, workspace_id=str(two_orgs.a.workspace_id))

    await run_tenant_job(app_engine, envelope, sample_registry(recorder))

    assert recorder.tenant_settings == [str(two_orgs.a.org_id)]
    assert recorder.rows_seen == [1]


async def test_job_for_a_cannot_read_b_rows(app_engine: AsyncEngine, two_orgs: TwoOrgs) -> None:
    recorder = Recorder()
    envelope = _envelope("sample.read", two_orgs.a, workspace_id=str(two_orgs.b.workspace_id))

    await run_tenant_job(app_engine, envelope, sample_registry(recorder))

    assert recorder.rows_seen == [0]


@pytest.mark.parametrize("kind", ["sample.update", "sample.delete"])
async def test_job_for_a_cannot_update_or_delete_b_rows(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, kind: str
) -> None:
    recorder = Recorder()
    before = await snapshot_org(app_engine, two_orgs.b)
    envelope = _envelope(kind, two_orgs.a, workspace_id=str(two_orgs.b.workspace_id))

    await run_tenant_job(app_engine, envelope, sample_registry(recorder))

    assert recorder.rows_changed == [0]
    assert await snapshot_org(app_engine, two_orgs.b) == before


async def test_job_for_a_cannot_insert_rows_for_b(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    before = await snapshot_org(app_engine, two_orgs.b)
    envelope = _envelope("sample.insert-for", two_orgs.a, target_org=str(two_orgs.b.org_id))

    with pytest.raises(DBAPIError) as error:
        await run_tenant_job(app_engine, envelope, sample_registry(Recorder()))

    assert getattr(error.value.orig, "sqlstate", None) == "42501"
    assert "forged-by-job" not in str(error.value.orig)
    assert await snapshot_org(app_engine, two_orgs.b) == before


async def test_failed_job_rolls_back_and_leaves_no_context(
    app_engine: AsyncEngine, two_orgs: TwoOrgs, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    before = await snapshot_org(app_engine, two_orgs.a)
    envelope = _envelope("sample.write-then-fail", two_orgs.a, secret="payload-secret-value")

    with pytest.raises(RuntimeError):
        await run_tenant_job(app_engine, envelope, sample_registry(Recorder()))

    assert await snapshot_org(app_engine, two_orgs.a) == before
    assert await _tenant_setting(app_engine) in (None, "")
    failures = [r for r in caplog.records if r.name == "ei_ai.jobs"]
    assert [r.getMessage() for r in failures] == [
        f"tenant_job_failed kind=sample.write-then-fail org_id={two_orgs.a.org_id}"
        " error=RuntimeError"
    ]
    assert "payload-secret-value" not in caplog.text


async def test_next_job_on_the_same_connection_sees_only_its_own_org(
    app_engine: AsyncEngine, two_orgs: TwoOrgs
) -> None:
    recorder = Recorder()
    registry = sample_registry(recorder)
    a, b = two_orgs.a, two_orgs.b

    await run_tenant_job(
        app_engine, _envelope("sample.read", a, workspace_id=str(a.workspace_id)), registry
    )
    await run_tenant_job(
        app_engine, _envelope("sample.read", b, workspace_id=str(a.workspace_id)), registry
    )
    await run_tenant_job(
        app_engine, _envelope("sample.read", b, workspace_id=str(b.workspace_id)), registry
    )

    assert recorder.tenant_settings == [str(a.org_id), str(b.org_id), str(b.org_id)]
    assert recorder.rows_seen == [1, 0, 1]


async def test_job_with_an_unknown_organization_sees_nothing(app_engine: AsyncEngine) -> None:
    recorder = Recorder()
    ghost = uuid.uuid4()
    envelope = JobEnvelope("sample.read", ghost, {"workspace_id": str(uuid.uuid4())})

    await run_tenant_job(app_engine, envelope, sample_registry(recorder))

    assert recorder.rows_seen == [0]


def test_every_registered_job_has_an_isolation_case() -> None:
    problems = job_coverage_problems(JOBS, JOB_CASES)

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("case", "me", "other"),
    [
        pytest.param(case, me, other, id=f"{case.kind} {me}->{other}")
        for case in JOB_CASES
        for me, other in [("A", "B"), ("B", "A")]
    ],
)
async def test_declared_jobs_are_isolated(
    case: JobCase,
    me: str,
    other: str,
    app_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    tmp_path: Path,
) -> None:
    rows = {"A": two_orgs.a, "B": two_orgs.b}
    # What the API's runner gives every job: the file store, the progress board, an embedder.
    files = OrgFileStore(tmp_path, OrgCipher(TEST_MASTER_KEY))
    with use_runtime(IngestionRuntime(files, ProgressBoard(), FakeEmbedder())):
        await assert_job_isolated(app_engine, JOBS, case, rows[me], rows[other])
