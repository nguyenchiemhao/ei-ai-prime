"""Markdown parsing."""

from ei_ai.knowledge.ingestion.extract import extract_document
from ei_ai.knowledge.ingestion.markdown_parser import parse_markdown

_SOURCE = """Intro line.

# Overtime Policy 2026

Body.

```
# not a heading
```

## 3. Approvals

Text.

Setext Title
------------

More.
"""


def test_md_headings_ignore_code_fences() -> None:
    parsed = parse_markdown(_SOURCE.encode())
    paths = [block.heading_path for block in parsed.blocks]
    assert paths == [
        (),
        ("Overtime Policy 2026",),
        ("Overtime Policy 2026", "3. Approvals"),
        ("Overtime Policy 2026", "Setext Title"),
    ]
    assert "# not a heading" in parsed.blocks[1].text
    assert parsed.blocks[1].text.startswith("# Overtime Policy 2026")


def test_md_heading_markup_is_dropped_and_levels_pop() -> None:
    parsed = parse_markdown(b"# A\n\n## **B** `c`\n\n# D\n")
    assert [b.heading_path for b in parsed.blocks] == [("A",), ("A", "B c"), ("D",)]


def test_md_chunks_carry_heading_path() -> None:
    result = extract_document("md", _SOURCE.encode(), None)
    assert result.chunks[2].heading_path == ("Overtime Policy 2026", "3. Approvals")
    assert result.chunks[0].heading_path == ()


def test_md_txt_pages_estimated() -> None:
    assert extract_document("md", b"# Short\n\ntext", None).page_count == 1
    assert extract_document("txt", b"x " * 1500, None).page_count == 1
    assert extract_document("txt", ("word " * 1000).encode(), None).page_count == 2
