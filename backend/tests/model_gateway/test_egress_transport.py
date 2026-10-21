"""The egress seam (EA-24 AC6, attacks 5, 17-20, 27): every cloud call goes through the explicit
egress proxy, environment proxies are ignored, nothing connects directly, and an Organization's
key is sent only on its own call. Local calls never use the proxy.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

import pytest

from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.gateway import ChatMessage, ModelGateway
from ei_ai.model_gateway.providers import Provider, ProviderRegistry
from ei_ai.model_gateway.transport import (
    LOCAL_API_KEY,
    ProviderNotConfigured,
    Transport,
    UpstreamError,
)
from ei_ai.settings import ModelSettings
from model_gateway.fakes import CLOUD, CTX, Collector, FakeCatalog
from support.fake_model_server import FakeModelServer, Reply
from support.forward_proxy import ForwardProxy

ORG_A = uuid.UUID("0192a000-0000-7000-8000-00000000000a")
ORG_B = uuid.UUID("0192a000-0000-7000-8000-00000000000b")
MESSAGES = [{"role": "user", "content": "hello"}]
ENV_PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


class Keys:
    """Fake BYOK store: one key per (Organization, provider)."""

    def __init__(self, keys: dict[tuple[uuid.UUID, str], str]) -> None:
        self.keys = keys

    def api_key(self, org_id: uuid.UUID, provider: str) -> str | None:
        return self.keys.get((org_id, provider))


KEYS = Keys({(ORG_A, "openai"): "sk-org-a", (ORG_B, "openai"): "sk-org-b"})


def _settings(local: FakeModelServer, proxy: ForwardProxy | None) -> ModelSettings:
    return ModelSettings(
        environment="test",
        local_base_url=local.base_url,
        read_timeout_seconds=2,
        retry_delay_seconds=0,
        egress_proxy_url=None if proxy is None else proxy.url,
    )


def _providers(settings: ModelSettings, cloud: FakeModelServer) -> ProviderRegistry:
    return ProviderRegistry.from_settings(settings, cloud_base_urls={"openai": cloud.base_url})


def _provider(registry: ProviderRegistry, key: str) -> Provider:
    provider = registry.get(key)
    assert provider is not None
    return provider


@pytest.fixture
async def make_transport() -> AsyncIterator[Callable[..., Transport]]:
    made: list[Transport] = []

    def make(settings: ModelSettings, credentials: Keys = KEYS) -> Transport:
        transport = Transport(settings, credentials)
        made.append(transport)
        return transport

    yield make
    for transport in made:
        await transport.aclose()


def test_servers_start_with_no_requests(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    other_proxy: ForwardProxy,
) -> None:
    assert local_server.requests == cloud_server.requests == []
    assert proxy.request_lines == other_proxy.request_lines == []
    assert local_server.base_url.startswith("http://127.0.0.1:")
    assert proxy.url.startswith("http://127.0.0.1:")


async def test_cloud_call_goes_through_proxy(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    openai = _provider(_providers(settings, cloud_server), "openai")

    reply = await transport.session(openai, ORG_A).chat(model="gpt-x", messages=MESSAGES)

    assert reply.text == "Xin chào"
    assert proxy.request_lines == [f"POST {cloud_server.base_url}/chat/completions HTTP/1.1"]
    assert cloud_server.paths() == ["/v1/chat/completions"]
    assert local_server.requests == []


@pytest.mark.parametrize("no_proxy", [None, "*"])
async def test_proxy_env_vars_cannot_bypass_or_redirect(
    no_proxy: str | None,
    monkeypatch: pytest.MonkeyPatch,
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    other_proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    for name in ENV_PROXIES:
        monkeypatch.setenv(name, other_proxy.url)
    if no_proxy is not None:
        monkeypatch.setenv("NO_PROXY", no_proxy)
        monkeypatch.setenv("no_proxy", no_proxy)
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    registry = _providers(settings, cloud_server)

    await transport.session(_provider(registry, "openai"), ORG_A).chat(model="m", messages=MESSAGES)
    await transport.session(_provider(registry, "local-chat"), ORG_A).served_ids()

    assert len(proxy.request_lines) == 1
    assert other_proxy.request_lines == []
    assert cloud_server.count("/v1/chat/completions") == 1
    assert local_server.paths() == ["/v1/models"]


async def test_no_proxy_configured_session_is_refused_without_network(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, None)
    transport = make_transport(settings)
    openai = _provider(_providers(settings, cloud_server), "openai")

    with pytest.raises(ProviderNotConfigured):
        transport.session(openai, ORG_A)

    assert cloud_server.requests == []
    assert proxy.request_lines == []


async def test_missing_cloud_key_is_not_configured_without_network(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, proxy)
    transport = make_transport(settings, Keys({}))
    openai = _provider(_providers(settings, cloud_server), "openai")

    with pytest.raises(ProviderNotConfigured):
        transport.session(openai, ORG_A)

    assert cloud_server.requests == []
    assert proxy.request_lines == []


async def test_proxy_down_never_connects_directly(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    openai = _provider(_providers(settings, cloud_server), "openai")
    proxy.stop()

    with pytest.raises(UpstreamError) as error:
        await transport.session(openai, ORG_A).chat(model="m", messages=MESSAGES)

    assert error.value.retryable is True
    assert cloud_server.requests == []


async def test_local_calls_do_not_use_proxy(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    local = _provider(_providers(settings, cloud_server), "local-chat")

    await transport.session(local, ORG_A).chat(model="m", messages=MESSAGES)

    assert proxy.request_lines == []
    assert local_server.count("/v1/chat/completions") == 1
    assert local_server.requests[0].headers["authorization"] == f"Bearer {LOCAL_API_KEY}"


async def test_org_key_is_sent_only_on_its_own_call(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    openai = _provider(_providers(settings, cloud_server), "openai")

    for org in (ORG_A, ORG_B, ORG_A, ORG_B):
        await transport.session(openai, org).chat(model="m", messages=MESSAGES)

    assert [r.headers["authorization"] for r in cloud_server.requests] == [
        "Bearer sk-org-a",
        "Bearer sk-org-b",
        "Bearer sk-org-a",
        "Bearer sk-org-b",
    ]


async def test_unconfigured_local_provider_is_not_configured(
    local_server: FakeModelServer, make_transport: Callable[..., Transport]
) -> None:
    settings = replace(_settings(local_server, None), local_base_url=None)
    transport = make_transport(settings)
    local = ProviderRegistry.from_settings(settings).get("local-chat")
    assert local is not None

    with pytest.raises(ProviderNotConfigured):
        transport.session(local, ORG_A)


@pytest.mark.parametrize(
    ("status", "retryable"), [(500, True), (502, True), (503, True), (400, False), (429, False)]
)
async def test_sdk_never_retries_and_errors_say_if_a_retry_is_allowed(
    local_server: FakeModelServer,
    make_transport: Callable[..., Transport],
    status: int,
    retryable: bool,
) -> None:
    settings = _settings(local_server, None)
    transport = make_transport(settings)
    local = _provider(ProviderRegistry.from_settings(settings), "local-chat")
    local_server.replies.append(Reply(status=status))

    with pytest.raises(UpstreamError) as error:
        await transport.session(local, ORG_A).chat(model="m", messages=MESSAGES)

    assert error.value.retryable is retryable
    assert local_server.count("/v1/chat/completions") == 1


async def test_timeout_is_retryable(
    local_server: FakeModelServer, make_transport: Callable[..., Transport]
) -> None:
    settings = replace(_settings(local_server, None), read_timeout_seconds=0.2)
    transport = make_transport(settings)
    local = _provider(ProviderRegistry.from_settings(settings), "local-chat")
    local_server.replies.append(Reply(delay=1))

    with pytest.raises(UpstreamError) as error:
        await transport.session(local, ORG_A).chat(model="m", messages=MESSAGES)

    assert error.value.retryable is True


async def test_stream_yields_pieces_with_usage_last(
    local_server: FakeModelServer, make_transport: Callable[..., Transport]
) -> None:
    settings = _settings(local_server, None)
    transport = make_transport(settings)
    local = _provider(ProviderRegistry.from_settings(settings), "local-chat")

    pieces = [
        piece
        async for piece in transport.session(local, ORG_A).stream_chat(model="m", messages=MESSAGES)
    ]

    assert "".join(p.text or "" for p in pieces) == "Xin chào"
    assert (pieces[-1].prompt_tokens, pieces[-1].completion_tokens) == (7, 2)
    assert local_server.requests[0].body["stream_options"] == {"include_usage": True}


async def test_stream_dropped_mid_way_raises_upstream_error(
    local_server: FakeModelServer, make_transport: Callable[..., Transport]
) -> None:
    settings = _settings(local_server, None)
    transport = make_transport(settings)
    local = _provider(ProviderRegistry.from_settings(settings), "local-chat")
    local_server.replies.append(Reply(drop_after=1))
    texts: list[str] = []

    with pytest.raises(UpstreamError):
        async for piece in transport.session(local, ORG_A).stream_chat(
            model="m", messages=MESSAGES
        ):
            texts.append(piece.text or "")

    assert "".join(texts) == "Xin"


async def test_no_proxy_configured_is_cloud_not_configured_without_network(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: Callable[..., ModelGateway]
) -> None:
    gateway = make_gateway(FakeCatalog([CLOUD], cloud_allowed=True), cloud=cloud_server)

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, CLOUD.ref, [ChatMessage("user", "hi")])

    assert error.value.code is ModelErrorCode.CLOUD_NOT_CONFIGURED
    assert cloud_server.requests == []
    assert proxy.request_lines == []


async def test_gateway_with_proxy_down_is_model_unavailable_after_one_retry(
    cloud_server: FakeModelServer, proxy: ForwardProxy, make_gateway: Callable[..., ModelGateway]
) -> None:
    collector = Collector()
    gateway = make_gateway(
        FakeCatalog([CLOUD], cloud_allowed=True),
        cloud=cloud_server,
        proxy=proxy,
        observers=[collector],
    )
    proxy.stop()

    with pytest.raises(ModelError) as error:
        await gateway.chat(CTX, CLOUD.ref, [ChatMessage("user", "hi")])

    assert error.value.code is ModelErrorCode.MODEL_UNAVAILABLE
    assert collector.records[0].attempts == 2
    assert cloud_server.requests == []


@pytest.mark.parametrize("provider_key", ["openai", "local-chat"])
async def test_cookies_are_never_stored_or_sent_across_organizations(
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
    provider_key: str,
) -> None:
    # R1-1: the pools are shared by every Organization, so a cookie set on Organization A's answer
    # (a provider or CDN cookie such as _cfuvid) must never be sent on any later call.
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    provider = _provider(_providers(settings, cloud_server), provider_key)
    server = cloud_server if provider_key == "openai" else local_server
    server.replies.extend([Reply(set_cookie="_cfuvid=COOKIE-1; Path=/"), Reply(), Reply()])

    for org in (ORG_A, ORG_B, ORG_A):
        await transport.session(provider, org).chat(model="m", messages=MESSAGES)

    assert len(server.requests) == 3
    assert [request.headers.get("cookie") for request in server.requests] == [None, None, None]


async def test_platform_openai_env_never_reaches_cloud_calls(
    monkeypatch: pytest.MonkeyPatch,
    local_server: FakeModelServer,
    cloud_server: FakeModelServer,
    proxy: ForwardProxy,
    make_transport: Callable[..., Transport],
) -> None:
    # R1-5: the SDK fills organization/project from these variables when none is passed.
    monkeypatch.setenv("OPENAI_ORG_ID", "org-platform")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-platform")
    settings = _settings(local_server, proxy)
    transport = make_transport(settings)
    registry = _providers(settings, cloud_server)

    await transport.session(_provider(registry, "openai"), ORG_A).chat(model="m", messages=MESSAGES)
    await transport.session(_provider(registry, "local-chat"), ORG_A).chat(
        model="m", messages=MESSAGES
    )

    for request in (*cloud_server.requests, *local_server.requests):
        assert "openai-organization" not in request.headers
        assert "openai-project" not in request.headers
