"""The in-memory progress of ingestion jobs, keyed by Organization and document."""

import threading
import uuid
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ei_ai.jobs.envelope import JobContext, JobEnvelope
from ei_ai.knowledge.ingestion.job import INGEST_DOCUMENT
from ei_ai.knowledge.ingestion.progress import ProgressBoard, TrackState
from ei_ai.tenancy.context import TenantContext

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
DOCUMENT = uuid.uuid4()


def _envelope(org_id: uuid.UUID = ORG) -> JobEnvelope:
    return JobEnvelope(INGEST_DOCUMENT, org_id, {"document_id": str(DOCUMENT)})


def _ctx(org_id: uuid.UUID = ORG) -> JobContext:
    return JobContext(org_id=org_id, session=cast(AsyncSession, None))


def _tenant(org_id: uuid.UUID = ORG) -> TenantContext:
    return TenantContext(org_id=org_id, user_id=uuid.uuid4())


def test_untracked_document_reads_none() -> None:
    assert ProgressBoard().read(_tenant(), DOCUMENT) is None


def test_tracked_document_is_waiting() -> None:
    board = ProgressBoard()

    board.track(_envelope(), DOCUMENT)

    assert board.read(_tenant(), DOCUMENT) == TrackState(running=False, percent=0)


def test_started_and_reported_document_is_running() -> None:
    board = ProgressBoard()
    board.track(_envelope(), DOCUMENT)

    board.start(_ctx(), DOCUMENT)
    board.report(_ctx(), DOCUMENT, 40)

    assert board.read(_tenant(), DOCUMENT) == TrackState(running=True, percent=40)


@pytest.mark.parametrize(("reported", "shown"), [(-5, 0), (150, 100)])
def test_report_is_kept_within_0_and_100(reported: int, shown: int) -> None:
    board = ProgressBoard()
    board.start(_ctx(), DOCUMENT)

    board.report(_ctx(), DOCUMENT, reported)

    assert board.read(_tenant(), DOCUMENT) == TrackState(running=True, percent=shown)


def test_untrack_forgets_the_document() -> None:
    board = ProgressBoard()
    board.track(_envelope(), DOCUMENT)
    board.start(_ctx(), DOCUMENT)

    board.untrack(_envelope(), DOCUMENT)

    assert board.read(_tenant(), DOCUMENT) is None


def test_report_after_untrack_does_not_track_again() -> None:
    board = ProgressBoard()
    board.track(_envelope(), DOCUMENT)
    board.untrack(_envelope(), DOCUMENT)

    board.report(_ctx(), DOCUMENT, 50)

    assert board.read(_tenant(), DOCUMENT) is None


def test_read_with_another_organization_is_none() -> None:
    board = ProgressBoard()
    board.track(_envelope(), DOCUMENT)
    board.start(_ctx(), DOCUMENT)

    assert board.read(_tenant(OTHER_ORG), DOCUMENT) is None


def test_another_organization_cannot_report_or_untrack() -> None:
    board = ProgressBoard()
    board.track(_envelope(), DOCUMENT)

    board.report(_ctx(OTHER_ORG), DOCUMENT, 70)
    board.untrack(_envelope(OTHER_ORG), DOCUMENT)

    assert board.read(_tenant(), DOCUMENT) == TrackState(running=False, percent=0)


def test_report_from_a_worker_thread() -> None:
    board = ProgressBoard()
    board.start(_ctx(), DOCUMENT)

    worker = threading.Thread(target=board.report, args=(_ctx(), DOCUMENT, 80))
    worker.start()
    worker.join()

    assert board.read(_tenant(), DOCUMENT) == TrackState(running=True, percent=80)


def test_read_refuses_an_unverified_context() -> None:
    with pytest.raises(TypeError):
        ProgressBoard().read(ORG, DOCUMENT)  # type: ignore[arg-type]
