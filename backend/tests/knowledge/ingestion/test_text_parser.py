"""TXT parsing and decoding."""

import pytest

from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.model import ExtractionOutcome
from ei_ai.knowledge.ingestion.text_parser import decode_text, parse_text


def test_txt_utf8_bom_and_cp1252() -> None:
    assert decode_text(b"\xef\xbb\xbfXin ch\xc3\xa0o") == "Xin chào"
    text = "Größe, Übung und Straße – für Mädchen schön. " * 4
    assert decode_text(text.encode("cp1252")) == text
    assert parse_text(b"hello").blocks[0].heading_path == ()


def test_binary_without_a_usable_encoding_is_unreadable() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        decode_text(bytes(range(256)) * 4)
    assert (caught.value.status, caught.value.reason) == ("failed", "unreadable_encoding")


@pytest.mark.parametrize("fmt", ["txt", "md"])
@pytest.mark.parametrize("data", [b"", b"  \n\r\n\t ", b"\xef\xbb\xbf"])
def test_empty_text_is_no_text(fmt: str, data: bytes) -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document(fmt, data, None)  # type: ignore[arg-type]
    assert (caught.value.status, caught.value.reason) == ("failed", "no_text")


def test_crlf_and_cr_become_lf() -> None:
    result = extract_document("txt", b"a\r\nb\rc", None)
    assert result.text == "a\nb\nc"
