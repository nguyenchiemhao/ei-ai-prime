"""Exactly one retry on 5xx, timeout or connection error, then MODEL_UNAVAILABLE (EA-24 AC3,
attacks 12-14). The fake server counts the requests; the SDK's own retries are off."""

from collections.abc import Callable

import pytest

from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ChatCompleted, ChatMessage, ModelGateway, TextDelta
from model_gateway.fakes import CTX, LOCAL, QWEN_SERVED, Collector, FakeCatalog
from support.fake_model_server import FakeModelServer, Reply, unused_loopback_url

MESSAGES = [ChatMessage("user", "hi")]
COMPLETIONS = "/v1/chat/completions"
MakeGateway = Callable[..., ModelGateway]


def _gateway(make: MakeGateway, server: FakeModelServer, **kwargs: object) -> ModelGateway:
    server.listed_ids = [QWEN_SERVED]
    return make(FakeCatalog([LOCAL]), local=server, **kwargs)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_two_5xx_make_exactly_two_requests_then_model_unavailable(
    local_server: FakeModelServer, make_gateway: MakeGateway, status: int
) -> None:
    collector = Collector()
    gateway = _gateway(make_gateway, local_server, observers=[collector])
    local_server.replies.extend([Reply(status=status), Reply(status=status), Reply()])

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert str(error.value) == "model qwen3-4b-instruct-2507@2026.10 is unavailable"
    assert local_server.count(COMPLETIONS) == 2
    assert collector.records[0].attempts == 2


async def test_5xx_then_ok_succeeds_with_two_attempts(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.replies.extend([Reply(status=500), Reply()])

    result = await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert result.text == "Xin chào"
    assert result.attempts == 2
    assert local_server.count(COMPLETIONS) == 2


async def test_stream_5xx_then_ok_succeeds_with_two_attempts(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.replies.extend([Reply(status=503), Reply()])

    events = [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]

    assert events[:-1] == [TextDelta("Xin"), TextDelta(" chào")]
    assert isinstance(events[-1], ChatCompleted) and events[-1].attempts == 2


@pytest.mark.parametrize("streaming", [True, False])
async def test_two_timeouts_make_exactly_two_requests_then_model_unavailable(
    local_server: FakeModelServer, make_gateway: MakeGateway, streaming: bool
) -> None:
    gateway = _gateway(make_gateway, local_server, read_timeout=0.2)
    local_server.replies.extend([Reply(delay=1), Reply(delay=1), Reply()])

    with pytest.raises(ModelError) as error:
        if streaming:
            [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]
        else:
            await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert local_server.count(COMPLETIONS) == 2


async def test_connection_refused_is_retried_once(make_gateway: MakeGateway) -> None:
    collector = Collector()
    unreachable = FakeModelServer(base_url=unused_loopback_url())
    gateway = make_gateway(FakeCatalog([LOCAL]), local=unreachable, observers=[collector])

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert collector.records[0].attempts == 2


@pytest.mark.parametrize("status", [400, 401, 404, 422, 429])
async def test_4xx_and_429_are_not_retried(
    local_server: FakeModelServer, make_gateway: MakeGateway, status: int
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.replies.extend([Reply(status=status), Reply()])

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert local_server.count(COMPLETIONS) == 1


async def test_failure_after_first_delta_is_not_retried(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.replies.extend([Reply(drop_after=1), Reply()])
    events = []

    with pytest.raises(ModelError) as error:
        async for event in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES):
            events.append(event)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert events == [TextDelta("Xin")]
    assert local_server.count(COMPLETIONS) == 1


async def test_failure_before_first_delta_is_retried(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.replies.extend([Reply(drop_after=0), Reply()])

    events = [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]

    assert events[:-1] == [TextDelta("Xin"), TextDelta(" chào")]
    assert local_server.count(COMPLETIONS) == 2


async def test_models_listing_5xx_counts_as_the_attempt(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.models_replies.extend([Reply(status=500), Reply(status=500)])

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert local_server.paths() == ["/v1/models", "/v1/models"]


async def test_models_listing_5xx_then_ok_completes_on_the_second_attempt(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = _gateway(make_gateway, local_server)
    local_server.models_replies.append(Reply(status=502))

    result = await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert result.attempts == 2
    assert local_server.paths() == ["/v1/models", "/v1/models", COMPLETIONS]


async def test_pinned_version_unavailable_is_not_retried(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)
    local_server.listed_ids = ["other@sha256-000000000000"]

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert local_server.paths() == ["/v1/models"]
