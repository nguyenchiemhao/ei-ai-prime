"""The platform chat model of the ask box (EA-37, R10).

One setting for every Organization, like the embedding model. D4 keeps documents local, so it
must name a local chat entry of the platform manifest. The error names the variable, never its
value.
"""

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Protocol

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.manifest import load_platform_models
from ei_ai.model_gateway.refs import InvalidModelRef, ModelRef
from ei_ai.model_gateway.results import ChatMessage, StreamEvent
from ei_ai.settings import SettingsError

DEFAULT_CHAT_MODEL_REF = "qwen3-4b-instruct-2507@2026.10"

_INVALID = "CHAT_MODEL_REF must name a local chat model of the platform manifest"


def platform_chat_ref(env: Mapping[str, str]) -> ModelRef:
    """``CHAT_MODEL_REF`` (unset or empty: the default) as a ref; ``SettingsError`` unless it
    names a manifest entry of kind ``chat`` deployed locally."""
    raw = env.get("CHAT_MODEL_REF") or DEFAULT_CHAT_MODEL_REF
    try:
        ref = ModelRef.parse(raw)
    except InvalidModelRef:
        raise SettingsError(_INVALID) from None
    entry = load_platform_models().find(ref)
    if entry is None or entry.kind != "chat" or entry.deployment != "local":
        raise SettingsError(_INVALID)
    return ref


class AnswerModel(Protocol):
    """A streaming chat model. ``stream`` returns an async generator so callers can close it."""

    ref: ModelRef

    def stream(
        self,
        ctx: ModelCallContext,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[StreamEvent]: ...


class GatewayAnswerModel:
    """Streams through ``ModelGateway.stream_chat`` with the model ``ref``; ``max_tokens=None``
    means the gateway default (``MODEL_MAX_TOKENS``)."""

    def __init__(self, gateway: ModelGateway, ref: ModelRef) -> None:
        self.ref = ref
        self._gateway = gateway

    def stream(
        self,
        ctx: ModelCallContext,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        return self._gateway.stream_chat(
            ctx, self.ref, messages, max_tokens=max_tokens, temperature=temperature
        )
