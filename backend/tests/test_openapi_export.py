import os
from pathlib import Path

from ei_ai.openapi_export import render_openapi, write_openapi

REPO_ROOT = Path(os.environ.get("EI_AI_REPO_ROOT", Path(__file__).resolve().parents[2]))
COMMITTED = REPO_ROOT / "packages" / "api-types" / "openapi.json"


def test_render_is_sorted_two_space_indented_and_lf() -> None:
    text = render_openapi()

    assert text.endswith("}\n")
    assert "\r" not in text
    assert text.startswith('{\n  "components"')


def test_write_openapi_writes_the_rendered_text(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "openapi.json"

    write_openapi(target)

    assert target.read_text(encoding="utf-8") == render_openapi()


def test_committed_openapi_matches_the_app() -> None:
    assert COMMITTED.is_file(), f"missing {COMMITTED}; run: npm run backend -- openapi-export"
    assert COMMITTED.read_text(encoding="utf-8") == render_openapi(), (
        "packages/api-types/openapi.json is stale; regenerate it with: "
        "npm run backend -- openapi-export, then npm run generate -w @ei-ai/api-types"
    )
