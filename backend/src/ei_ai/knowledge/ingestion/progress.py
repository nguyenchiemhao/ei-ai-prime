"""In-memory progress of ingestion jobs, keyed by ``(org_id, document_id)`` (EA-33, R4).

Only the runner and the job write here; a reader gets an entry only with the verified
``TenantContext`` of the same Organization (D46). Reports arrive from worker threads, so every
access holds a lock.
"""

import threading
import uuid
from dataclasses import dataclass

from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.tenancy.context import TenantContext

_Key = tuple[uuid.UUID, uuid.UUID]


@dataclass(frozen=True)
class TrackState:
    """A tracked job: waiting for a slot (``running`` False) or running at ``percent``."""

    running: bool
    percent: int


def _key(source: JobEnvelope | JobContext | TenantContext, document_id: uuid.UUID) -> _Key:
    """The board key of a document, taking the Organization from a verified object only.

    Input: the envelope, job context or tenant context, and the document id.
    Output: ``(org_id, document_id)``; ``TypeError`` for any other source.
    """
    if not isinstance(source, JobEnvelope | JobContext | TenantContext):
        raise TypeError(f"progress needs a verified context, got {type(source).__name__}")
    return (source.org_id, document_id)


class ProgressBoard:
    """Which documents have a job in this process, and how far each running job is."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[_Key, TrackState] = {}

    def track(self, envelope: JobEnvelope, document_id: uuid.UUID) -> None:
        """Marks a submitted job as waiting for a slot."""
        with self._lock:
            self._states[_key(envelope, document_id)] = TrackState(running=False, percent=0)

    def start(self, ctx: JobContext, document_id: uuid.UUID) -> None:
        """Marks the job as running at 0 percent."""
        with self._lock:
            self._states[_key(ctx, document_id)] = TrackState(running=True, percent=0)

    def report(self, ctx: JobContext, document_id: uuid.UUID, percent: int) -> None:
        """Records the progress of a tracked job, kept within 0-100; an untracked document is
        ignored, so a late report cannot bring back a finished job."""
        key = _key(ctx, document_id)
        with self._lock:
            if key in self._states:
                self._states[key] = TrackState(running=True, percent=max(0, min(100, percent)))

    def untrack(self, envelope: JobEnvelope, document_id: uuid.UUID) -> None:
        """Forgets the job once it has ended (done, failed or cancelled)."""
        with self._lock:
            self._states.pop(_key(envelope, document_id), None)

    def read(self, tenant: TenantContext, document_id: uuid.UUID) -> TrackState | None:
        """The state of a document of the caller's Organization, else None."""
        key = _key(tenant, document_id)
        with self._lock:
            return self._states.get(key)
