"""The trace/usage hook (EA-24, plan §3 #9, attacks 25, 26): exactly one record per call, on
success and on every failure; an observer that fails never changes the result."""

import logging
import uuid
from collections.abc import Callable

import pytest

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.errors import ModelError
from ei_ai.model_gateway.gateway import ChatMessage, ModelGateway
from ei_ai.model_gateway.observer import LoggingObserver, ModelCallRecord
from ei_ai.model_gateway.refs import ModelRef
from model_gateway.fakes import CLOUD, CTX, LOCAL, ORG_A, QWEN_SERVED, Collector, FakeCatalog
from support.fake_model_server import FakeModelServer, Reply

MESSAGES = [ChatMessage("user", "hi")]
MakeGateway = Callable[..., ModelGateway]
ASSISTANT = uuid.UUID("0192a000-0000-7000-8000-0000000000aa")
CHANNEL = uuid.UUID("0192a000-0000-7000-8000-0000000000cc")


class Exploding:
    def record(self, record: ModelCallRecord) -> None:
        raise RuntimeError("observer is broken")


async def test_success_record_has_the_call_metadata(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    collector = Collector()
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server, observers=[collector])
    ctx = ModelCallContext(ORG_A, "user:42", assistant_id=ASSISTANT, channel_id=CHANNEL)

    [e async for e in gateway.stream_chat(ctx, LOCAL.ref, MESSAGES)]

    [record] = collector.records
    assert (record.org_id, record.actor, record.assistant_id, record.channel_id) == (
        ORG_A,
        "user:42",
        ASSISTANT,
        CHANNEL,
    )
    assert (record.kind, record.model_ref, record.digest) == (
        "chat",
        "qwen3-4b-instruct-2507@2026.10",
        LOCAL.digest,
    )
    assert (record.deployment, record.provider, record.outcome, record.attempts) == (
        "local",
        "local-chat",
        "ok",
        1,
    )
    assert (record.prompt_tokens, record.completion_tokens) == (7, 2)
    assert record.latency_ms >= 0
    assert record.first_token_ms is not None
    assert 0 <= record.first_token_ms <= record.latency_ms


@pytest.mark.parametrize(
    ("ref", "listed", "replies", "expected"),
    [
        (LOCAL.ref, [QWEN_SERVED], [], "ok"),
        (ModelRef("missing", "v1"), [QWEN_SERVED], [], "MODEL_NOT_FOUND"),
        (LOCAL.ref, ["x@sha256-000000000000"], [], "PINNED_VERSION_UNAVAILABLE"),
        (LOCAL.ref, [QWEN_SERVED], [Reply(status=500)] * 2, "MODEL_UNAVAILABLE"),
        (CLOUD.ref, [QWEN_SERVED], [], "CLOUD_DISABLED"),
    ],
)
@pytest.mark.parametrize("streaming", [True, False])
async def test_every_outcome_emits_exactly_one_record(
    local_server: FakeModelServer,
    make_gateway: MakeGateway,
    ref: ModelRef,
    listed: list[str],
    replies: list[Reply],
    expected: str,
    streaming: bool,
) -> None:
    local_server.listed_ids = listed
    local_server.replies.extend(replies)
    collector = Collector()
    gateway = make_gateway(FakeCatalog([LOCAL, CLOUD]), local=local_server, observers=[collector])

    try:
        if streaming:
            [e async for e in gateway.stream_chat(CTX, ref, MESSAGES)]
        else:
            await gateway.chat(CTX, ref, MESSAGES)
    except ModelError:
        pass

    assert [record.outcome for record in collector.records] == [expected]


async def test_a_stream_closed_early_emits_one_cancelled_record(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    collector = Collector()
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server, observers=[collector])

    stream = gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)
    await anext(stream)
    await stream.aclose()

    assert [record.outcome for record in collector.records] == ["cancelled"]


async def test_observer_failure_does_not_change_result(
    local_server: FakeModelServer,
    make_gateway: MakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    collector = Collector()
    gateway = make_gateway(
        FakeCatalog([LOCAL]), local=local_server, observers=[Exploding(), collector]
    )

    with caplog.at_level(logging.WARNING, logger="ei_ai.model_gateway"):
        result = await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert result.text == "Xin chào"
    assert len(collector.records) == 1
    assert [r.getMessage() for r in caplog.records] == ["observer failed (Exploding)"]
    assert "observer is broken" not in caplog.text


async def test_logging_observer_writes_one_metadata_line(
    local_server: FakeModelServer,
    make_gateway: MakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server, observers=[LoggingObserver()])

    with caplog.at_level(logging.INFO, logger="ei_ai.model_gateway"):
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    [line] = [r for r in caplog.records if r.name == "ei_ai.model_gateway"]
    assert line.levelno == logging.INFO
    assert line.getMessage() == "model call"
    assert line.__dict__["outcome"] == "ok"
    assert line.__dict__["model_ref"] == "qwen3-4b-instruct-2507@2026.10"
    assert line.__dict__["org_id"] == str(ORG_A)
    for name in ("deployment", "provider", "attempts", "latency_ms", "first_token_ms"):
        assert name in line.__dict__


async def test_logging_observer_warns_on_failure(
    local_server: FakeModelServer,
    make_gateway: MakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    local_server.listed_ids = ["x@sha256-000000000000"]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server, observers=[LoggingObserver()])

    with caplog.at_level(logging.INFO, logger="ei_ai.model_gateway"), pytest.raises(ModelError):
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    [line] = [r for r in caplog.records if r.name == "ei_ai.model_gateway"]
    assert line.levelno == logging.WARNING
    assert line.__dict__["outcome"] == "PINNED_VERSION_UNAVAILABLE"
