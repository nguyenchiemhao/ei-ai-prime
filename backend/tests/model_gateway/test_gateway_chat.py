"""Chat through the gateway against the fake server (EA-24 AC1, AC2, attacks 6, 10, 21)."""

from collections.abc import Callable

import pytest

from ei_ai.model_gateway.catalog import CatalogEntry
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import (
    ChatCompleted,
    ChatMessage,
    ModelGateway,
    StreamEvent,
    TextDelta,
)
from ei_ai.model_gateway.refs import ModelRef
from model_gateway.fakes import (
    CLOUD,
    CTX,
    LOCAL,
    NEWER,
    QWEN_SERVED,
    FakeCatalog,
)
from support.fake_model_server import FakeModelServer, Reply
from support.forward_proxy import ForwardProxy

MESSAGES = [ChatMessage(role="system", content="Be brief."), ChatMessage("user", "Xin chào")]
MakeGateway = Callable[..., ModelGateway]


async def _stream(gateway: ModelGateway, entry: CatalogEntry) -> list[StreamEvent]:
    return [event async for event in gateway.stream_chat(CTX, entry.ref, MESSAGES)]


async def test_stream_chat_yields_deltas_then_completes_with_usage(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    events = await _stream(gateway, LOCAL)

    assert events[:-1] == [TextDelta("Xin"), TextDelta(" chào")]
    done = events[-1]
    assert isinstance(done, ChatCompleted)
    assert done.model_ref == "qwen3-4b-instruct-2507@2026.10"
    assert done.digest == LOCAL.digest
    assert (done.usage.prompt_tokens, done.usage.completion_tokens) == (7, 2)
    assert done.finish_reason == "stop"
    assert done.attempts == 1


async def test_stream_requests_include_usage_and_pinned_served_id(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    await _stream(gateway, LOCAL)

    assert local_server.paths() == ["/v1/models", "/v1/chat/completions"]
    body = local_server.requests[1].body
    assert body["model"] == QWEN_SERVED
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["max_tokens"] == 512
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Xin chào"},
    ]


async def test_max_tokens_and_temperature_are_passed(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    await gateway.chat(CTX, LOCAL.ref, MESSAGES, max_tokens=16, temperature=0.2)

    body = local_server.requests[1].body
    assert (body["max_tokens"], body["temperature"]) == (16, 0.2)


async def test_chat_returns_text_and_usage(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    result = await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert result.text == "Xin chào"
    assert result.model_ref == "qwen3-4b-instruct-2507@2026.10"
    assert result.digest == LOCAL.digest
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (7, 2)
    assert result.attempts == 1
    assert local_server.requests[1].body["model"] == QWEN_SERVED
    assert "stream" not in local_server.requests[1].body


@pytest.mark.parametrize("streaming", [True, False])
async def test_newer_build_only_fails_pinned_version_unavailable_without_completion_request(
    local_server: FakeModelServer, make_gateway: MakeGateway, streaming: bool
) -> None:
    # The server runs another build of the same model: its alias carries another digest.
    local_server.listed_ids = ["qwen3-4b-instruct-2507@sha256-aaaaaaaaaaaa"]
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    with pytest.raises(ModelError) as error:
        if streaming:
            await _stream(gateway, LOCAL)
        else:
            await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert str(error.value) == "pinned version unavailable: qwen3-4b-instruct-2507@2026.10"
    assert local_server.paths() == ["/v1/models"]


async def test_pinned_newer_row_is_unavailable_on_the_older_server(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL, NEWER]), local=local_server)

    with pytest.raises(ModelError) as error:
        await _stream(gateway, NEWER)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert local_server.count("/v1/chat/completions") == 0


async def test_both_builds_listed_calls_exactly_the_pinned_served_id(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = ["qwen3-4b-instruct-2507@sha256-aaaaaaaaaaaa", QWEN_SERVED]
    gateway = make_gateway(FakeCatalog([LOCAL, NEWER]), local=local_server)

    await gateway.chat(CTX, LOCAL.ref, MESSAGES)
    await gateway.chat(CTX, NEWER.ref, MESSAGES)

    models = [r.body["model"] for r in local_server.requests if r.path == "/v1/chat/completions"]
    assert models == [QWEN_SERVED, "qwen3-4b-instruct-2507@sha256-aaaaaaaaaaaa"]


@pytest.mark.parametrize("streaming", [True, False])
async def test_cloud_response_with_other_model_fails_pinned_version_unavailable(
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
    streaming: bool,
) -> None:
    # The provider silently answers with another snapshot (an alias upgrade).
    cloud_server.replies.append(Reply(model="gpt-4.1-2025-09-01"))
    gateway = make_gateway(
        FakeCatalog([CLOUD], cloud_allowed=True), cloud=cloud_server, proxy=proxy
    )
    deltas: list[StreamEvent] = []

    with pytest.raises(ModelError) as error:
        if streaming:
            async for event in gateway.stream_chat(CTX, CLOUD.ref, MESSAGES):
                deltas.append(event)
        else:
            await gateway.chat(CTX, CLOUD.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert deltas == []
    assert cloud_server.count("/v1/chat/completions") == 1


async def test_cloud_call_with_the_pinned_snapshot_succeeds_without_a_listing(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    gateway = make_gateway(
        FakeCatalog([CLOUD], cloud_allowed=True), cloud=cloud_server, proxy=proxy
    )

    events = await _stream(gateway, CLOUD)

    assert events[:-1] == [TextDelta("Xin"), TextDelta(" chào")]
    done = events[-1]
    assert isinstance(done, ChatCompleted)
    assert done.digest is None
    assert cloud_server.paths() == ["/v1/chat/completions"]
    assert cloud_server.requests[0].body["model"] == "gpt-4.1-2025-04-14"


async def test_unknown_provider_is_model_unavailable_without_network(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
) -> None:
    rogue = CatalogEntry(
        id=LOCAL.id,
        kind="chat",
        model_id="rogue",
        version="v1",
        digest=LOCAL.digest,
        deployment="local",
        provider="attacker-host",
    )
    gateway = make_gateway(
        FakeCatalog([rogue], cloud_allowed=True),
        local=local_server,
        cloud=cloud_server,
        proxy=proxy,
    )

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, rogue.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert local_server.requests == cloud_server.requests == []
    assert proxy.request_lines == []


async def test_local_row_naming_a_cloud_provider_is_model_unavailable(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    # A local row may never be served by a cloud provider (no local→cloud switch, D18).
    mislabelled = CatalogEntry(
        id=LOCAL.id,
        kind="chat",
        model_id="sneaky",
        version="v1",
        digest=LOCAL.digest,
        deployment="local",
        provider="openai",
    )
    gateway = make_gateway(
        FakeCatalog([mislabelled], cloud_allowed=True), cloud=cloud_server, proxy=proxy
    )

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, mislabelled.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert cloud_server.requests == []


async def test_unconfigured_local_provider_is_model_unavailable(make_gateway: MakeGateway) -> None:
    gateway = make_gateway(FakeCatalog([LOCAL]))

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert str(error.value) == "model qwen3-4b-instruct-2507@2026.10 is unavailable"


async def test_unknown_ref_is_model_not_found(make_gateway: MakeGateway) -> None:
    gateway = make_gateway(FakeCatalog([LOCAL]))

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, ModelRef("nope", "v1"), MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_NOT_FOUND


async def test_errors_are_raised_without_a_cause(
    local_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    local_server.replies.extend([Reply(status=500), Reply(status=500)])
    gateway = make_gateway(FakeCatalog([LOCAL]), local=local_server)

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


async def test_cloud_stream_whose_first_chunk_already_has_text_yields_nothing(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    # R1-2 (attack 10): no role-only chunk first, so the other snapshot's very first chunk holds
    # text. The pin check must run before that text is yielded.
    cloud_server.replies.append(Reply(model="gpt-4.1-2025-09-01", role_chunk=False))
    gateway = make_gateway(
        FakeCatalog([CLOUD], cloud_allowed=True), cloud=cloud_server, proxy=proxy
    )
    deltas: list[StreamEvent] = []

    with pytest.raises(ModelError) as error:
        async for event in gateway.stream_chat(CTX, CLOUD.ref, MESSAGES):
            deltas.append(event)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert deltas == []


async def test_cloud_stream_switching_snapshot_mid_way_stops_before_the_switched_text(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    # Every chunk is checked: text of a chunk from another snapshot is never yielded.
    cloud_server.replies.append(Reply(role_chunk=False, later_model="gpt-4.1-2025-09-01"))
    gateway = make_gateway(
        FakeCatalog([CLOUD], cloud_allowed=True), cloud=cloud_server, proxy=proxy
    )
    deltas: list[StreamEvent] = []

    with pytest.raises(ModelError) as error:
        async for event in gateway.stream_chat(CTX, CLOUD.ref, MESSAGES):
            deltas.append(event)

    assert error.value.code is ModelErrorCode.PINNED_VERSION_UNAVAILABLE
    assert deltas == [TextDelta("Xin")]
    assert cloud_server.count("/v1/chat/completions") == 1
