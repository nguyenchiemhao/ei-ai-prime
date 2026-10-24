"""Logging of the api process (EA-37 Q1-1).

Uvicorn's logging config sets up the ``uvicorn.*`` loggers only: the root logger keeps no handler
and level WARNING, so every ``ei_ai.*`` INFO line (the masked ``answer_done`` trace among them)
was dropped. ``configure_app_logging`` gives the ``ei_ai`` logger one stderr handler at INFO.
Messages are passed through as they are: what each logger writes is masked at the call site (D52).
"""

import logging
import sys
from collections.abc import Callable

APP_LOGGER = "ei_ai"
FORMAT = "%(levelname)s:     %(name)s %(message)s"


class _StderrHandler(logging.Handler):
    """Writes to the current ``sys.stderr`` (looked up per record, like ``logging.lastResort``)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def configure_app_logging() -> Callable[[], None]:
    """Send ``ei_ai.*`` records at INFO and above to stderr; returns the undo.

    Idempotent: a second call adds no handler. A level set on the ``ei_ai`` logger beforehand
    is kept (only an unset level becomes INFO) and restored by the undo.
    """
    logger = logging.getLogger(APP_LOGGER)
    previous_level = logger.level
    if previous_level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    added: logging.Handler | None = None
    if not any(isinstance(handler, _StderrHandler) for handler in logger.handlers):
        added = _StderrHandler()
        added.setFormatter(logging.Formatter(FORMAT))
        logger.addHandler(added)

    def restore() -> None:
        if added is not None:
            logger.removeHandler(added)
        logger.setLevel(previous_level)

    return restore
