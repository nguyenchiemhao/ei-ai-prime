"""The typed errors of the Model Gateway. Messages are fixed text plus the model ref: never a
prompt, an answer, a URL, a key or an upstream error body (D52)."""

from enum import StrEnum


class ModelErrorCode(StrEnum):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_RETIRED = "MODEL_RETIRED"
    PINNED_VERSION_UNAVAILABLE = "PINNED_VERSION_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    CLOUD_DISABLED = "CLOUD_DISABLED"
    CLOUD_NOT_CONFIGURED = "CLOUD_NOT_CONFIGURED"


def _message(code: ModelErrorCode, ref: str, kind: str) -> str:
    match code:
        case ModelErrorCode.MODEL_NOT_FOUND:
            return f"no {kind} model {ref} in this Organization's catalog"
        case ModelErrorCode.MODEL_RETIRED:
            return f"model {ref} is retired"
        case ModelErrorCode.PINNED_VERSION_UNAVAILABLE:
            return f"pinned version unavailable: {ref}"
        case ModelErrorCode.MODEL_UNAVAILABLE:
            return f"model {ref} is unavailable"
        case ModelErrorCode.CLOUD_DISABLED:
            return "cloud models are off for this Organization"
        case ModelErrorCode.CLOUD_NOT_CONFIGURED:
            return "cloud model calls are not configured"


class ModelError(Exception):
    """A gateway call failed with ``code``; ``str()`` is the fixed, user-safe message."""

    def __init__(self, code: ModelErrorCode, ref: str, kind: str = "chat") -> None:
        super().__init__(_message(code, ref, kind))
        self.code = code
        self.ref = ref
