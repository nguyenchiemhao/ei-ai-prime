"""The in-process ingestion runner: at most two jobs at once, drained in tests (EA-33, R2, R3)."""

import asyncio
import logging
import os
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.jobs.envelope import JobEnvelope, envelope_for
from ei_ai.knowledge.ingestion import job as ingestion_job
from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.progress import ProgressBoard, TrackState
from ei_ai.knowledge.ingestion.result_rows import lock_queued_document
from ei_ai.knowledge.ingestion.runner import IngestionRunner
from ei_ai.storage.files import OrgFileStore
from ei_ai.tenancy.context import TenantContext
from support.tenants import OrgRows, TwoOrgs

from .conftest import document_row, file_store, queue_document

pytestmark = pytest.mark.integration

WAIT_SECONDS = 10


@pytest.fixture
async def pool_engine() -> AsyncIterator[AsyncEngine]:
    """An engine with room for parallel jobs (the shared fixture has a single connection)."""
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=4)
    try:
        yield engine
    finally:
        await engine.dispose()


def _tenant(org: OrgRows) -> TenantContext:
    return TenantContext(org_id=org.org_id, user_id=org.user_id)


def _envelope(org: OrgRows, document_id: uuid.UUID) -> JobEnvelope:
    return envelope_for(_tenant(org), INGEST_DOCUMENT, {"document_id": str(document_id)})


def _runner(engine: AsyncEngine, storage: OrgFileStore, board: ProgressBoard) -> Any:
    return IngestionRunner(lambda: engine, lambda: storage, board)


async def _wait_until(condition: Any) -> None:
    for _ in range(WAIT_SECONDS * 100):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


async def test_runner_runs_at_most_two_jobs(
    pool_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = two_orgs.a
    storage = file_store(tmp_path)
    board = ProgressBoard()
    runner = _runner(pool_engine, storage, board)
    documents = [
        await queue_document(pool_engine, storage, a, "txt", f"Text {n}.\n".encode())
        for n in range(3)
    ]
    release = threading.Event()
    lock = threading.Lock()
    running = [0]
    most = [0]

    def blocking_extract(*args: Any) -> Any:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        release.wait(WAIT_SECONDS)
        with lock:
            running[0] -= 1
        return extract_document(*args)

    monkeypatch.setattr(ingestion_job, "extract_document", blocking_extract)

    try:
        for document_id in documents:
            runner.submit(_envelope(a, document_id))
        await _wait_until(lambda: running[0] == 2)
        await asyncio.sleep(0.2)
        states = [board.read(_tenant(a), document_id) for document_id in documents]
        assert running[0] == 2
        assert sum(1 for state in states if state is not None and state.running) == 2
        assert TrackState(running=False, percent=0) in states
    finally:
        release.set()
        await runner.drain()

    assert most[0] == 2
    rows = [await document_row(pool_engine, a, document_id) for document_id in documents]
    assert [row.status for row in rows] == ["ready", "ready", "ready"]


async def test_drain_waits_and_untracks(
    pool_engine: AsyncEngine, two_orgs: TwoOrgs, tmp_path: Path
) -> None:
    a = two_orgs.a
    storage = file_store(tmp_path)
    board = ProgressBoard()
    runner = _runner(pool_engine, storage, board)
    document_id = await queue_document(pool_engine, storage, a, "md", b"# Title\n\nBody text.\n")

    runner.submit(_envelope(a, document_id))
    assert board.read(_tenant(a), document_id) is not None
    await runner.drain()

    assert board.read(_tenant(a), document_id) is None
    row = await document_row(pool_engine, a, document_id)
    assert (row.status, row.page_count) == ("ready", 1)


async def test_failed_job_does_not_stop_the_runner(
    pool_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = two_orgs.a
    storage = file_store(tmp_path)
    board = ProgressBoard()
    runner = _runner(pool_engine, storage, board)
    bad = await queue_document(pool_engine, storage, a, "txt", b"Bad one.\n")
    good = await queue_document(pool_engine, storage, a, "txt", b"Good one.\n")

    async def lock_or_fail(conn: Any, org_id: uuid.UUID, document_id: uuid.UUID) -> Any:
        if document_id == bad:
            raise RuntimeError("lost connection")
        return await lock_queued_document(conn, org_id, document_id)

    monkeypatch.setattr(ingestion_job, "lock_queued_document", lock_or_fail)
    caplog.set_level(logging.INFO)

    runner.submit(_envelope(a, bad))
    runner.submit(_envelope(a, good))
    await runner.drain()

    assert (await document_row(pool_engine, a, bad)).status == "queued"
    assert (await document_row(pool_engine, a, good)).status == "ready"
    assert board.read(_tenant(a), bad) is None
    assert board.read(_tenant(a), good) is None
    failures = [r.getMessage() for r in caplog.records if r.name == "ei_ai.jobs"]
    assert failures == [
        f"tenant_job_failed kind={INGEST_DOCUMENT} org_id={a.org_id} error=RuntimeError"
    ]


async def test_close_cancels_waiting_jobs_and_untracks(
    pool_engine: AsyncEngine,
    two_orgs: TwoOrgs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = two_orgs.a
    storage = file_store(tmp_path)
    board = ProgressBoard()
    runner = _runner(pool_engine, storage, board)
    document_id = await queue_document(pool_engine, storage, a, "txt", b"Waits.\n")
    started = asyncio.Event()

    async def hang(*args: Any) -> None:
        started.set()
        await asyncio.sleep(WAIT_SECONDS)

    monkeypatch.setattr(ingestion_job, "lock_queued_document", hang)

    runner.submit(_envelope(a, document_id))
    await asyncio.wait_for(started.wait(), WAIT_SECONDS)
    await runner.close()

    assert board.read(_tenant(a), document_id) is None
    assert (await document_row(pool_engine, a, document_id)).status == "queued"
