"""DOCX parsing and untrusted DOCX files."""

import zipfile
from io import BytesIO

import pytest

from ei_ai.knowledge.ingestion.docx_parser import MAX_PARSED_XML_BYTES, parse_docx
from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.model import ExtractionOutcome
from support.documents import add_docx_part, make_docx, make_zip_bomb_docx

_BLOCKS = [
    ("Normal", "Preamble before any heading."),
    ("Heading 1", "Overtime Policy"),
    ("Normal", "Intro text."),
    ("Heading 2", "Weekend work"),
    ("Normal", "Needs approval."),
    ("Heading 1", "Leave"),
    ("Normal", "Twelve days."),
]


def test_docx_heading_path_and_table_rows() -> None:
    parsed = parse_docx(make_docx(_BLOCKS, table=[["Role", "Limit"], ["Staff", "40 h"]]))
    paths = [block.heading_path for block in parsed.blocks]
    assert paths == [(), ("Overtime Policy",), ("Overtime Policy", "Weekend work"), ("Leave",)]
    assert parsed.blocks[0].text == "Preamble before any heading."
    assert parsed.blocks[2].text == "Weekend work\n\nNeeds approval."
    assert parsed.blocks[3].text.endswith("Twelve days.\n\nRole | Limit\nStaff | 40 h")


def test_docx_title_is_above_heading_1() -> None:
    parsed = parse_docx(make_docx([("Title", "Handbook"), ("Heading 1", "Pay"), ("Normal", "x")]))
    assert parsed.blocks[-1].heading_path == ("Handbook", "Pay")


def test_docx_pages_from_app_xml_or_estimate() -> None:
    with_pages = extract_document("docx", make_docx(_BLOCKS, pages=7), None)
    assert with_pages.page_count == 7
    estimated = extract_document("docx", make_docx(_BLOCKS), None)
    assert estimated.page_count == 1


def test_docx_chunks_carry_heading_path() -> None:
    result = extract_document("docx", make_docx(_BLOCKS), None)
    assert result.chunks[2].heading_path == ("Overtime Policy", "Weekend work")


def test_docx_zip_bomb_is_file_too_complex() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("docx", make_zip_bomb_docx(), None)
    assert (caught.value.status, caught.value.reason) == ("failed", "file_too_complex")


@pytest.mark.parametrize("data", [b"not a zip at all", b"", b"PK\x03\x04broken"])
def test_not_a_zip_docx_is_corrupt(data: bytes) -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("docx", data, None)
    assert caught.value.reason == "corrupt_file"


def test_zip_without_document_part_is_corrupt() -> None:
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("docx", buffer.getvalue(), None)
    assert caught.value.reason == "corrupt_file"


def _corrupt_app_xml_stream(data: bytes) -> bytes:
    """The DOCX with the deflate stream of docProps/app.xml overwritten by garbage."""
    info = zipfile.ZipFile(BytesIO(data)).getinfo("docProps/app.xml")
    name_length = int.from_bytes(data[info.header_offset + 26 : info.header_offset + 28], "little")
    extra_length = int.from_bytes(data[info.header_offset + 28 : info.header_offset + 30], "little")
    start = info.header_offset + 30 + name_length + extra_length
    return data[:start] + b"\xff" * 8 + data[start + 8 :]


def _encrypted_app_xml_docx() -> bytes:
    """A ZIP whose docProps/app.xml entry is flagged as password-encrypted."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        entry = zipfile.ZipInfo("docProps/app.xml")
        entry.flag_bits |= 0x1
        archive.writestr(entry, "<Pages>3</Pages>")
    return buffer.getvalue()


def test_corrupt_deflate_stream_is_corrupt_file() -> None:
    data = _corrupt_app_xml_stream(make_docx(_BLOCKS, pages=3))
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("docx", data, None)
    assert (caught.value.status, caught.value.reason) == ("failed", "corrupt_file")


def test_truncated_docx_is_corrupt_file() -> None:
    data = make_docx(_BLOCKS, pages=3)
    for cut in (len(data) // 2, len(data) - 10):
        with pytest.raises(ExtractionOutcome) as caught:
            extract_document("docx", data[:cut], None)
        assert caught.value.reason == "corrupt_file"


def test_encrypted_zip_entry_is_corrupt_file() -> None:
    with pytest.raises(ExtractionOutcome) as caught:
        extract_document("docx", _encrypted_app_xml_docx(), None)
    assert caught.value.reason == "corrupt_file"


_MIB = 1024 * 1024
_MAIN_PART = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def _xml_bytes(data: bytes) -> int:
    """The uncompressed size of the XML and relationship parts of a generated DOCX."""
    names = zipfile.ZipFile(BytesIO(data)).infolist()
    return sum(i.file_size for i in names if i.filename.endswith((".xml", ".rels")))


def test_docx_xml_parts_just_under_the_cap_are_parsed() -> None:
    base = make_docx(_BLOCKS)
    padding = MAX_PARSED_XML_BYTES - _xml_bytes(base)
    parsed = parse_docx(add_docx_part(base, "customXml/padding.xml", padding))
    assert parsed.blocks[0].text == "Preamble before any heading."


def test_docx_xml_parts_just_over_the_cap_are_file_too_complex() -> None:
    base = make_docx(_BLOCKS)
    padding = MAX_PARSED_XML_BYTES - _xml_bytes(base) + 1
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(add_docx_part(base, "customXml/padding.xml", padding))
    assert (caught.value.status, caught.value.reason) == ("failed", "file_too_complex")


def test_docx_xml_cap_is_far_below_the_api_memory() -> None:
    assert 48 * _MIB <= MAX_PARSED_XML_BYTES <= 64 * _MIB


def test_docx_media_does_not_count_against_the_xml_cap() -> None:
    size = MAX_PARSED_XML_BYTES + _MIB
    data = add_docx_part(make_docx(_BLOCKS), "word/media/image1.png", size, override="image/png")
    assert parse_docx(data).blocks[0].text == "Preamble before any heading."


def test_docx_xml_part_with_a_media_name_still_counts() -> None:
    data = add_docx_part(
        make_docx(_BLOCKS), "word/media/body.png", MAX_PARSED_XML_BYTES + 1, override=_MAIN_PART
    )
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(data)
    assert caught.value.reason == "file_too_complex"


def test_docx_oversized_content_types_is_file_too_complex() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b" " * (_MIB + 1))
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(buffer.getvalue())
    assert caught.value.reason == "file_too_complex"


def _rewrite_content_types(data: bytes, old: bytes, new: bytes) -> bytes:
    """The DOCX with ``old`` replaced by ``new`` in ``[Content_Types].xml``."""
    source = zipfile.ZipFile(BytesIO(data))
    result = BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "[Content_Types].xml":
                assert old in content
                content = content.replace(old, new)
            target.writestr(info.filename, content)
    return result.getvalue()


def test_docx_xml_content_type_written_with_a_character_reference_still_counts() -> None:
    # An XML parser reads "+x&#109;l" as "+xml": the cap must see the same content type.
    disguised = _MAIN_PART.replace("+xml", "+x&#109;l")
    data = add_docx_part(
        make_docx(_BLOCKS), "word/media/body.png", MAX_PARSED_XML_BYTES + 1, override=disguised
    )
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(data)
    assert caught.value.reason == "file_too_complex"


def test_docx_relationship_parts_count_whatever_their_content_type() -> None:
    # Relationship parts are always parsed as XML, so a non-XML default for .rels changes nothing.
    data = add_docx_part(make_docx(_BLOCKS), "word/_rels/extra.xml.rels", MAX_PARSED_XML_BYTES + 1)
    rels_type = b"application/vnd.openxmlformats-package.relationships+xml"
    data = _rewrite_content_types(data, rels_type, b"image/png")
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(data)
    assert caught.value.reason == "file_too_complex"


def test_docx_malformed_content_types_is_corrupt_file() -> None:
    data = _rewrite_content_types(make_docx(_BLOCKS), b"</Types>", b"<Types>")
    with pytest.raises(ExtractionOutcome) as caught:
        parse_docx(data)
    assert caught.value.reason == "corrupt_file"
