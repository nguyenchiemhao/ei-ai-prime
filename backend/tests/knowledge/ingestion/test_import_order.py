"""``ei_ai.jobs`` imports the ingestion job when the package loads, so each module around it must
import cleanly when it is the first one a fresh interpreter loads (no import cycle)."""

import subprocess
import sys

import pytest

MODULES = (
    "ei_ai.jobs",
    "ei_ai.storage.files",
    "ei_ai.knowledge.ingestion.job",
    "ei_ai.knowledge.ingestion.progress",
    "ei_ai.knowledge.ingestion.runtime",
    "ei_ai.knowledge.ingestion.runner",
    "ei_ai.knowledge.indexing.job",
    "ei_ai.knowledge.indexing.indexer",
    "ei_ai.knowledge.indexing.embedder",
)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_without_a_cycle(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
