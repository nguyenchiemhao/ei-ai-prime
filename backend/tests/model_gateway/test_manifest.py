"""The platform model manifest (EA-24 AC7): validated, three local entries, pinned by sha256."""

import json
from importlib import resources
from typing import Any

import pytest
from pydantic import ValidationError

from ei_ai.model_gateway.manifest import PlatformModels, load_platform_models
from ei_ai.model_gateway.refs import ModelRef

CHAT_DIGEST = "sha256:3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
CHAT_SOURCE = (
    "unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9"
    "/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
)


def _raw() -> dict[str, Any]:
    text = resources.files("ei_ai.model_gateway").joinpath("data/local-models.json").read_text()
    data: dict[str, Any] = json.loads(text)
    return data


def test_has_exactly_the_chat_embedding_and_rerank_entries() -> None:
    models = load_platform_models()

    assert [(str(e.ref), e.kind, e.provider) for e in models.entries] == [
        ("qwen3-4b-instruct-2507@2026.10", "chat", "local-chat"),
        ("bge-m3@2026.10", "embedding", "local-embedding"),
        ("bge-reranker-v2-m3@2026.10", "rerank", "local-rerank"),
    ]
    assert all(e.deployment == "local" and e.status == "available" for e in models.entries)


def test_chat_entry_has_the_contract_values() -> None:
    chat = load_platform_models().find(ModelRef("qwen3-4b-instruct-2507", "2026.10"))

    assert chat is not None
    assert chat.display_name == "Qwen3 4B Instruct 2507"
    assert chat.digest == CHAT_DIGEST
    assert chat.source_revision == CHAT_SOURCE
    assert chat.vietnamese_quality is None
    assert chat.vietnamese_quality_measured is False
    assert chat.tool_use is True
    assert chat.context_window == 8192
    assert chat.speed is None


def test_every_source_revision_names_a_40_hex_commit_and_a_gguf_file() -> None:
    for entry in load_platform_models().entries:
        repo, _, rest = entry.source_revision.partition("@")
        revision, _, file = rest.partition("/")
        assert "/" in repo
        assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
        assert file.endswith(".gguf")


def test_find_returns_none_for_an_unknown_ref() -> None:
    assert load_platform_models().find(ModelRef("gpt-4.1", "2025.04")) is None


def test_known_refs_are_sorted() -> None:
    assert load_platform_models().known_refs() == [
        "bge-m3@2026.10",
        "bge-reranker-v2-m3@2026.10",
        "qwen3-4b-instruct-2507@2026.10",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("digest", "sha256:" + "A" * 64),
        ("digest", None),
        ("deployment", "cloud"),
        ("kind", "vision"),
        ("model_id", "Qwen3"),
        ("context_window", 0),
        ("unexpected", "x"),
    ],
)
def test_invalid_entries_are_rejected(field: str, value: object) -> None:
    raw = _raw()
    raw["models"][0][field] = value

    with pytest.raises(ValidationError):
        PlatformModels.model_validate(raw)


def test_duplicate_refs_are_rejected() -> None:
    raw = _raw()
    raw["models"].append(dict(raw["models"][0]))

    with pytest.raises(ValidationError):
        PlatformModels.model_validate(raw)
