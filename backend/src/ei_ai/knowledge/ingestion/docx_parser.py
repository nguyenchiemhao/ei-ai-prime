"""DOCX parsing: heading sections with a heading path."""

import posixpath
import re
import zipfile
import zlib
from io import BytesIO

from docx import Document
from docx.oxml.parser import parse_xml
from docx.table import Table
from docx.text.paragraph import Paragraph

from ei_ai.knowledge.ingestion.model import (
    CORRUPT_FILE,
    FILE_TOO_COMPLEX,
    Block,
    ExtractionOutcome,
    ParsedDocument,
)

MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
# python-docx builds an lxml tree of every XML part it loads, several times the part's size, inside
# the API process (1 GiB). Media parts stay raw bytes, so only XML parts count against this cap.
MAX_PARSED_XML_BYTES = 50 * 1024 * 1024
_APP_XML = "docProps/app.xml"
_APP_XML_MAX_BYTES = 64 * 1024
_CONTENT_TYPES = "[Content_Types].xml"
_CONTENT_TYPES_MAX_BYTES = 1024 * 1024
_CT_NAMESPACE = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_DEFAULT_TAG = f"{_CT_NAMESPACE}Default"
_OVERRIDE_TAG = f"{_CT_NAMESPACE}Override"
_PAGES = re.compile(rb"<(?:\w+:)?Pages>\s*(\d+)\s*</(?:\w+:)?Pages>")
_HEADING = re.compile(r"^Heading ([1-6])$")


def _content_types(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    """The ``[Content_Types].xml`` defaults (by extension) and overrides (by part name), lower-case
    keys without the leading slash; empty when the part is missing. It is read with python-docx's
    own parser and namespace, so character references and the like decode as python-docx sees them.
    """
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    if _CONTENT_TYPES not in archive.namelist():
        return defaults, overrides
    if archive.getinfo(_CONTENT_TYPES).file_size > _CONTENT_TYPES_MAX_BYTES:
        raise ExtractionOutcome("failed", FILE_TOO_COMPLEX)
    try:
        root = parse_xml(archive.read(_CONTENT_TYPES))
    except SyntaxError as error:  # lxml.etree.XMLSyntaxError
        raise ExtractionOutcome("failed", CORRUPT_FILE) from error
    for entry in root:
        content_type = entry.get("ContentType") or ""
        extension = entry.get("Extension")
        part_name = entry.get("PartName")
        if entry.tag == _DEFAULT_TAG and extension is not None:
            defaults[extension.lower()] = content_type
        elif entry.tag == _OVERRIDE_TAG and part_name is not None:
            overrides[part_name.lstrip("/").lower()] = content_type
    return defaults, overrides


def _parsed_xml_bytes(archive: zipfile.ZipFile) -> int:
    """The uncompressed size of every part an OPC reader may parse as XML: relationship parts
    always; any other part unless its content type (override, else extension default) is known
    and not XML."""
    defaults, overrides = _content_types(archive)
    total = 0
    for info in archive.infolist():
        name = info.filename.lower()
        content_type = overrides.get(name, defaults.get(posixpath.splitext(name)[1][1:], ""))
        if name.endswith(".rels") or not content_type or content_type.lower().endswith("xml"):
            total += info.file_size
    return total


def _check_archive(data: bytes) -> int | None:
    """Reject non-ZIPs and zip bombs; the ``<Pages>`` value of app.xml when it is above 0."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ExtractionOutcome("failed", FILE_TOO_COMPLEX)
            if _parsed_xml_bytes(archive) > MAX_PARSED_XML_BYTES:
                raise ExtractionOutcome("failed", FILE_TOO_COMPLEX)
            if _APP_XML not in archive.namelist():
                return None
            with archive.open(_APP_XML) as app:
                match = _PAGES.search(app.read(_APP_XML_MAX_BYTES))
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        NotImplementedError,
        EOFError,
        OSError,
        RuntimeError,
        ValueError,
        zlib.error,
    ) as error:
        raise ExtractionOutcome("failed", CORRUPT_FILE) from error
    pages = int(match[1]) if match else 0
    return pages or None


def _heading_level(paragraph: Paragraph) -> int | None:
    """0 for Title, 1-6 for Heading 1-6, None for body text."""
    name = paragraph.style.name if paragraph.style is not None else ""
    if name == "Title":
        return 0
    match = _HEADING.match(name or "")
    return int(match[1]) if match else None


def _table_lines(table: Table) -> list[str]:
    """One line per non-empty row, the distinct cells joined by `` | ``."""
    lines: list[str] = []
    for row in table.rows:
        seen: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(cell.text.strip())
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


def parse_docx(data: bytes) -> ParsedDocument:
    """Sections in body order; each starts at a heading and holds its paragraphs (blank-line
    separated) and table rows. Text before the first heading has an empty path."""
    pages = _check_archive(data)
    try:
        body = list(Document(BytesIO(data)).iter_inner_content())
    except Exception as error:
        raise ExtractionOutcome("failed", CORRUPT_FILE) from error
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    parts: list[str] = []
    section_path: tuple[str, ...] = ()

    for item in body:
        if isinstance(item, Table):
            rows = "\n".join(_table_lines(item))
            if rows:
                parts.append(rows)
            continue
        text = item.text.strip()
        level = _heading_level(item)
        if level is None:
            if text:
                parts.append(text)
            continue
        if not text:
            continue
        if parts:
            blocks.append(Block("\n\n".join(parts), None, section_path))
            parts = []
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
        section_path = tuple(title for _, title in stack)
        parts.append(text)
    if parts:
        blocks.append(Block("\n\n".join(parts), None, section_path))
    return ParsedDocument(tuple(blocks), pages)
