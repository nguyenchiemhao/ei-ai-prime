"""The status shown to clients, derived from the stored status and the runner (spec R4)."""

from datetime import UTC, datetime, timedelta

import pytest

from ei_ai.knowledge.ingestion.progress import TrackState
from ei_ai.knowledge.ingestion.status import INTERRUPTED_AFTER, ShownStatus, shown_status

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
JUST_NOW = NOW - timedelta(seconds=5)
LONG_AGO = NOW - timedelta(hours=3)


def test_interrupted_after_is_two_minutes() -> None:
    assert timedelta(minutes=2) == INTERRUPTED_AFTER


def test_queued_and_tracked_not_started_is_queued() -> None:
    shown = shown_status("queued", None, LONG_AGO, TrackState(running=False, percent=0), NOW)

    assert shown == ShownStatus(status="queued", progress=None, reason=None)


@pytest.mark.parametrize("percent", [0, 60, 100])
def test_queued_and_running_is_processing_with_progress(percent: int) -> None:
    shown = shown_status("queued", None, LONG_AGO, TrackState(running=True, percent=percent), NOW)

    assert shown == ShownStatus(status="processing", progress=percent, reason=None)


def test_queued_not_tracked_and_old_is_failed_interrupted() -> None:
    shown = shown_status("queued", None, LONG_AGO, None, NOW)

    assert shown == ShownStatus(status="failed", progress=None, reason="interrupted")


def test_queued_not_tracked_and_recent_is_queued() -> None:
    shown = shown_status("queued", None, JUST_NOW, None, NOW)

    assert shown == ShownStatus(status="queued", progress=None, reason=None)


def test_interrupted_at_two_minutes_and_one_second() -> None:
    updated_at = NOW - timedelta(minutes=2, seconds=1)

    assert shown_status("queued", None, updated_at, None, NOW).reason == "interrupted"


def test_not_interrupted_at_one_minute_fifty_nine() -> None:
    updated_at = NOW - timedelta(minutes=1, seconds=59)

    assert shown_status("queued", None, updated_at, None, NOW) == ShownStatus(
        status="queued", progress=None, reason=None
    )


def test_ready_is_ready_without_progress_or_reason() -> None:
    shown = shown_status("ready", None, LONG_AGO, None, NOW)

    assert shown == ShownStatus(status="ready", progress=None, reason=None)


@pytest.mark.parametrize(
    "reason", ["corrupt_file", "password_protected", "no_text", "processing_error"]
)
def test_failed_keeps_its_reason(reason: str) -> None:
    shown = shown_status("failed", reason, LONG_AGO, None, NOW)

    assert shown == ShownStatus(status="failed", progress=None, reason=reason)


def test_not_supported_keeps_its_reason() -> None:
    shown = shown_status("not_supported", "scanned_pdf", LONG_AGO, None, NOW)

    assert shown == ShownStatus(status="not_supported", progress=None, reason="scanned_pdf")


@pytest.mark.parametrize("stored", ["ready", "failed", "not_supported"])
def test_a_final_status_ignores_a_stale_track(stored: str) -> None:
    reason = None if stored == "ready" else "corrupt_file"

    shown = shown_status(stored, reason, LONG_AGO, TrackState(running=True, percent=100), NOW)

    assert shown == ShownStatus(status=stored, progress=None, reason=reason)
