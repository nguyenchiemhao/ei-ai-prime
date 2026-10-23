"""The rerank stage: the ``Reranker`` protocol, its gateway adapter and its setting (EA-36, R12).

A reranker only ever gets passages the principal may read (D8); it never logs.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Protocol

from ei_ai.model_gateway.context import ModelCallContext
from ei_ai.model_gateway.gateway import ModelGateway
from ei_ai.model_gateway.manifest import load_platform_models
from ei_ai.model_gateway.refs import InvalidModelRef, ModelRef
from ei_ai.settings import SettingsError

_INVALID = "RERANK_MODEL_REF must name a local rerank model of the platform manifest"


class RerankShapeError(Exception):
    """The model answered with the wrong number of scores or a non-finite score."""


class Reranker(Protocol):
    ref: ModelRef

    async def rerank(
        self, ctx: ModelCallContext, query: str, documents: Sequence[str]
    ) -> list[float]:
        """One score per document, in input order (higher = more relevant)."""
        ...


class GatewayReranker:
    """Reranks through ``ModelGateway.rerank`` with the model ``ref``; every score is checked."""

    def __init__(self, gateway: ModelGateway, ref: ModelRef) -> None:
        self.ref = ref
        self._gateway = gateway

    async def rerank(
        self, ctx: ModelCallContext, query: str, documents: Sequence[str]
    ) -> list[float]:
        """One score per document, in input order; gateway errors (``ModelError``) pass through."""
        if not documents:
            return []
        result = await self._gateway.rerank(ctx, self.ref, query, documents)
        scores: dict[int, float] = {}
        for index, score in result.results:
            if not 0 <= index < len(documents) or index in scores or not math.isfinite(score):
                raise RerankShapeError("rerank answer does not match the documents")
            scores[index] = score
        if len(scores) != len(documents):
            raise RerankShapeError("rerank answer does not match the documents")
        return [scores[index] for index in range(len(documents))]


def platform_rerank_ref(env: Mapping[str, str]) -> ModelRef | None:
    """The rerank model of the platform, or ``None`` (rerank off).

    Input: the environment. Output: ``RERANK_MODEL_REF`` as a ref (unset or empty: ``None``);
    ``SettingsError`` unless it names a manifest entry of kind ``rerank`` deployed locally. The
    error names the variable, never its value.
    """
    raw = env.get("RERANK_MODEL_REF")
    if not raw:
        return None
    try:
        ref = ModelRef.parse(raw)
    except InvalidModelRef:
        raise SettingsError(_INVALID) from None
    entry = load_platform_models().find(ref)
    if entry is None or entry.kind != "rerank" or entry.deployment != "local":
        raise SettingsError(_INVALID)
    return ref
