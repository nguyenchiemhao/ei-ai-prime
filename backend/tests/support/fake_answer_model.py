"""Test-only ``AnswerModel``: scripted text deltas, no model, no network (EA-37, R17).

``deltas`` are streamed one by one, then a ``ChatCompleted`` with ``finish_reason``. ``fail`` is
raised before the first delta, or after ``fail_after`` deltas. ``gate`` pauses the stream before
the first delta until it is set; with ``gate_after`` = n it pauses after the n-th delta
instead. ``calls`` records the messages of every call; ``closed`` becomes true
when the stream is closed or finished.

Never imported by ``src``.
"""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, field

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatCompleted, ChatMessage, StreamEvent, TextDelta, Usage


@dataclass
class FakeAnswerModel:
    deltas: Sequence[str] = ("Nghỉ 3 ngày ", "[1]", ".")
    fail: Exception | None = None
    fail_after: int | None = None
    gate: asyncio.Event | None = None
    gate_after: int | None = None
    finish_reason: str | None = "stop"
    ref: ModelRef = ModelRef("qwen3-4b-instruct-2507", "2026.10")
    calls: list[list[ChatMessage]] = field(default_factory=list)
    closed: bool = False

    async def stream(
        self,
        ctx: ModelCallContext,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        self.calls.append(list(messages))
        self.closed = False
        try:
            if self.gate is not None and self.gate_after is None:
                await self.gate.wait()
            if self.fail is not None and self.fail_after is None:
                raise self.fail
            for count, delta in enumerate(self.deltas):
                if self.fail is not None and count == self.fail_after:
                    raise self.fail
                yield TextDelta(delta)
                if self.gate is not None and self.gate_after == count + 1:
                    await self.gate.wait()
            if self.fail is not None and self.fail_after is not None:
                raise self.fail
            yield ChatCompleted(
                model_ref=str(self.ref),
                digest=None,
                usage=Usage(prompt_tokens=0, completion_tokens=0),
                finish_reason=self.finish_reason,
                attempts=1,
            )
        finally:
            self.closed = True
