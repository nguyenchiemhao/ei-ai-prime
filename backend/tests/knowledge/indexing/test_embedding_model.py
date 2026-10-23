"""The platform embedding model (EA-35, R3): a local embedding entry of the manifest."""

import pytest

from ei_ai.knowledge.indexing.embedding_model import (
    DEFAULT_EMBEDDING_MODEL_REF,
    platform_embedding_ref,
)
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.settings import SettingsError

MESSAGE = "EMBEDDING_MODEL_REF must name a local embedding model of the platform manifest"


def test_platform_embedding_ref_must_be_a_local_manifest_embedding() -> None:
    assert DEFAULT_EMBEDDING_MODEL_REF == "bge-m3@2026.10"
    assert platform_embedding_ref({}) == ModelRef("bge-m3", "2026.10")
    assert platform_embedding_ref({"EMBEDDING_MODEL_REF": "bge-m3@2026.10"}) == ModelRef(
        "bge-m3", "2026.10"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "qwen3-4b-instruct-2507@2026.10",  # a chat model of the manifest
        "bge-reranker-v2-m3@2026.10",  # a rerank model of the manifest
        "bge-m3@1999.01",  # unknown version
        "not-a-ref",  # malformed
        "Bad Ref@x y",  # malformed
    ],
)
def test_platform_embedding_ref_refuses_other_refs(raw: str) -> None:
    with pytest.raises(SettingsError) as error:
        platform_embedding_ref({"EMBEDDING_MODEL_REF": raw})

    assert str(error.value) == MESSAGE
