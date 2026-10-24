"""``stream_answer`` with a scripted model (EA-37: AC2, AC3, AC7; R5, R20-R25, D52)."""

import asyncio
import logging
import uuid
from collections.abc import Sequence

import pytest

from ei_ai.knowledge.answers import prompt
from ei_ai.knowledge.answers.citations import CitationFilter
from ei_ai.knowledge.answers.events import (
    AnswerDelta,
    AnswerDone,
    AnswerEvent,
    AnswerFailed,
    PassageInfo,
    PassagesFound,
)
from ei_ai.knowledge.answers.service import PreparedAnswer, stream_answer
from ei_ai.knowledge.answers.strict import MIN_RELEVANCE
from ei_ai.knowledge.retrieval.service import Passage
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from support.fake_answer_model import FakeAnswerModel

ORG = uuid.UUID("0192a000-0000-7000-8000-00000000000a")
CTX = ModelCallContext(org_id=ORG, actor="platform-operator")
LEAK_SENTINEL = "SENTINEL-EA37-9c1d"


def _passage(
    text: str = "Employees get 3 days of paid leave.",
    *,
    name: str = "Leave Policy 2026.md",
    score: float = 0.6,
    rerank: float | None = None,
    page: int | None = None,
) -> Passage:
    return Passage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        document_name=name,
        page=page,
        heading_path=("§4.1 Personal leave",),
        ordinal=0,
        text=text,
        retrieval_score=score,
        rerank_score=rerank,
    )


def _prepared(
    passages: Sequence[Passage] | None = None, question: str = "Kết hôn được nghỉ mấy ngày?"
) -> PreparedAnswer:
    found = tuple([_passage(), _passage(), _passage()] if passages is None else passages)
    return PreparedAnswer(
        org_id=ORG,
        question=question,
        language="vi",
        passages=found,
        principal_kind="authenticated",
        simulated=True,
    )


async def _run(
    prepared: PreparedAnswer, model: FakeAnswerModel, *, strict: bool = True
) -> list[AnswerEvent]:
    return [e async for e in stream_answer(prepared, model=model, ctx=CTX, strict=strict)]


def _done(events: Sequence[AnswerEvent]) -> AnswerDone:
    last = events[-1]
    assert isinstance(last, AnswerDone)
    return last


async def test_stream_answer_event_order() -> None:
    model = FakeAnswerModel()

    events = await _run(_prepared(), model)

    assert isinstance(events[0], PassagesFound)
    assert events[0].language == "vi"
    assert [type(e) for e in events[1:-1]] == [AnswerDelta] * 3
    assert events[-1] == AnswerDone("answered", "Nghỉ 3 ngày [1].", (1,))
    assert len(model.calls) == 1


async def test_passages_found_lists_title_section_page_and_the_best_score() -> None:
    prepared = _prepared(
        [
            _passage(name="Leave Policy 2026.md", score=0.6, page=2),
            _passage(name="Notes.docx", score=0.5, rerank=0.91),
        ]
    )

    events = await _run(prepared, FakeAnswerModel())

    assert events[0] == PassagesFound(
        "vi",
        (
            PassageInfo(1, "Leave Policy 2026", "§4.1 Personal leave", 2, 0.6),
            PassageInfo(2, "Notes", "§4.1 Personal leave", None, 0.91),
        ),
    )


async def test_invalid_citations_removed_from_stream_and_done() -> None:
    events = await _run(_prepared(), FakeAnswerModel(deltas=["A [", "4] B [2]"]))

    deltas = [e.text for e in events if isinstance(e, AnswerDelta)]
    assert not any("[4]" in text for text in deltas)
    assert "".join(deltas) == "A  B [2]"
    assert _done(events) == AnswerDone("answered", "A  B [2]", (2,))


async def test_below_threshold_is_not_found_without_model_call() -> None:
    model = FakeAnswerModel()
    weak = _passage(score=MIN_RELEVANCE - 0.01)

    events = await _run(_prepared([weak]), model)

    assert [type(e) for e in events] == [PassagesFound, AnswerDone]
    assert _done(events) == AnswerDone("not_found", "", ())
    assert model.calls == []


async def test_no_passages_is_not_found_without_model_call() -> None:
    model = FakeAnswerModel()

    events = await _run(_prepared([]), model)

    assert events[0] == PassagesFound("vi", ())
    assert _done(events) == AnswerDone("not_found", "", ())
    assert model.calls == []


async def test_sentinel_is_not_found_and_never_streamed() -> None:
    events = await _run(_prepared(), FakeAnswerModel(deltas=["NOT_", "FOUND", " (no data)"]))

    assert not any(isinstance(e, AnswerDelta) for e in events)
    assert _done(events) == AnswerDone("not_found", "", ())


async def test_uncited_guess_is_not_found() -> None:
    events = await _run(_prepared(), FakeAnswerModel(deltas=["Chắc là 5 ngày."]))

    assert any(isinstance(e, AnswerDelta) for e in events)  # shown while streaming (R18)
    assert _done(events) == AnswerDone("not_found", "", ())


async def test_relaxed_mode_keeps_uncited_answer() -> None:
    events = await _run(_prepared(), FakeAnswerModel(deltas=["Chắc là 5 ngày."]), strict=False)

    assert _done(events) == AnswerDone("answered", "Chắc là 5 ngày.", ())


async def test_relaxed_mode_asks_the_model_even_without_passages() -> None:
    model = FakeAnswerModel(deltas=["Tài liệu không nói về việc này."])

    events = await _run(_prepared([]), model, strict=False)

    assert len(model.calls) == 1
    assert _done(events).outcome == "answered"


async def test_chat_model_error_yields_error_event() -> None:
    model = FakeAnswerModel(fail=ModelError(ModelErrorCode.MODEL_NOT_FOUND, "qwen", "chat"))

    events = await _run(_prepared(), model)

    assert events[-1] == AnswerFailed("model_unavailable")
    assert not any(isinstance(e, AnswerDone) for e in events)
    assert model.closed


async def test_unexpected_error_yields_answer_failed() -> None:
    model = FakeAnswerModel(deltas=["Nghỉ ", "[1]"], fail=RuntimeError(LEAK_SENTINEL), fail_after=1)

    events = await _run(_prepared(), model)

    assert [type(e) for e in events] == [PassagesFound, AnswerDelta, AnswerFailed]
    assert events[-1] == AnswerFailed("answer_failed")


async def test_cancel_closes_model_stream_and_logs_cancelled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ei_ai")
    model = FakeAnswerModel(deltas=["Nghỉ ", "3 ngày ", "[1]"])
    stream = stream_answer(_prepared(), model=model, ctx=CTX)

    assert isinstance(await anext(stream), PassagesFound)
    assert isinstance(await anext(stream), AnswerDelta)
    await stream.aclose()

    assert model.closed
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("answer_done")]
    assert len(lines) == 1
    assert "outcome=cancelled" in lines[0]


async def test_task_cancellation_is_reraised_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ei_ai")
    model = FakeAnswerModel(gate=asyncio.Event())

    async def consume() -> None:
        async for _ in stream_answer(_prepared(), model=model, ctx=CTX):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert model.closed
    assert any("outcome=cancelled" in r.getMessage() for r in caplog.records)


async def test_answer_logs_hold_no_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="ei_ai")
    prepared = _prepared(
        [_passage(f"Passage with {LEAK_SENTINEL}", name=f"Secret {LEAK_SENTINEL} policy.md")],
        question=f"What about {LEAK_SENTINEL}?",
    )

    await _run(prepared, FakeAnswerModel(deltas=[f"Answer {LEAK_SENTINEL} ", "[1]"]))
    await _run(
        prepared, FakeAnswerModel(deltas=["x"], fail=RuntimeError(LEAK_SENTINEL), fail_after=0)
    )

    records = [r for r in caplog.records if r.name.startswith("ei_ai")]
    assert records
    assert not any(LEAK_SENTINEL in r.getMessage() or "Secret" in r.getMessage() for r in records)
    lines = [r.getMessage() for r in records if r.getMessage().startswith("answer_done")]
    assert len(lines) == 2
    for key in ("outcome=", "rule=", "passages=", "cited=", "removed=", "finish="):
        assert key in lines[0]
    assert "outcome=answered" in lines[0]
    assert "finish=stop" in lines[0]
    assert "outcome=error rule=RuntimeError" in lines[1]


async def test_each_ask_uses_a_fresh_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    issued: list[str] = []
    real = prompt.new_delimiter

    def counting() -> str:
        issued.append(real())
        return issued[-1]

    monkeypatch.setattr("ei_ai.knowledge.answers.service.new_delimiter", counting)
    first, second = FakeAnswerModel(), FakeAnswerModel()

    await _run(_prepared(), first)
    await _run(_prepared(), second)

    assert len(issued) == 2
    assert issued[0] != issued[1]
    for delimiter, model in zip(issued, (first, second), strict=True):
        system = model.calls[0][0].content
        assert f"<<DATA-{delimiter}>>" in system
        assert f"<<END-DATA-{delimiter}>>" in model.calls[0][1].content


async def test_failure_after_the_model_stream_yields_answer_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ei_ai")

    def broken_flush(self: CitationFilter) -> str:
        raise RuntimeError(LEAK_SENTINEL)

    monkeypatch.setattr(CitationFilter, "flush", broken_flush)

    events = await _run(_prepared(), FakeAnswerModel())

    assert events[-1] == AnswerFailed("answer_failed")
    assert not any(isinstance(e, AnswerDone) for e in events)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("answer_done")]
    assert len(lines) == 1
    assert "outcome=error rule=RuntimeError" in lines[0]
    assert LEAK_SENTINEL not in lines[0]


async def test_closing_the_stream_right_after_done_is_logged_answered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ei_ai")
    stream = stream_answer(_prepared(), model=FakeAnswerModel(), ctx=CTX)

    async for event in stream:
        if isinstance(event, AnswerDone):
            break
    await stream.aclose()

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("answer_done")]
    assert len(lines) == 1
    assert "outcome=answered" in lines[0]
