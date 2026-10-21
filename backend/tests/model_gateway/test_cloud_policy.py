"""The Organization's cloud switch (EA-24 AC5, AC6, D17, attack 4): off means CLOUD_DISABLED,
audited, with no network; on still needs the egress proxy and the Organization's key."""

import inspect
from collections.abc import Callable

import pytest

from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ChatMessage, ModelGateway
from model_gateway.fakes import CLOUD, CTX, LOCAL, ORG_B, Collector, FakeCatalog, Keys
from support.fake_model_server import FakeModelServer
from support.forward_proxy import ForwardProxy

MESSAGES = [ChatMessage("user", "hi")]
MakeGateway = Callable[..., ModelGateway]
PUBLIC_CALLS = ("stream_chat", "chat", "embed", "rerank")


@pytest.mark.parametrize("streaming", [True, False])
async def test_cloud_ref_with_switch_off_is_cloud_disabled_without_network(
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_gateway: MakeGateway,
    streaming: bool,
) -> None:
    catalog = FakeCatalog([LOCAL, CLOUD], cloud_allowed=False)
    collector = Collector()
    gateway = make_gateway(catalog, cloud=cloud_server, proxy=proxy, observers=[collector])

    with pytest.raises(ModelError) as error:
        if streaming:
            [e async for e in gateway.stream_chat(CTX, CLOUD.ref, MESSAGES)]
        else:
            await gateway.chat(CTX, CLOUD.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.CLOUD_DISABLED
    assert str(error.value) == "cloud models are off for this Organization"
    assert catalog.blocks == [(CTX, CLOUD)]
    assert cloud_server.requests == []
    assert proxy.request_lines == []
    assert collector.records[0].outcome == "CLOUD_DISABLED"


async def test_switch_read_from_resolved_org_state(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    catalog = FakeCatalog([CLOUD], cloud_allowed=True)
    gateway = make_gateway(catalog, cloud=cloud_server, proxy=proxy)

    result = await gateway.chat(CTX, CLOUD.ref, MESSAGES)

    assert result.text == "Xin chào"
    assert catalog.blocks == []
    assert len(proxy.request_lines) == 1


def test_gateway_api_has_no_cloud_override_parameter() -> None:
    for name in PUBLIC_CALLS:
        parameters = inspect.signature(getattr(ModelGateway, name)).parameters
        suspicious = [p for p in parameters if "cloud" in p or "fallback" in p or "allow" in p]
        assert suspicious == [], f"{name} takes {suspicious}"
        assert "org_id" not in parameters


async def test_cloud_without_proxy_is_cloud_not_configured_without_network(
    cloud_server: FakeModelServer, make_gateway: MakeGateway
) -> None:
    catalog = FakeCatalog([CLOUD], cloud_allowed=True)
    gateway = make_gateway(catalog, cloud=cloud_server, proxy=None)

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, CLOUD.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.CLOUD_NOT_CONFIGURED
    assert str(error.value) == "cloud model calls are not configured"
    assert cloud_server.requests == []
    assert catalog.blocks == []


async def test_cloud_without_the_org_key_is_cloud_not_configured(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: MakeGateway
) -> None:
    catalog = FakeCatalog([CLOUD], cloud_allowed=True)
    gateway = make_gateway(
        catalog, cloud=cloud_server, proxy=proxy, keys=Keys({(ORG_B, "openai"): "sk-b"})
    )

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, CLOUD.ref, MESSAGES)

    assert error.value.code is ModelErrorCode.CLOUD_NOT_CONFIGURED
    assert cloud_server.requests == []
    assert proxy.request_lines == []
