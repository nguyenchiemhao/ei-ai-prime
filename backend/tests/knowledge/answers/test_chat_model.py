"""The platform chat model and its gateway adapter (EA-37, R10, R22)."""

from collections.abc import AsyncIterator, Iterator

import pytest
from model_gateway.fakes import CTX, LOCAL, QWEN_SERVED, FakeCatalog, build_gateway

from ei_ai.knowledge.answers.chat_model import (
    DEFAULT_CHAT_MODEL_REF,
    GatewayAnswerModel,
    platform_chat_ref,
)
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.model_gateway.results import ChatCompleted, ChatMessage, TextDelta
from ei_ai.settings import ModelSettings, SettingsError
from support.fake_model_server import FakeModelServer, Reply, running_fake_model_server

MESSAGE = "CHAT_MODEL_REF must name a local chat model of the platform manifest"


def test_platform_chat_ref_defaults_to_the_local_qwen() -> None:
    assert DEFAULT_CHAT_MODEL_REF == "qwen3-4b-instruct-2507@2026.10"
    expected = ModelRef("qwen3-4b-instruct-2507", "2026.10")
    assert platform_chat_ref({}) == expected
    assert platform_chat_ref({"CHAT_MODEL_REF": ""}) == expected
    assert platform_chat_ref({"CHAT_MODEL_REF": "qwen3-4b-instruct-2507@2026.10"}) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "bge-m3@2026.10",  # an embedding model of the manifest
        "bge-reranker-v2-m3@2026.10",  # a rerank model of the manifest
        "qwen3-4b-instruct-2507@1999.01",  # unknown version
        "not-a-ref",  # malformed
    ],
)
def test_platform_chat_ref_refuses_other_refs_without_echoing_them(raw: str) -> None:
    with pytest.raises(SettingsError) as error:
        platform_chat_ref({"CHAT_MODEL_REF": raw})

    assert str(error.value) == MESSAGE
    assert raw not in str(error.value)


@pytest.fixture
def server() -> Iterator[FakeModelServer]:
    yield from running_fake_model_server()


@pytest.fixture
async def gateway(server: FakeModelServer) -> AsyncIterator[ModelGateway]:
    server.listed_ids = [QWEN_SERVED]
    made = build_gateway(FakeCatalog([LOCAL]), local=server)
    try:
        yield made
    finally:
        await made.aclose()


async def test_gateway_answer_model_streams(server: FakeModelServer, gateway: ModelGateway) -> None:
    server.replies.append(Reply(deltas=("Nghỉ ", "3 ngày")))
    model = GatewayAnswerModel(gateway, LOCAL.ref)
    messages = [ChatMessage("system", "Be brief."), ChatMessage("user", "Xin chào")]

    events = [e async for e in model.stream(CTX, messages, temperature=0.1)]

    assert model.ref == LOCAL.ref
    assert events[:2] == [TextDelta("Nghỉ "), TextDelta("3 ngày")]
    assert isinstance(events[-1], ChatCompleted)
    body = next(r.body for r in server.requests if r.path == "/v1/chat/completions")
    assert body["temperature"] == 0.1
    # max_tokens was not passed: the gateway default (MODEL_MAX_TOKENS) applies (R22).
    assert body["max_tokens"] == ModelSettings(environment="test").max_tokens
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
