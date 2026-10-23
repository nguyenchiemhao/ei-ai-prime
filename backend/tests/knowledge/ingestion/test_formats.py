"""Supported formats and file-name rules."""

import pytest

from ei_ai.knowledge.errors import InvalidFileName
from ei_ai.knowledge.ingestion.formats import (
    MAX_FILE_BYTES,
    ORG_QUOTA_BYTES,
    clean_file_name,
    format_for,
)


def test_format_for_supported_and_unsupported() -> None:
    assert format_for("a.PDF") == "pdf"
    assert format_for("Report.v2.Docx") == "docx"
    assert format_for("notes.md") == "md"
    assert format_for("notes.TXT") == "txt"
    for name in ["x.exe", "y.doc", "z.xlsx", "noext", "pdf", "a.pdf.exe"]:
        assert format_for(name) is None


def test_limits() -> None:
    assert MAX_FILE_BYTES == 52_428_800
    assert ORG_QUOTA_BYTES == 1_073_741_824


def test_clean_file_name_rules() -> None:
    assert clean_file_name("a/b/c.txt") == "c.txt"
    assert clean_file_name("..\\..\\etc\\passwd.txt") == "passwd.txt"
    assert clean_file_name("  Quy trình.md  ") == "Quy trình.md"
    assert clean_file_name("x" * 255) == "x" * 255
    nfd = "Quy trình.md"
    assert clean_file_name(nfd) == "Quy trình.md"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "dir/",
        "x" * 256,
        "a\x00b.txt",
        "a\tb.txt",
        "a\x7fb.txt",
        "a\u0085b.txt",
        "a b.txt",
        "a b.txt",
    ],
)
def test_clean_file_name_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidFileName):
        clean_file_name(raw)
