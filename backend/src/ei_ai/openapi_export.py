"""Export the app's OpenAPI document: ``python -m ei_ai.openapi_export <path>``.

Deterministic (sorted keys, 2-space indent, LF) so the committed copy can be compared byte for byte.
"""

import json
import sys
from pathlib import Path

from ei_ai.main import create_app


def render_openapi() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_openapi(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_openapi(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m ei_ai.openapi_export <path>")
    write_openapi(Path(sys.argv[1]))
