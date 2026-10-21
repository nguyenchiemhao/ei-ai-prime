"""AC4, the dedicated "no cloud fallback" test (D18, attacks 15, 16): the local model fails, the
Organization allows cloud models and has a cloud row, a key and a proxy, and the gateway still
never calls the cloud."""

from collections.abc import Callable

import pytest

from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ChatMessage, ModelGateway
from model_gateway.fakes import CLOUD, CTX, LOCAL, QWEN_SERVED, Collector, FakeCatalog
from support.fake_model_server import FakeModelServer, Reply
from support.forward_proxy import ForwardProxy

MESSAGES = [ChatMessage("user", "hi")]
MakeGateway = Callable[..., ModelGateway]


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize(
    "failure",
    [Reply(status=500), Reply(status=503), Reply(delay=1)],
    ids=["500", "503", "timeout"],
)
async def test_local_failure_never_calls_cloud(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
    failure: Reply,
    streaming: bool,
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    local_server.replies.extend([failure, failure])
    catalog = FakeCatalog([LOCAL, CLOUD], cloud_allowed=True)
    collector = Collector()
    gateway = make_gateway(
        catalog,
        local=local_server,
        cloud=cloud_server,
        proxy=proxy,
        observers=[collector],
        read_timeout=0.2,
    )

    with pytest.raises(ModelError) as error:
        if streaming:
            [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]
        else:
            await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert error.value.ref == "qwen3-4b-instruct-2507@2026.10"
    assert cloud_server.requests == []
    assert proxy.request_lines == []
    assert catalog.blocks == []
    [record] = collector.records
    assert (record.model_ref, record.deployment, record.provider) == (
        "qwen3-4b-instruct-2507@2026.10",
        "local",
        "local-chat",
    )


async def test_local_pinned_version_missing_never_calls_cloud(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
) -> None:
    local_server.listed_ids = ["qwen3-4b-instruct-2507@sha256-ffffffffffff"]
    gateway = make_gateway(
        FakeCatalog([LOCAL, CLOUD], cloud_allowed=True),
        local=local_server,
        cloud=cloud_server,
        proxy=proxy,
    )

    with pytest.raises(ModelError):
        await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert cloud_server.requests == []
    assert proxy.request_lines == []


@pytest.mark.parametrize("streaming", [True, False])
async def test_gateway_resolves_only_the_requested_ref(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
    streaming: bool,
) -> None:
    local_server.listed_ids = [QWEN_SERVED]
    local_server.replies.extend([Reply(status=500), Reply(status=500)])
    catalog = FakeCatalog([LOCAL, CLOUD], cloud_allowed=True)
    gateway = make_gateway(catalog, local=local_server, cloud=cloud_server, proxy=proxy)

    with pytest.raises(ModelError):
        if streaming:
            [e async for e in gateway.stream_chat(CTX, LOCAL.ref, MESSAGES)]
        else:
            await gateway.chat(CTX, LOCAL.ref, MESSAGES)

    assert catalog.resolves == [(CTX.org_id, "qwen3-4b-instruct-2507@2026.10", "chat")]
