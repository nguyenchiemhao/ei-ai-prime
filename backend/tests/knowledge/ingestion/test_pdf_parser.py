"""PDF parsing, scan detection and untrusted PDFs."""

import pytest
from pypdf import PdfReader
from pypdf.errors import DependencyError

from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.model import ExtractionOutcome
from ei_ai.knowledge.ingestion.pdf_parser import parse_pdf
from support.documents import make_aes_pdf, make_blank_pdf, make_encrypted_pdf, make_text_pdf


def test_pdf_page_count() -> None:
    parsed = parse_pdf(make_text_pdf(["one", "two", "three"]))
    assert parsed.page_count == 3
    assert [block.page for block in parsed.blocks] == [1, 2, 3]
    assert "two" in parsed.blocks[1].text


def test_pdf_chunks_carry_page() -> None:
    pages = ["Alpha page text " * 5, "Beta page text " * 5, "Gamma page text " * 5]
    result = extract_document("pdf", make_text_pdf(pages), None)
    assert result.page_count == 3
    assert [chunk.page for chunk in result.chunks] == [1, 2, 3]
    assert all(chunk.heading_path == () for chunk in result.chunks)


def test_encrypted_pdf_is_password_protected() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_encrypted_pdf(), None)
    assert (caught.value.status, caught.value.reason) == ("failed", "password_protected")


@pytest.mark.parametrize("data", [b"\x00\x01garbage" * 50, b"%PDF-1.4\ntruncated", b""])
def test_garbage_with_pdf_extension_is_corrupt(data: bytes) -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", data, None)
    assert (caught.value.status, caught.value.reason) == ("failed", "corrupt_file")


def test_blank_pdf_is_scanned_not_supported() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_blank_pdf(2), None)
    assert (caught.value.status, caught.value.reason) == ("not_supported", "scanned_pdf")


def test_pdf_without_pages_is_corrupt() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_blank_pdf(0), None)
    assert caught.value.reason == "corrupt_file"


def test_scan_threshold_49_vs_50() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_text_pdf(["a" * 49]), None)
    assert caught.value.reason == "scanned_pdf"
    assert len(extract_document("pdf", make_text_pdf(["a" * 50]), None).chunks) == 1


def test_scan_threshold_is_an_average_over_pages() -> None:
    mixed = extract_document("pdf", make_text_pdf(["a" * 120, ""]), None)
    assert mixed.page_count == 2
    assert [chunk.page for chunk in mixed.chunks] == [1]


def test_aes_pdf_with_empty_user_password_is_readable() -> None:
    result = extract_document("pdf", make_aes_pdf(""), None)
    assert "Secret page text" in result.text
    assert result.page_count == 1


def test_aes_pdf_with_user_password_is_password_protected() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_aes_pdf("hunter2"), None)
    assert caught.value.reason == "password_protected"


def test_missing_crypto_library_is_processing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: PdfReader, password: str) -> int:
        raise DependencyError("cryptography is required")

    monkeypatch.setattr(PdfReader, "decrypt", fail)
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("pdf", make_encrypted_pdf(), None)
    assert caught.value.reason == "processing_error"
