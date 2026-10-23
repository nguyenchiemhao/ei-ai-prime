"""What the knowledge jobs need besides their ``JobContext``: the encrypted file store of originals
and the progress board (EA-33, R2), and the embedder of the index job (EA-35; None when indexing
is off). ``JobContext`` carries only the Organization and the session, so the runner sets the
runtime around each job.

The job modules import this one while ``ei_ai.jobs`` is still initialising, so the file store,
progress and embedder types are imported for type checking only: a runtime import would close an
import cycle (``ei_ai.storage.files``/``progress`` -> ``ei_ai.jobs`` -> ``job`` -> here)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ei_ai.knowledge.indexing.embedder import ChunkEmbedder
    from ei_ai.knowledge.ingestion.progress import ProgressBoard
    from ei_ai.storage.files import OrgFileStore


@dataclass(frozen=True)
class IngestionRuntime:
    files: OrgFileStore
    progress: ProgressBoard
    embedder: ChunkEmbedder | None = None


_RUNTIME: ContextVar[IngestionRuntime | None] = ContextVar("ingestion_runtime", default=None)


@contextmanager
def use_runtime(runtime: IngestionRuntime) -> Iterator[IngestionRuntime]:
    """Makes ``runtime`` the current one inside the block (this task and the tasks it starts).

    Input: the runtime. Output: the same runtime, for ``with ... as``.
    """
    token = _RUNTIME.set(runtime)
    try:
        yield runtime
    finally:
        _RUNTIME.reset(token)


def current_runtime() -> IngestionRuntime:
    """The runtime set by ``use_runtime``; ``RuntimeError`` when none is set."""
    runtime = _RUNTIME.get()
    if runtime is None:
        raise RuntimeError("no ingestion runtime is set")
    return runtime
