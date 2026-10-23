"""The extraction pipeline end to end: normalisation, offsets, progress."""

import unicodedata

import pytest

from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.model import ExtractionOutcome
from support.documents import make_docx, make_text_pdf

_MD = (
    "# Quy trình làm thêm giờ\n\n"
    + "Nhân viên cần được quản lý phê duyệt trước khi làm thêm giờ. " * 12
    + "\n\n## Làm việc cuối tuần\n\n"
    + "Cần có sự đồng ý bằng văn bản của trưởng phòng. " * 12
)
_DOCX = [
    ("Heading 1", "Quy trình làm thêm giờ"),
    ("Normal", "Nhân viên cần được phê duyệt."),
    ("Heading 2", "Làm việc cuối tuần"),
    ("Normal", "Cần có sự đồng ý của trưởng phòng."),
]


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def test_nfc_and_nfd_documents_give_identical_chunks() -> None:
    nfc = unicodedata.normalize("NFC", _MD)
    assert nfc != _nfd(nfc)
    assert extract_document("md", nfc.encode(), None) == extract_document(
        "md", _nfd(nfc).encode(), None
    )
    assert extract_document("txt", nfc.encode(), None) == extract_document(
        "txt", _nfd(nfc).encode(), None
    )
    nfd_docx = [(style, _nfd(text)) for style, text in _DOCX]
    assert extract_document("docx", make_docx(_DOCX), None) == extract_document(
        "docx", make_docx(nfd_docx), None
    )


def test_text_is_the_blocks_joined_and_chunks_index_into_it() -> None:
    result = extract_document("md", _MD.encode(), None)
    assert "\n\n## Làm việc cuối tuần\n\n" in result.text
    for chunk in result.chunks:
        assert chunk.text == result.text[chunk.char_start : chunk.char_end]


def test_progress_for_pdf_maps_pages_to_0_80_then_90() -> None:
    seen: list[int] = []
    extract_document("pdf", make_text_pdf(["page text " * 10] * 4), seen.append)
    assert seen == [20, 40, 60, 80, 90]


def test_progress_for_other_formats_is_90() -> None:
    seen: list[int] = []
    extract_document("txt", b"hello", seen.append)
    assert seen == [90]


def test_outcome_message_is_the_reason_code_only() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("txt", b"   ", None)
    assert str(caught.value) == "no_text"


def test_docx_and_md_chunks_carry_heading_path() -> None:
    md = extract_document("md", _MD.encode(), None)
    assert md.chunks[0].heading_path == ("Quy trình làm thêm giờ",)
    assert md.chunks[-1].heading_path == ("Quy trình làm thêm giờ", "Làm việc cuối tuần")
    docx = extract_document("docx", make_docx(_DOCX), None)
    assert docx.chunks[-1].heading_path == ("Quy trình làm thêm giờ", "Làm việc cuối tuần")
