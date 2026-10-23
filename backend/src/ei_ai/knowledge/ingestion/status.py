"""The status shown to clients, derived at read time from the stored status and the runner
(EA-33, R4). Nothing is written here; the caller passes the clock's ``now``."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ei_ai.knowledge.ingestion.progress import TrackState

INTERRUPTED_AFTER = timedelta(minutes=2)
INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class ShownStatus:
    status: str
    progress: int | None
    reason: str | None


def shown_status(
    stored: str,
    reason: str | None,
    updated_at: datetime,
    track: TrackState | None,
    now: datetime,
) -> ShownStatus:
    """The API status of a document.

    Input: the stored status and reason, the row's ``updated_at``, the runner's state of the
    document (None when not tracked) and the current time.
    Output: ``queued`` while waiting, ``processing`` with a percentage while running,
    ``failed``/``interrupted`` for a queued row no job holds after ``INTERRUPTED_AFTER``,
    else the stored status and reason.
    """
    if stored != "queued":
        return ShownStatus(status=stored, progress=None, reason=reason)
    if track is not None and track.running:
        return ShownStatus(status="processing", progress=track.percent, reason=None)
    if track is None and now - updated_at > INTERRUPTED_AFTER:
        return ShownStatus(status="failed", progress=None, reason=INTERRUPTED)
    return ShownStatus(status="queued", progress=None, reason=None)
