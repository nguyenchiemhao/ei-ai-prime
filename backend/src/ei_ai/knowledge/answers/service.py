"""Grounded answers in two phases (EA-37): ``prepare_answer`` reads in the tenant transaction,
``stream_answer`` talks to the model after that transaction is closed and touches no DB session.

Strict mode (R5): no relevant passage gives "not found" without a model call; a model reply of
``NOT_FOUND`` or an answer without a valid citation gives "not found" too. Citations are checked
while streaming (R21). Logs hold ids, counts, codes and timings only, never text (D52).
"""

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Literal

from ei_ai.db.tenant import TenantExecutor
from ei_ai.knowledge.answers.chat_model import AnswerModel
from ei_ai.knowledge.answers.citations import CitationFilter, cited_numbers
from ei_ai.knowledge.answers.events import (
    AnswerDelta,
    AnswerDone,
    AnswerEvent,
    AnswerFailed,
    PassageInfo,
    PassagesFound,
)
from ei_ai.knowledge.answers.prompt import build_messages, new_delimiter
from ei_ai.knowledge.answers.sources import source_section, source_title
from ei_ai.knowledge.answers.strict import SentinelDetector, has_relevant_passage
from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
from ei_ai.knowledge.retrieval.principal import AnonymousPrincipal, RetrievalPrincipal
from ei_ai.knowledge.retrieval.reranker import Reranker
from ei_ai.knowledge.retrieval.scope import KnowledgeScope
from ei_ai.knowledge.retrieval.service import Passage, retrieve
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.results import ChatCompleted, TextDelta
from ei_ai.tenancy.context import TenantContext
from ei_ai.vn_text.language import Language, detect_language

logger = logging.getLogger("ei_ai.knowledge.answers")

ANSWER_K = 3
TEMPERATURE = 0.1


@dataclass(frozen=True)
class PreparedAnswer:
    """Everything the stream needs; no DB handle."""

    org_id: uuid.UUID
    question: str
    language: Language
    passages: tuple[Passage, ...]
    principal_kind: Literal["anonymous", "authenticated"]
    simulated: bool


async def prepare_answer(
    session: TenantExecutor,
    tenant: TenantContext,
    question: str,
    principal: RetrievalPrincipal,
    scope: KnowledgeScope,
    *,
    embedder: ChunkEmbedder,
    ctx: ModelCallContext,
    reranker: Reranker | None = None,
) -> PreparedAnswer:
    """The top ``ANSWER_K`` passages the principal may read, with the question's language.

    ``ValueError`` (bad question) and ``ModelError`` (embedder) pass through.
    """
    result = await retrieve(
        session,
        tenant,
        question,
        principal,
        scope,
        embedder=embedder,
        ctx=ctx,
        reranker=reranker,
        k=ANSWER_K,
    )
    stripped = question.strip()
    anonymous = isinstance(principal, AnonymousPrincipal)
    return PreparedAnswer(
        org_id=tenant.org_id,
        question=stripped,
        language=detect_language(stripped),
        passages=result.passages,
        principal_kind="anonymous" if anonymous else "authenticated",
        simulated=principal.simulated,
    )


def _info(number: int, passage: Passage) -> PassageInfo:
    score = passage.rerank_score if passage.rerank_score is not None else passage.retrieval_score
    return PassageInfo(
        number=number,
        title=source_title(passage.document_name),
        section=source_section(passage.heading_path),
        page=passage.page,
        score=score,
    )


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


@dataclass
class _Trace:
    """The facts of one ask for its single ``answer_done`` log line."""

    outcome: str = "cancelled"
    rule: str = "none"
    cited: int = 0
    removed: int = 0
    finish: str | None = None
    first_token_ms: int | None = None


async def stream_answer(
    prepared: PreparedAnswer,
    *,
    model: AnswerModel,
    ctx: ModelCallContext,
    strict: bool = True,
) -> AsyncGenerator[AnswerEvent]:
    """``PassagesFound``, then deltas, then ``AnswerDone`` or ``AnswerFailed``.

    Cancellation (``CancelledError``, ``GeneratorExit``) closes the model stream, is logged as
    ``outcome=cancelled`` and re-raised.
    """
    started = time.perf_counter()
    trace = _Trace()
    passages = prepared.passages
    try:
        yield PassagesFound(
            prepared.language, tuple(_info(n, p) for n, p in enumerate(passages, start=1))
        )
        if strict and not has_relevant_passage(passages):
            trace.outcome, trace.rule = "not_found", "gate"
            yield AnswerDone("not_found", "", ())
            return

        messages = build_messages(
            prepared.question, passages, prepared.language, strict=strict, delimiter=new_delimiter()
        )
        sentinel = SentinelDetector()
        citations = CitationFilter(len(passages))
        shown: list[str] = []
        try:
            async with aclosing(model.stream(ctx, messages, temperature=TEMPERATURE)) as events:
                async for event in events:
                    if isinstance(event, TextDelta):
                        text = citations.feed(sentinel.feed(event.text))
                        if sentinel.matched:
                            break
                        if text:
                            if trace.first_token_ms is None:
                                trace.first_token_ms = _ms(started)
                            shown.append(text)
                            yield AnswerDelta(text)
                    elif isinstance(event, ChatCompleted):
                        trace.finish = event.finish_reason
            # The final flush and the outcome stay inside the error handling: a failure here is an
            # ``answer_failed`` error, not a cancelled ask.
            if not sentinel.matched:
                tail = citations.feed(sentinel.flush()) + citations.flush()
                if tail:
                    shown.append(tail)
                    yield AnswerDelta(tail)
            trace.removed = citations.removed
            answer = "".join(shown).strip()
            numbers = cited_numbers(answer, len(passages))
            trace.cited = len(numbers)
            if sentinel.matched:
                trace.outcome, trace.rule = "not_found", "sentinel"
            elif not answer:
                trace.outcome, trace.rule = "not_found", "empty"
            elif strict and not numbers:
                trace.outcome, trace.rule = "not_found", "uncited"
            else:
                trace.outcome, trace.rule = "answered", "cited" if strict else "relaxed"
        except ModelError as error:
            trace.outcome, trace.rule = "error", str(error.code)
            yield AnswerFailed("model_unavailable")
            return
        except Exception as error:
            trace.outcome, trace.rule = "error", type(error).__name__
            yield AnswerFailed("answer_failed")
            return

        # The outcome is set before the final yield, so a client closing the stream right after
        # ``done`` is logged with it, not as ``cancelled``.
        if trace.outcome == "answered":
            yield AnswerDone("answered", answer, numbers)
        else:
            yield AnswerDone("not_found", "", ())
    finally:
        logger.info(
            "answer_done org_id=%s outcome=%s rule=%s passages=%d cited=%d removed=%d finish=%s"
            " principal=%s simulated=%s first_token_ms=%s elapsed_ms=%d",
            prepared.org_id,
            trace.outcome,
            trace.rule,
            len(passages),
            trace.cited,
            trace.removed,
            trace.finish or "none",
            prepared.principal_kind,
            "yes" if prepared.simulated else "no",
            "none" if trace.first_token_ms is None else trace.first_token_ms,
            _ms(started),
        )
