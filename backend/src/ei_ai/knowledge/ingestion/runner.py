"""The in-process runner of ingestion jobs, owned by the API process (EA-33, R2, R3).

Each submitted envelope runs as an asyncio task through ``run_tenant_job``, so the job always
executes in its own Organization's tenant transaction. At most ``max_parallel`` jobs run at once;
the others wait. The document row (status ``queued``) is the durable record: a job lost with the
process is shown as interrupted (see ``status.py``).

When an embedder is configured, an ingest job that ended normally is followed by the index job of
the same document (EA-35, R8), built by ``follow_up`` so it keeps the verified Organization. The
index job waits for a slot like any job; it is not on the progress board (the document is already
``ready``), and its failure leaves the document ``ready`` and not indexed.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.envelope import JobEnvelope, follow_up
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.knowledge.indexing.job import INDEX_DOCUMENT
from ei_ai.knowledge.ingestion.job import document_id_of
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.storage.files import OrgFileStore


class IngestionRunner:
    """Runs ingestion envelopes (and their index follow-ups) in the background, a few at a time."""

    def __init__(
        self,
        engine: Callable[[], AsyncEngine],
        files: Callable[[], OrgFileStore],
        progress: ProgressBoard,
        max_parallel: int = 2,
        embedder: Callable[[], ChunkEmbedder | None] = lambda: None,
    ) -> None:
        self._engine = engine
        self._files = files
        self._progress = progress
        self._embedder = embedder
        self._slots = asyncio.Semaphore(max_parallel)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, envelope: JobEnvelope) -> None:
        """Tracks the job as waiting and starts it in the background (call on the event loop).

        Input: the envelope built by ``envelope_for``. Output: None.
        """
        document_id = document_id_of(envelope.payload)
        self._progress.track(envelope, document_id)
        self._start(self._ingest(envelope), lambda: self._progress.untrack(envelope, document_id))

    def _start(
        self, job: Coroutine[Any, Any, None], finished: Callable[[], None] = lambda: None
    ) -> None:
        """Runs ``job`` as a tracked task; ``finished`` runs when the task ends."""
        task = asyncio.get_running_loop().create_task(job)

        def done(ended: asyncio.Task[None]) -> None:
            # A done callback also runs for a task cancelled before it started.
            self._tasks.discard(ended)
            finished()

        self._tasks.add(task)
        task.add_done_callback(done)

    async def _ingest(self, envelope: JobEnvelope) -> None:
        """Runs the ingest job, then queues the index job when an embedder is configured."""
        if not await self._run(envelope, None):
            return
        embedder = self._embedder()
        if embedder is None:
            return
        document_id = document_id_of(envelope.payload)
        index = follow_up(envelope, INDEX_DOCUMENT, {"document_id": str(document_id)})
        self._start(self._index(index, embedder))

    async def _index(self, envelope: JobEnvelope, embedder: ChunkEmbedder) -> None:
        """Runs the index job (a failure is logged and leaves the document not indexed)."""
        await self._run(envelope, embedder)

    async def _run(self, envelope: JobEnvelope, embedder: ChunkEmbedder | None) -> bool:
        """Waits for a slot, then runs the job with the runtime set; True when it ended normally.

        A failure has been logged by ``run_tenant_job`` (kind, org, error class) and rolled back:
        an ingest job leaves the document queued (shown as interrupted later), an index job
        leaves it ready and not indexed.
        """
        async with self._slots:
            with use_runtime(IngestionRuntime(self._files(), self._progress, embedder)):
                try:
                    await run_tenant_job(self._engine(), envelope)
                except Exception:
                    return False
        return True

    async def drain(self) -> None:
        """Waits until every submitted job has ended, including jobs submitted meanwhile."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self) -> None:
        """Cancels the running and waiting jobs, and any follow-up they queued, and waits for
        them to end."""
        while self._tasks:
            for task in tuple(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
