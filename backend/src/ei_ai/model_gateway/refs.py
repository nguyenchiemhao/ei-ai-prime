"""Model refs ``<model_id>@<version>``: the name under which an Assistant pins a catalog row."""

import re
from dataclasses import dataclass

# Must match the CHECK constraints of migration 0005.
MODEL_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")
VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}")


class InvalidModelRef(ValueError):
    """Not ``<model_id>@<version>`` with the catalog's patterns (the value is never echoed)."""


@dataclass(frozen=True)
class ModelRef:
    model_id: str
    version: str

    def __post_init__(self) -> None:
        if not MODEL_ID_PATTERN.fullmatch(self.model_id) or not VERSION_PATTERN.fullmatch(
            self.version
        ):
            raise InvalidModelRef("a model ref is <model_id>@<version>")

    @classmethod
    def parse(cls, raw: str) -> "ModelRef":
        """The ref in ``raw``; raises ``InvalidModelRef`` unless it has exactly one ``@``."""
        model_id, separator, version = raw.strip().partition("@")
        if not separator:
            raise InvalidModelRef("a model ref is <model_id>@<version>")
        return cls(model_id, version)

    def __str__(self) -> str:
        return f"{self.model_id}@{self.version}"
