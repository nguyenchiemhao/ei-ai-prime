"""``ModelGateway``: chat (streaming and not), embedding and rerank through OpenAI-compatible
endpoints, for exactly the pinned catalog row (D4, D18, F8).

Call flow, in this order; a failing step raises ``ModelError`` (from None) and nothing after it
runs:

1. resolve the requested ref once in the caller's Organization (MODEL_NOT_FOUND, MODEL_RETIRED);
2. a cloud row with the Organization's switch off: audit, then CLOUD_DISABLED (no network);
3. unknown or unconfigured provider: MODEL_UNAVAILABLE (local) or CLOUD_NOT_CONFIGURED (cloud);
4. at most two attempts (``retry``): a local server must list the pinned served id, a cloud
   answer must come from the pinned snapshot (PINNED_VERSION_UNAVAILABLE, not retried);
5. exactly one ``ModelCallRecord`` to the observers.

There is no code path that picks another catalog row: never a newer build, never a local→cloud
fallback.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Iterator, Sequence
from contextlib import aclosing, contextmanager
from dataclasses import dataclass, field

from ei_ai.model_gateway.catalog import CatalogEntry, CatalogReader
from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.manifest import Kind
from ei_ai.model_gateway.observer import ModelCallObserver, ModelCallRecord, notify
from ei_ai.model_gateway.pinning import served_model_id, verify_answered_by, verify_listed
from ei_ai.model_gateway.providers import Provider, ProviderRegistry
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import (
    ChatCompleted,
    ChatMessage,
    ChatResult,
    EmbeddingResult,
    RerankResult,
    StreamEvent,
    TextDelta,
    Usage,
)
from ei_ai.model_gateway.retry import should_retry
from ei_ai.model_gateway.transport import (
    ProviderNotConfigured,
    ProviderSession,
    Transport,
    UpstreamError,
)

__all__ = [
    "ChatCompleted",
    "ChatMessage",
    "ChatResult",
    "EmbeddingResult",
    "ModelGateway",
    "RerankResult",
    "StreamEvent",
    "TextDelta",
    "Usage",
]


@dataclass
class _Call:
    """The state of one call, turned into its ``ModelCallRecord`` at the end."""

    ctx: ModelCallContext
    ref: str
    kind: Kind
    started: float
    entry: CatalogEntry | None = None
    attempts: int = 0
    usage: Usage = field(default_factory=lambda: Usage(0, 0))
    first_token: float | None = None
    outcome: str = "cancelled"


@dataclass(frozen=True)
class _Target:
    entry: CatalogEntry
    provider: Provider
    session: ProviderSession
    served_id: str


def _wire(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


class ModelGateway:
    def __init__(
        self,
        *,
        catalog: CatalogReader,
        providers: ProviderRegistry,
        transport: Transport,
        observers: Iterable[ModelCallObserver] = (),
        retry_delay_seconds: float = 0.25,
        default_max_tokens: int = 512,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._catalog = catalog
        self._providers = providers
        self._transport = transport
        self._observers = tuple(observers)
        self._retry_delay = retry_delay_seconds
        self._max_tokens = default_max_tokens
        self._sleep = sleep
        self._clock = clock

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def stream_chat(
        self,
        ctx: ModelCallContext,
        ref: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        """Text deltas as they arrive, then one ``ChatCompleted`` with the usage."""
        call = _Call(ctx, str(ref), "chat", self._clock())
        with self._recorded(call):
            target = await self._open(call, ref)
            finish_reason = None
            while True:
                call.attempts += 1
                yielded = False
                try:
                    await self._check_listed(target)
                    pieces = target.session.stream_chat(
                        model=target.served_id,
                        messages=_wire(messages),
                        max_tokens=max_tokens or self._max_tokens,
                        temperature=temperature,
                    )
                    async with aclosing(pieces):
                        async for piece in pieces:
                            verify_answered_by(target.entry, target.provider, piece.model)
                            if piece.prompt_tokens is not None:
                                call.usage = Usage(
                                    piece.prompt_tokens, piece.completion_tokens or 0
                                )
                            finish_reason = piece.finish_reason or finish_reason
                            if piece.text:
                                if call.first_token is None:
                                    call.first_token = self._clock()
                                yielded = True
                                yield TextDelta(piece.text)
                    break
                except UpstreamError as error:
                    if not should_retry(error, call.attempts, yielded=yielded):
                        raise self._unavailable(call) from None
                await self._sleep(self._retry_delay)
            call.outcome = "ok"
            yield ChatCompleted(
                str(ref), target.entry.digest, call.usage, finish_reason, call.attempts
            )

    async def chat(
        self,
        ctx: ModelCallContext,
        ref: ModelRef,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """One complete answer."""

        async def request(call: _Call, target: _Target) -> ChatResult:
            reply = await target.session.chat(
                model=target.served_id,
                messages=_wire(messages),
                max_tokens=max_tokens or self._max_tokens,
                temperature=temperature,
            )
            verify_answered_by(target.entry, target.provider, reply.model)
            call.usage = Usage(reply.prompt_tokens, reply.completion_tokens)
            return ChatResult(reply.text, str(ref), target.entry.digest, call.usage, call.attempts)

        return await self._unary(ctx, ref, "chat", request)

    async def embed(
        self, ctx: ModelCallContext, ref: ModelRef, inputs: Sequence[str]
    ) -> EmbeddingResult:
        """One vector per input, in input order."""

        async def request(call: _Call, target: _Target) -> EmbeddingResult:
            reply = await target.session.embed(model=target.served_id, inputs=inputs)
            verify_answered_by(target.entry, target.provider, reply.model)
            call.usage = Usage(reply.prompt_tokens, 0)
            return EmbeddingResult(reply.vectors, str(ref), target.entry.digest, call.usage)

        return await self._unary(ctx, ref, "embedding", request)

    async def rerank(
        self,
        ctx: ModelCallContext,
        ref: ModelRef,
        query: str,
        documents: Sequence[str],
        top_n: int | None = None,
    ) -> RerankResult:
        """(document index, relevance score) pairs."""

        async def request(call: _Call, target: _Target) -> RerankResult:
            results = await target.session.rerank(
                model=target.served_id, query=query, documents=documents, top_n=top_n
            )
            return RerankResult(results, str(ref), target.entry.digest)

        return await self._unary(ctx, ref, "rerank", request)

    async def _unary[T](
        self,
        ctx: ModelCallContext,
        ref: ModelRef,
        kind: Kind,
        request: Callable[[_Call, _Target], Awaitable[T]],
    ) -> T:
        call = _Call(ctx, str(ref), kind, self._clock())
        with self._recorded(call):
            target = await self._open(call, ref)
            while True:
                call.attempts += 1
                try:
                    await self._check_listed(target)
                    result = await request(call, target)
                    break
                except UpstreamError as error:
                    if not should_retry(error, call.attempts):
                        raise self._unavailable(call) from None
                await self._sleep(self._retry_delay)
            call.outcome = "ok"
            return result

    @contextmanager
    def _recorded(self, call: _Call) -> Iterator[None]:
        """Set the outcome of a failed call and emit its one record, however the call ends."""
        try:
            yield
        except ModelError as error:
            call.outcome = error.code.value
            raise
        except Exception:
            call.outcome = "error"
            raise
        finally:
            self._finish(call)

    async def _open(self, call: _Call, ref: ModelRef) -> _Target:
        """Steps 1-3: the pinned row, the cloud switch and a session; no model request yet."""
        resolved = await self._catalog.resolve(call.ctx, ref, call.kind)
        entry = call.entry = resolved.entry
        if entry.deployment == "cloud" and not resolved.cloud_allowed:
            await self._catalog.record_cloud_block(call.ctx, entry)
            raise ModelError(ModelErrorCode.CLOUD_DISABLED, call.ref, call.kind)
        provider = self._providers.get(entry.provider)
        if provider is None or provider.deployment != entry.deployment:
            raise self._unavailable(call)
        try:
            session = self._transport.session(provider, call.ctx.org_id)
        except ProviderNotConfigured:
            if provider.deployment == "cloud":
                code = ModelErrorCode.CLOUD_NOT_CONFIGURED
                raise ModelError(code, call.ref, call.kind) from None
            raise self._unavailable(call) from None
        return _Target(entry, provider, session, served_model_id(entry, provider))

    async def _check_listed(self, target: _Target) -> None:
        if target.provider.served_id_rule == "llama.cpp":
            listed = await target.session.served_ids()
            verify_listed(target.entry, target.served_id, listed)

    def _unavailable(self, call: _Call) -> ModelError:
        return ModelError(ModelErrorCode.MODEL_UNAVAILABLE, call.ref, call.kind)

    def _finish(self, call: _Call) -> None:
        now = self._clock()
        entry = call.entry
        record = ModelCallRecord(
            org_id=call.ctx.org_id,
            actor=call.ctx.actor,
            assistant_id=call.ctx.assistant_id,
            channel_id=call.ctx.channel_id,
            kind=call.kind,
            model_ref=call.ref,
            digest=None if entry is None else entry.digest,
            deployment=None if entry is None else entry.deployment,
            provider=None if entry is None else entry.provider,
            outcome=call.outcome,
            attempts=call.attempts,
            prompt_tokens=call.usage.prompt_tokens,
            completion_tokens=call.usage.completion_tokens,
            latency_ms=round((now - call.started) * 1000),
            first_token_ms=(
                None
                if call.first_token is None
                else round((call.first_token - call.started) * 1000)
            ),
        )
        notify(self._observers, record)
