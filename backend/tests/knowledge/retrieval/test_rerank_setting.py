"""The platform rerank setting (R12): unset = off, else a local rerank entry of the manifest."""

import pytest

from ei_ai.knowledge.retrieval.reranker import platform_rerank_ref
from ei_ai.model_gateway.refs import ModelRef
from ei_ai.settings import SettingsError

MESSAGE = "RERANK_MODEL_REF must name a local rerank model of the platform manifest"


@pytest.mark.parametrize("env", [{}, {"RERANK_MODEL_REF": ""}])
def test_rerank_setting_unset_is_off(env: dict[str, str]) -> None:
    assert platform_rerank_ref(env) is None


def test_rerank_setting_accepts_manifest_reranker() -> None:
    ref = platform_rerank_ref({"RERANK_MODEL_REF": "bge-reranker-v2-m3@2026.10"})

    assert ref == ModelRef("bge-reranker-v2-m3", "2026.10")


@pytest.mark.parametrize("raw", ["bge-m3@2026.10", "x@1", "bad ref"])
def test_rerank_setting_rejects_embedding_or_unknown(raw: str) -> None:
    with pytest.raises(SettingsError) as error:
        platform_rerank_ref({"RERANK_MODEL_REF": raw})

    assert str(error.value) == MESSAGE
    assert raw not in str(error.value)
