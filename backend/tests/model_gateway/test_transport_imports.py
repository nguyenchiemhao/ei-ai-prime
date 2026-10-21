"""The egress seam (EA-24 plan T4, FND-10 later): under ``src`` only the gateway transport
imports the OpenAI SDK or an HTTP client library."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
HTTP_LIBRARIES = ("openai", "httpx", "httpx2", "httpcore", "httpcore2", "requests", "aiohttp")
ALLOWED = {"ei_ai/model_gateway/transport.py"}


def _top_level_imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_only_the_transport_imports_http_libraries() -> None:
    offenders = sorted(
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path.relative_to(SRC).as_posix() not in ALLOWED
        and _top_level_imports(path.read_text("utf-8")) & set(HTTP_LIBRARIES)
    )

    assert offenders == []


def test_the_transport_is_where_the_sdk_is_imported() -> None:
    source = (SRC / "ei_ai/model_gateway/transport.py").read_text("utf-8")

    assert {"openai", "httpx2"} <= _top_level_imports(source)
