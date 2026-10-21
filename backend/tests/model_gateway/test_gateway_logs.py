"""Masked logs (EA-24 NFR, F13, D52, attack 23): a sentinel placed in every prompt, input,
query, document, API key and upstream error body never appears in a log record, an exception
(message, repr, cause or context) or an observer record. Logging runs at DEBUG for every logger,
the SDK and HTTP client included."""

import logging
from collections.abc import Awaitable, Callable

import pytest

from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.gateway import ChatMessage, ModelGateway
from ei_ai.model_gateway.observer import LoggingObserver
from model_gateway.fakes import (
    CLOUD,
    CTX,
    EMBED,
    EMBED_SERVED,
    LOCAL,
    ORG_A,
    QWEN_SERVED,
    RERANK,
    RERANK_SERVED,
    Collector,
    FakeCatalog,
    Keys,
)
from support.fake_model_server import FakeModelServer, Reply
from support.forward_proxy import ForwardProxy

SENTINEL = "SENTINEL-7f3a9c"
MESSAGES = [ChatMessage("system", f"secret {SENTINEL}"), ChatMessage("user", f"q {SENTINEL}")]
MakeGateway = Callable[..., ModelGateway]
Call = Callable[[ModelGateway], Awaitable[object]]


async def _stream(gateway: ModelGateway) -> object:
    return [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]


async def _chat(gateway: ModelGateway) -> object:
    return await gateway.chat(CTX, LOCAL.ref, MESSAGES)


async def _cloud(gateway: ModelGateway) -> object:
    return await gateway.chat(CTX, CLOUD.ref, MESSAGES)


async def _embed(gateway: ModelGateway) -> object:
    return await gateway.embed(CTX, EMBED.ref, [f"input {SENTINEL}"])


async def _rerank(gateway: ModelGateway) -> object:
    return await gateway.rerank(CTX, RERANK.ref, f"query {SENTINEL}", [f"doc {SENTINEL}"])


def _chain(error: BaseException | None) -> list[BaseException]:
    seen: list[BaseException] = []
    while error is not None and error not in seen:
        seen.append(error)
        error = error.__cause__ or error.__context__
    return seen


@pytest.mark.parametrize(
    ("call", "replies", "cloud_allowed"),
    [
        (_stream, [], False),
        (_chat, [], False),
        (_stream, [Reply(status=500, body=f"echo {SENTINEL}")] * 2, False),
        (_chat, [Reply(status=400, body=f"echo {SENTINEL}")], False),
        (_chat, [Reply(delay=1)] * 2, False),
        (_stream, [Reply(drop_after=1, deltas=(f"a {SENTINEL}", "b"))], False),
        (_cloud, [], False),
        (_cloud, [Reply(status=500, body=f"echo {SENTINEL}")] * 2, True),
        (_embed, [], False),
        (_rerank, [], False),
        (_rerank, [Reply(status=503, body=f"echo {SENTINEL}")] * 2, False),
    ],
    ids=[
        "stream-ok",
        "chat-ok",
        "stream-5xx",
        "chat-4xx",
        "chat-timeout",
        "stream-drop",
        "cloud-blocked",
        "cloud-5xx",
        "embed-ok",
        "rerank-ok",
        "rerank-5xx",
    ],
)
async def test_no_sentinel_in_logs_errors_or_records(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
    caplog: pytest.LogCaptureFixture,
    call: Call,
    replies: list[Reply],
    cloud_allowed: bool,
) -> None:
    local_server.listed_ids = [QWEN_SERVED, EMBED_SERVED, RERANK_SERVED]
    local_server.replies.extend(replies)
    cloud_server.replies.extend(replies)
    collector = Collector()
    gateway = make_gateway(
        FakeCatalog([LOCAL, CLOUD, EMBED, RERANK], cloud_allowed=cloud_allowed),
        local=local_server,
        cloud=cloud_server,
        proxy=proxy,
        keys=Keys({(ORG_A, "openai"): f"sk-{SENTINEL}"}),
        observers=[LoggingObserver(), collector],
        read_timeout=0.2,
    )
    caplog.set_level(logging.DEBUG)
    raised: BaseException | None = None

    try:
        result = await call(gateway)
    except ModelError as error:
        raised = error
        result = None

    texts = [caplog.text, repr(collector.records)]
    texts += [repr(vars(record)) for record in caplog.records]
    texts += [f"{type(e).__name__} {e} {e!r} {e.args!r}" for e in _chain(raised)]
    assert [text[:2000] for text in texts if SENTINEL in text] == []
    assert len(collector.records) == 1
    if raised is None:
        assert result is not None
