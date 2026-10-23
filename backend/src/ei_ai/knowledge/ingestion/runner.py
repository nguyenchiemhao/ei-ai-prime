"""The in-process runner of ingestion jobs, owned by the API process (EA-33, R2, R3).

Each submitted envelope runs as an asyncio task through ``run_tenant_job``, so the job always
executes in its own Organization's tenant transaction. At most ``max_parallel`` jobs run at once;
the others wait. The document row (status ``queued``) is the durable record: a job lost with the
process is shown as interrupted (see ``status.py``).
"""

import asyncio
import contextlib
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.jobs.envelope import JobEnvelope
from ei_ai.jobs.runner import run_tenant_job
from ei_ai.knowledge.ingestion.job import document_id_of
from ei_ai.knowledge.ingestion.progress import ProgressBoard
from ei_ai.knowledge.ingestion.runtime import IngestionRuntime, use_runtime
from ei_ai.storage.files import OrgFileStore


class IngestionRunner:
    """Runs ingestion envelopes in the background, a few at a time."""

    def __init__(
        self,
        engine: Callable[[], AsyncEngine],
        files: Callable[[], OrgFileStore],
        progress: ProgressBoard,
        max_parallel: int = 2,
    ) -> None:
        self._engine = engine
        self._files = files
        self._progress = progress
        self._slots = asyncio.Semaphore(max_parallel)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, envelope: JobEnvelope) -> None:
        """Tracks the job as waiting and starts it in the background (call on the event loop).

        Input: the envelope built by ``envelope_for``. Output: None.
        """
        document_id = document_id_of(envelope.payload)
        self._progress.track(envelope, document_id)
        task = asyncio.get_running_loop().create_task(self._run(envelope))

        def finished(done: asyncio.Task[None]) -> None:
            # A done callback also runs for a task cancelled before it started.
            self._tasks.discard(done)
            self._progress.untrack(envelope, document_id)

        self._tasks.add(task)
        task.add_done_callback(finished)

    async def _run(self, envelope: JobEnvelope) -> None:
        """Waits for a slot, then runs the job with the runtime set."""
        async with self._slots:
            with use_runtime(IngestionRuntime(self._files(), self._progress)):
                # run_tenant_job has logged the failure (kind, org, error class) and rolled
                # back; the document stays queued and is shown as interrupted later.
                with contextlib.suppress(Exception):
                    await run_tenant_job(self._engine(), envelope)

    async def drain(self) -> None:
        """Waits until every submitted job has ended, including jobs submitted meanwhile."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self) -> None:
        """Cancels the running and waiting jobs and waits for them to end."""
        for task in self._tasks:
            task.cancel()
        await self.drain()
