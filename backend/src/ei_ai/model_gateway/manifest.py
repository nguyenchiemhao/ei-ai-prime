"""The platform's local models: a code-reviewed manifest, no tenant data (EA-24, plan §3 #3).

Its entries are copied into an Organization's ``model_catalog`` by ``ei-ai model add`` and by the
demo seed. Every entry is pinned by the sha256 of its GGUF file and the publisher revision.
"""

import json
from functools import cache
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ei_ai.model_gateway.refs import MODEL_ID_PATTERN, VERSION_PATTERN, ModelRef

Kind = Literal["chat", "embedding", "rerank"]


class ManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Kind
    display_name: str = Field(min_length=1, max_length=200)
    model_id: str = Field(pattern=f"^{MODEL_ID_PATTERN.pattern}$")
    version: str = Field(pattern=f"^{VERSION_PATTERN.pattern}$")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[^@\s]+/[^@\s]+@[0-9a-f]{40}/\S+\.gguf$")
    deployment: Literal["local"]
    provider: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,49}$")
    vietnamese_quality: Literal["good", "fair", "poor"] | None
    vietnamese_quality_measured: bool
    tool_use: bool
    context_window: int | None = Field(gt=0)
    speed: Literal["faster", "slower"] | None
    status: Literal["available"]

    @property
    def ref(self) -> ModelRef:
        return ModelRef(self.model_id, self.version)


class PlatformModels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    entries: list[ManifestEntry] = Field(alias="models", min_length=1)

    @model_validator(mode="after")
    def refs_are_unique(self) -> "PlatformModels":
        """No two entries share a ref."""
        refs = [str(entry.ref) for entry in self.entries]
        if len(set(refs)) != len(refs):
            raise ValueError("model refs must be unique")
        return self

    def find(self, ref: ModelRef) -> ManifestEntry | None:
        """The entry of ``ref``, else None."""
        return next((entry for entry in self.entries if entry.ref == ref), None)

    def known_refs(self) -> list[str]:
        """Every ref, sorted (for the "unknown model" message)."""
        return sorted(str(entry.ref) for entry in self.entries)


@cache
def load_platform_models() -> PlatformModels:
    """The packaged manifest, validated once."""
    data = resources.files("ei_ai.model_gateway").joinpath("data/local-models.json")
    return PlatformModels.model_validate(json.loads(data.read_text("utf-8")))
