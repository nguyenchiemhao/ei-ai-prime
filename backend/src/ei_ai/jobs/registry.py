"""The registry of job kinds and their handlers."""

import re
from collections.abc import Awaitable, Callable, Mapping

from ei_ai.jobs.envelope import JobContext

JobHandler = Callable[[JobContext, Mapping[str, object]], Awaitable[None]]

_KIND = re.compile(r"[a-z][a-z0-9_.-]*")


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str) -> Callable[[JobHandler], JobHandler]:
        """Decorator: ``@JOBS.register("ingest.document")``."""
        if not _KIND.fullmatch(kind):
            raise ValueError("job kind must match ^[a-z][a-z0-9_.-]*$")
        if kind in self._handlers:
            raise ValueError(f"job kind already registered: {kind}")

        def decorator(handler: JobHandler) -> JobHandler:
            self._handlers[kind] = handler
            return handler

        return decorator

    def handler(self, kind: str) -> JobHandler:
        try:
            return self._handlers[kind]
        except KeyError:
            raise KeyError(kind) from None

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


# Empty today. KB-02 (EA-33) registers document ingestion here and runs its queue tasks through
# ``run_tenant_job``; every kind registered here needs a JobCase in the isolation suite.
JOBS = JobRegistry()
