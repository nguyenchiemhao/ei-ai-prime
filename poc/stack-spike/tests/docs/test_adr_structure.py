"""EA-11 AC1, AC2, AC5, AC6: structural checks of docs/architecture/adr-001-tech-stack.md.

The content (is the choice sensible, is each licence claim correct) is checked by the reviewer;
these tests make sure no required part is missing or left as a placeholder.
"""

import os
import re
from pathlib import Path

import pytest

DEFAULT_ADR_PATH = Path(__file__).resolve().parents[4] / "docs/architecture/adr-001-tech-stack.md"

COMPONENT_TITLES = {
    "3.1": "Backend language and framework",
    "3.2": "Database and tenant isolation",
    "3.3": "Vector store",
    "3.4": "Keyword search",
    "3.5": "File storage and per-Organization encryption",
    "3.6": "Local model serving",
    "3.7": "Models: LLM, embedding, reranker",
    "3.8": "Admin frontend",
    "3.9": "Widget",
    "3.10": "Background jobs",
    "3.11": "Rate-limit store and cache",
    "3.12": "Packaging and local environment",
    "3.13": "Authentication and identity tokens",
    "3.14": "Egress proxy",
    "3.15": "Logging, tracing and masking",
}

SECTION_TITLES = {
    "1": "Context",
    "2": "Selection criteria",
    "3": "Decisions per component",
    "4": "Architecture overview",
    "5": "Foundations F1–F15 mapping",
    "6": "Self-hosted single-Organization install",
    "7": "Frontend fit with DSN-01",
    "8": "Dev machine fit and RAM budget",
    "9": "Isolation PoC results",
    "10": "Licence notes and red flags",
    "11": "Consequences, risks and revisit triggers",
    "12": "References",
}

PLACEHOLDER_CELLS = {"", "-", "?", "tbd", "todo", "n/a"}
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module")
def adr() -> str:
    path = Path(os.environ.get("ADR_PATH", DEFAULT_ADR_PATH))
    assert path.is_file(), f"ADR not found at {path}"
    return path.read_text(encoding="utf-8")


def _split(text: str, level: int) -> list[tuple[str, str, str]]:
    """Split on headings of one level into (number, title, body); a body ends at the next heading
    of the same or a higher level."""
    marker = "#" * level
    heading = re.compile(rf"^{marker} (\d+(?:\.\d+)?)\.? (.*)$", re.MULTILINE)
    higher = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)
    parts = []
    for match in heading.finditer(text):
        following = higher.search(text, match.end())
        end = following.start() if following else len(text)
        parts.append((match.group(1), match.group(2).strip(), text[match.end() : end]))
    return parts


def _titles(text: str, level: int) -> dict[str, str]:
    return {number: title for number, title, _ in _split(text, level)}


def _section(text: str, number: str) -> str:
    """Body of `## <number>.` (level 2) or `### <number>` (level 3)."""
    level = 3 if "." in number else 2
    return next(body for num, _, body in _split(text, level) if num == number)


def _is_separator(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-+:?", cell) for cell in row)


def _tables(body: str) -> list[list[list[str]]]:
    """Markdown tables of a section body as rows of cells (separator row removed, header kept)."""
    body = FENCE.sub("", body)
    tables, current = [], []
    for line in body.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            current.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif current:
            tables.append([row for row in current if not _is_separator(row)])
            current = []
    return tables


def _has_mermaid(body: str) -> bool:
    return re.search(r"^```mermaid\b", body, re.MULTILINE) is not None


def test_adr_file_exists_with_status_and_ticket(adr):
    assert re.search(r"^- Status: (Proposed|Accepted)\b", adr, re.MULTILINE)
    assert "EA-11" in adr


def test_has_required_headings(adr):
    assert _titles(adr, 2) == SECTION_TITLES
    assert _titles(adr, 3) == COMPONENT_TITLES


def test_lists_selection_criteria_table(adr):
    rows = [row for table in _tables(_section(adr, "2")) for row in table]
    criteria = [row for row in rows if re.fullmatch(r"C\d+", row[0])]

    assert len(criteria) >= 5


@pytest.mark.parametrize("number", COMPONENT_TITLES)
def test_every_main_component_has_at_least_two_options(adr, number):
    tables = _tables(_section(adr, number))

    assert tables, f"section {number} has no options table"
    header, *options = tables[0]
    assert header[0].lower().startswith("option")
    assert len(options) >= 2


@pytest.mark.parametrize("number", COMPONENT_TITLES)
def test_every_main_component_has_choice_and_reasons(adr, number):
    body = _section(adr, number)

    assert re.search(r"^\*\*Choice:\*\*\s*\S+", body, re.MULTILINE)
    assert re.search(r"^\*\*Reasons:\*\*", body, re.MULTILINE)


def _foundation_rows(adr: str) -> list[list[str]]:
    tables = _tables(_section(adr, "5"))
    assert tables, "section 5 has no table"
    return tables[0][1:]


def test_maps_every_foundation_f1_to_f15(adr):
    rows = _foundation_rows(adr)

    assert [row[0] for row in rows] == [f"F{n}" for n in range(1, 16)]


def test_no_foundation_row_has_empty_or_placeholder_cell(adr):
    for row in _foundation_rows(adr):
        assert len(row) == 5, f"{row[0]} must have 5 cells"
        for cell in row:
            assert cell.strip().lower() not in PLACEHOLDER_CELLS, f"{row[0]} has a placeholder cell"


def test_has_no_tbd_or_todo_markers(adr):
    assert re.search(r"\b(TBD|TODO)\b", adr) is None


def test_has_self_host_section_with_topology_and_config_differences(adr):
    body = _section(adr, "6")
    tables = _tables(body)

    assert _has_mermaid(body)
    assert any("Self-hosted" in " ".join(table[0]) for table in tables)
    assert "D6" in body


def test_frontend_fit_section_covers_dsn01_requirements(adr):
    body = _section(adr, "7").lower()
    required = [
        ["ibm plex"],
        ["vietnamese"],
        ["token"],
        ["iframe"],
        ["settokenprovider"],
        ["stream"],
        ["abort", "stop"],
        ["i18n"],
        ["aria", "accessib"],
        ["bundle"],
    ]

    for alternatives in required:
        assert any(word in body for word in alternatives), f"section 7 misses {alternatives}"


def test_ram_budget_mentions_16_gb_and_one_command(adr):
    body = _section(adr, "8")

    assert "16 GB" in body
    assert "--profile model up" in body


def test_architecture_overview_has_mermaid_diagram(adr):
    assert _has_mermaid(_section(adr, "4"))
