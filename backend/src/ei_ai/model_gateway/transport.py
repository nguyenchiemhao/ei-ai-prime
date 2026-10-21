"""The only gateway module that imports the OpenAI SDK and its HTTP client (the egress seam).

- One ``httpx2.AsyncClient`` per provider, shared by every Organization: a connection pool that
  keeps no credentials and no per-call state. Its cookie jar refuses every cookie, so a
  ``Set-Cookie`` on one Organization's answer is never sent on another's call (D46, R1-1).
  ``trust_env=False`` everywhere: ``HTTP(S)_PROXY``/``NO_PROXY`` can neither bypass nor redirect
  anything.
- Cloud clients always use the explicit egress proxy (``EGRESS_PROXY_URL``, D33). Without a proxy
  or without the Organization's key a cloud session is refused before any network access; a
  proxy that is down is a connection error, never a direct connection. FND-10 replaces this seam
  with its ``egress`` module.
- Per cloud call an ``AsyncOpenAI`` carries the calling Organization's key on the shared pool;
  local servers take no key, so their client is reused. The SDK's own retries are off (the
  gateway retries once, D18), and the ``OpenAI-Organization``/``OpenAI-Project`` headers it would
  fill from ``OPENAI_ORG_ID``/``OPENAI_PROJECT_ID`` are never sent.
- Failures become ``UpstreamError(retryable)`` without an exception chain: no URL, key or
  upstream body ever travels in an exception (D52).

openai 3.29 is built on ``httpx2`` (pydantic's fork of httpx), not on ``httpx``.
"""

import uuid
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any, Protocol, cast

import httpx2
import openai
from openai import Omit
from openai.types.chat import ChatCompletionMessageParam

from ei_ai.model_gateway.providers import Provider
from ei_ai.settings import ModelSettings

# Local llama.cpp servers need no key; the SDK insists on one.
LOCAL_API_KEY = "local-no-key"
# Without a value the SDK reads these from the platform's environment (OPENAI_ORG_ID,
# OPENAI_PROJECT_ID) and would send them on every Organization's call; Omit drops the headers.
_NO_PLATFORM_HEADERS = cast(
    Mapping[str, str], {"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()}
)


def _cookieless_jar() -> CookieJar:
    """A jar whose policy accepts no domain, so it never stores a cookie."""
    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


class CloudCredentials(Protocol):
    def api_key(self, org_id: uuid.UUID, provider: str) -> str | None:
        """The Organization's own key for ``provider`` (BYOK, D17), or None."""
        ...


class NoCloudCredentials:
    """No BYOK store yet (ADM-04): every cloud call fails closed."""

    def api_key(self, org_id: uuid.UUID, provider: str) -> str | None:
        return None


class ProviderNotConfigured(Exception):
    """No base URL, proxy or key: refused before any network access."""


class UpstreamError(Exception):
    """A failed request. ``retryable``: 5xx, timeout or connection error (never 4xx)."""

    def __init__(self, retryable: bool) -> None:
        super().__init__("retryable upstream failure" if retryable else "upstream failure")
        self.retryable = retryable


@dataclass(frozen=True)
class ChatReply:
    model: str
    text: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class StreamPiece:
    model: str
    text: str | None
    finish_reason: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class EmbedReply:
    model: str
    vectors: list[list[float]]
    prompt_tokens: int


def _upstream_error(error: Exception) -> UpstreamError:
    if isinstance(error, openai.APIStatusError):
        return UpstreamError(retryable=error.status_code >= 500)
    retryable = isinstance(
        error, openai.APIConnectionError | httpx2.TransportError | httpx2.StreamError
    )
    return UpstreamError(retryable=retryable)


# Raised by the SDK, the HTTP client or a malformed response. Each method turns them into an
# ``UpstreamError`` raised after the ``except`` block, so neither ``__cause__`` nor
# ``__context__`` links to the SDK exception, whose message can echo the upstream body (D52).
_FAILURES = (
    openai.OpenAIError,
    httpx2.HTTPError,
    httpx2.StreamError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
)


class ProviderSession:
    """One call's view of a provider: the shared pool plus this Organization's key."""

    def __init__(self, client: openai.AsyncOpenAI) -> None:
        self._sdk = client

    async def served_ids(self) -> set[str]:
        """The model ids ``GET /models`` lists."""
        try:
            page = await self._sdk.models.list()
            return {model.id for model in page.data}
        except _FAILURES as error:
            failure = _upstream_error(error)
        raise failure

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatReply:
        try:
            response = await self._sdk.chat.completions.create(
                model=model,
                messages=_messages(messages),
                max_tokens=_given(max_tokens),
                temperature=_given(temperature),
            )
            choice = response.choices[0]
            usage = response.usage
            return ChatReply(
                model=response.model,
                text=choice.message.content or "",
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            )
        except _FAILURES as error:
            failure = _upstream_error(error)
        raise failure

    async def stream_chat(
        self,
        *,
        model: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncGenerator[StreamPiece]:
        """The chunks as pieces; the usage arrives on the last piece (``include_usage``)."""
        failure: UpstreamError | None = None
        try:
            stream = await self._sdk.chat.completions.create(
                model=model,
                messages=_messages(messages),
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=_given(max_tokens),
                temperature=_given(temperature),
            )
            async with stream:
                async for chunk in stream:
                    choice = chunk.choices[0] if chunk.choices else None
                    usage = chunk.usage
                    yield StreamPiece(
                        model=chunk.model,
                        text=choice.delta.content if choice else None,
                        finish_reason=choice.finish_reason if choice else None,
                        prompt_tokens=usage.prompt_tokens if usage else None,
                        completion_tokens=usage.completion_tokens if usage else None,
                    )
        except _FAILURES as error:
            failure = _upstream_error(error)
        if failure is not None:
            raise failure

    async def embed(self, *, model: str, inputs: Sequence[str]) -> EmbedReply:
        try:
            response = await self._sdk.embeddings.create(model=model, input=list(inputs))
            vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
            return EmbedReply(response.model, vectors, response.usage.prompt_tokens)
        except _FAILURES as error:
            failure = _upstream_error(error)
        raise failure

    async def rerank(
        self, *, model: str, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[tuple[int, float]]:
        """llama.cpp ``POST /rerank``: ``{"results": [{"index", "relevance_score"}]}``."""
        body: dict[str, Any] = {"model": model, "query": query, "documents": list(documents)}
        if top_n is not None:
            body["top_n"] = top_n
        try:
            response = await self._sdk.post("/rerank", cast_to=object, body=body)
            results = response["results"]  # type: ignore[index]
            return [(int(r["index"]), float(r["relevance_score"])) for r in results]
        except _FAILURES as error:
            failure = _upstream_error(error)
        raise failure


def _messages(messages: Sequence[dict[str, str]]) -> list[ChatCompletionMessageParam]:
    """Plain role/content dicts in the SDK's message type (roles are checked by the gateway)."""
    return cast(list[ChatCompletionMessageParam], list(messages))


def _given[T](value: T | None) -> T | Omit:
    """The SDK's "leave it out" marker for an unset option."""
    return openai.omit if value is None else value


class Transport:
    """HTTP clients of the gateway, built here and nowhere else."""

    def __init__(
        self, settings: ModelSettings, credentials: CloudCredentials | None = None
    ) -> None:
        self._settings = settings
        self._credentials = credentials or NoCloudCredentials()
        self._timeout = httpx2.Timeout(
            settings.read_timeout_seconds, connect=settings.connect_timeout_seconds
        )
        self._pools: dict[str, httpx2.AsyncClient] = {}
        self._local_clients: dict[str, openai.AsyncOpenAI] = {}

    def _pool(self, provider: Provider) -> httpx2.AsyncClient:
        pool = self._pools.get(provider.key)
        if pool is None:
            proxy = self._settings.egress_proxy_url if provider.deployment == "cloud" else None
            pool = httpx2.AsyncClient(
                timeout=self._timeout, trust_env=False, proxy=proxy, cookies=_cookieless_jar()
            )
            self._pools[provider.key] = pool
        return pool

    def session(self, provider: Provider, org_id: uuid.UUID) -> ProviderSession:
        """A session for one call; raises ``ProviderNotConfigured`` before any network access."""
        if provider.base_url is None:
            raise ProviderNotConfigured
        if provider.deployment == "local":
            # Local servers take no key, so one client per provider is reused across calls.
            client = self._local_clients.get(provider.key)
            if client is None:
                client = self._local_clients[provider.key] = self._sdk_client(
                    provider, provider.base_url, LOCAL_API_KEY
                )
            return ProviderSession(client)
        if self._settings.egress_proxy_url is None:
            raise ProviderNotConfigured
        key = self._credentials.api_key(org_id, provider.key)
        if not key:
            raise ProviderNotConfigured
        # A cloud client carries one Organization's key: built per call, never shared.
        return ProviderSession(self._sdk_client(provider, provider.base_url, key))

    def _sdk_client(self, provider: Provider, base_url: str, key: str) -> openai.AsyncOpenAI:
        return openai.AsyncOpenAI(
            api_key=key,
            base_url=base_url,
            http_client=self._pool(provider),
            timeout=self._timeout,
            max_retries=0,
            default_headers=_NO_PLATFORM_HEADERS,
        )

    async def aclose(self) -> None:
        for pool in self._pools.values():
            await pool.aclose()
        self._pools.clear()
        self._local_clients.clear()
