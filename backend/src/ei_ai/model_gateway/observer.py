"""The trace and usage hook of every gateway call (F10/F11; FND-09 adds the real observers).

Each call ends with exactly one ``ModelCallRecord``, on success and on failure. It holds
metadata only: never a message, an answer, an input, a query, a document, a key or a URL (D52).
"""

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("ei_ai.model_gateway")


@dataclass(frozen=True)
class ModelCallRecord:
    org_id: uuid.UUID
    actor: str
    assistant_id: uuid.UUID | None
    channel_id: uuid.UUID | None
    kind: str
    model_ref: str
    digest: str | None
    deployment: str | None
    provider: str | None
    # "ok", "cancelled" (the caller closed the stream or was cancelled), "error" (a bug) or a
    # ModelErrorCode value.
    outcome: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    first_token_ms: int | None


class ModelCallObserver(Protocol):
    def record(self, record: ModelCallRecord) -> None:
        """Take one record; must not block (queue slow work, EA-26 AC7)."""
        ...


class LoggingObserver:
    """One fixed-field line per call on ``ei_ai.model_gateway`` (WARNING when it failed)."""

    def record(self, record: ModelCallRecord) -> None:
        level = logging.INFO if record.outcome in ("ok", "cancelled") else logging.WARNING
        logger.log(
            level,
            "model call",
            extra={
                "org_id": str(record.org_id),
                "assistant_id": None if record.assistant_id is None else str(record.assistant_id),
                "channel_id": None if record.channel_id is None else str(record.channel_id),
                "kind": record.kind,
                "model_ref": record.model_ref,
                "deployment": record.deployment,
                "provider": record.provider,
                "outcome": record.outcome,
                "attempts": record.attempts,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "latency_ms": record.latency_ms,
                "first_token_ms": record.first_token_ms,
            },
        )


def notify(observers: Iterable[ModelCallObserver], record: ModelCallRecord) -> None:
    """Give the record to every observer; a failing observer is logged by class name only and
    never changes the call's result (EA-26 AC7)."""
    for observer in observers:
        try:
            observer.record(record)
        except Exception:
            logger.warning("observer failed (%s)", type(observer).__name__)
