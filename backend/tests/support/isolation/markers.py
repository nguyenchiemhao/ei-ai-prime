"""Leak detection by marker: the ids and names of the fixture rows of an Organization.

Messages name the location and a count, never the marker values: CI logs are shared (D52).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine

from support.tenants import OrgRows

from .snapshot import snapshot_org


def count_markers(text: str, other: OrgRows) -> int:
    lowered = text.lower()
    return sum(1 for marker in other.markers() if marker.lower() in lowered)


def assert_no_markers(text: str, other: OrgRows, where: str) -> None:
    hits = count_markers(text, other)
    assert hits == 0, f"{where}: {hits} marker(s) of Organization {other.label} found"


TEST_CLIENT_LOGGERS = ("httpx", "httpcore")


async def assert_nothing_copied(
    engine: AsyncEngine, me: OrgRows, other: OrgRows, where: str
) -> None:
    """Read-other-write-mine: after a call as ``me`` that named ``other``'s data, none of it
    may have landed in ``me``'s own rows (a job or route that copies across tenants)."""
    rows = await snapshot_org(engine, me)
    assert_no_markers(repr(rows), other, f"{where}: rows of Organization {me.label}")


@dataclass
class CapturedLogs:
    """The formatted log records (traceback included) captured by ``capture_logs``."""

    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _ListHandler(logging.Handler):
    def __init__(self, captured: CapturedLogs) -> None:
        super().__init__(level=logging.DEBUG)
        self._captured = captured
        self._formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        self._captured.lines.append(self._formatter.format(record))


@contextmanager
def capture_logs() -> Iterator[CapturedLogs]:
    """Collect the log records of the app: everything the ``ei_ai`` loggers emit (down to DEBUG)
    and whatever any other logger, ``uvicorn.error`` included, emits at the root level. The test
    client's own loggers are left out: they print the URL the test itself sent. Levels and
    handlers are restored on exit."""
    captured = CapturedLogs()
    handler = _ListHandler(captured)
    handler.addFilter(lambda record: not record.name.startswith(TEST_CLIENT_LOGGERS))
    app_logger = logging.getLogger("ei_ai")
    root = logging.getLogger()
    previous_level = app_logger.level
    app_logger.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield captured
    finally:
        root.removeHandler(handler)
        app_logger.setLevel(previous_level)
