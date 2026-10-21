"""Version pinning (D18, plan §3 #14): which id a server must serve for a catalog row.

The local model start script (``infra/model/start-model.sh``) refuses a file whose sha256 differs
from the configured one and serves the model as ``<model_id>@sha256-<first 12 hex of the file's
actual sha256>``. So the listed id proves which file runs; a newer build has another id. Cloud
providers serve the pinned snapshot id itself and must answer with exactly that id.
"""

from ei_ai.model_gateway.catalog import CatalogEntry
from ei_ai.model_gateway.errors import ModelError, ModelErrorCode
from ei_ai.model_gateway.providers import Provider

_DIGEST_PREFIX = "sha256:"
SERVED_DIGEST_HEX = 12


def served_model_id(entry: CatalogEntry, provider: Provider) -> str:
    """The id to request (and, for llama.cpp, to find in ``GET /models``)."""
    if provider.served_id_rule == "model_id":
        return entry.model_id
    if entry.digest is None or not entry.digest.startswith(_DIGEST_PREFIX):
        raise _unavailable(entry)
    digest_hex = entry.digest[len(_DIGEST_PREFIX) :]
    return f"{entry.model_id}@sha256-{digest_hex[:SERVED_DIGEST_HEX]}"


def verify_listed(entry: CatalogEntry, served_id: str, listed: set[str]) -> None:
    """The server lists the pinned id, else ``PINNED_VERSION_UNAVAILABLE`` (never another id)."""
    if served_id not in listed:
        raise _unavailable(entry)


def verify_answered_by(entry: CatalogEntry, provider: Provider, answered_model: str) -> None:
    """A cloud answer comes from the pinned snapshot, else ``PINNED_VERSION_UNAVAILABLE``.

    llama.cpp echoes whatever model name was requested, so its answers are not checked: its
    ``GET /models`` listing is the proof.
    """
    if provider.served_id_rule == "model_id" and answered_model != entry.model_id:
        raise _unavailable(entry)


def _unavailable(entry: CatalogEntry) -> ModelError:
    return ModelError(ModelErrorCode.PINNED_VERSION_UNAVAILABLE, str(entry.ref), entry.kind)
