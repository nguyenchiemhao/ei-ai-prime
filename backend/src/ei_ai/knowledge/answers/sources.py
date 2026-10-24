"""Passage title and section shown to the user (EA-37, R13)."""

from collections.abc import Sequence

_EXTENSIONS = (".pdf", ".docx", ".md", ".txt")


def source_title(document_name: str) -> str:
    """The document name without a known ingestion extension; other names stay unchanged."""
    if document_name.lower().endswith(_EXTENSIONS):
        return document_name.rsplit(".", 1)[0]
    return document_name


def source_section(heading_path: Sequence[str]) -> str | None:
    return heading_path[-1] if heading_path else None
