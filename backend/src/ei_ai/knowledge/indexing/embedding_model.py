"""The platform embedding model (EA-35, R3): one setting for every Organization.

D4 keeps documents and embeddings local, so the setting must name a local embedding entry of the
platform manifest. The error names the variable, never its value.
"""

from collections.abc import Mapping

from ei_ai.model_gateway.manifest import load_platform_models
from ei_ai.model_gateway.refs import InvalidModelRef, ModelRef
from ei_ai.settings import SettingsError

DEFAULT_EMBEDDING_MODEL_REF = "bge-m3@2026.10"

_INVALID = "EMBEDDING_MODEL_REF must name a local embedding model of the platform manifest"


def platform_embedding_ref(env: Mapping[str, str]) -> ModelRef:
    """The embedding model the platform indexes and queries with.

    Input: the environment. Output: ``EMBEDDING_MODEL_REF`` (unset or empty: the default) as a
    ref; ``SettingsError`` unless it names a manifest entry of kind ``embedding`` deployed locally.
    """
    raw = env.get("EMBEDDING_MODEL_REF") or DEFAULT_EMBEDDING_MODEL_REF
    try:
        ref = ModelRef.parse(raw)
    except InvalidModelRef:
        raise SettingsError(_INVALID) from None
    entry = load_platform_models().find(ref)
    if entry is None or entry.kind != "embedding" or entry.deployment != "local":
        raise SettingsError(_INVALID)
    return ref
