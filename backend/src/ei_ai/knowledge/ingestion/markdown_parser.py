"""Markdown parsing: heading sections from the original source lines."""

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ei_ai.knowledge.ingestion.model import Block, ParsedDocument
from ei_ai.knowledge.ingestion.text_parser import decode_text


def _heading_title(inline: Token) -> str:
    """The plain text of a heading's inline token (markup dropped)."""
    children = inline.children or []
    return "".join(c.content for c in children if c.type in ("text", "code_inline")).strip()


def _find_headings(source: str) -> list[tuple[int, int, str]]:
    """``(first line, level, title)`` of every top-level ATX or setext heading, in order."""
    tokens = MarkdownIt("commonmark").parse(source)
    headings: list[tuple[int, int, str]] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0 and token.map:
            title = _heading_title(tokens[index + 1])
            headings.append((token.map[0], int(token.tag[1]), title))
    return headings


def parse_markdown(data: bytes) -> ParsedDocument:
    """One block per heading section (heading line included); headings in code fences do not
    count. Text before the first heading has an empty path."""
    source = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    headings = _find_headings(source)
    starts = [0] + [line for line, _, _ in headings]
    ends = starts[1:] + [len(lines)]
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    path: tuple[str, ...] = ()
    for position, (start, end) in enumerate(zip(starts, ends, strict=True)):
        if position > 0:
            _, level, title = headings[position - 1]
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = tuple(name for _, name in stack)
        text = "\n".join(lines[start:end])
        if text.strip():
            blocks.append(Block(text, None, path))
    return ParsedDocument(tuple(blocks), None)
