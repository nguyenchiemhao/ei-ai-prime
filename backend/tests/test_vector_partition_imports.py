"""The partition commands take a raw Organization id, so only the migrator plane may import them.

Under ``src`` only the CLI (``ei-ai db vector-partition``) and the vectors package itself may
import ``ei_ai.vectors.partitions``. A route that imported it could pass a client-sent id.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULE = "ei_ai.vectors.partitions"
PACKAGE = "ei_ai.vectors"
ALLOWED = ("ei_ai/cli.py",)
ALLOWED_PREFIXES = ("ei_ai/vectors/",)


def _from_module(node: ast.ImportFrom, package: list[str]) -> str:
    if node.level == 0:
        return node.module or ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports_partitions(source: str, package: list[str]) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == MODULE for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = _from_module(node, package)
            if module == MODULE or module.startswith(f"{MODULE}."):
                return True
            if module == PACKAGE and any(alias.name == "partitions" for alias in node.names):
                return True
    return False


def stray_imports(root: Path) -> list[str]:
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        package = list(path.relative_to(root).parent.parts)
        allowed = relative in ALLOWED or relative.startswith(ALLOWED_PREFIXES)
        source = path.read_text(encoding="utf-8")
        if not allowed and _imports_partitions(source, package):
            problems.append(f"{relative} imports {MODULE}; only the CLI and vectors may")
    return problems


def test_vector_partition_importers() -> None:
    assert stray_imports(BACKEND / "src") == []


def test_the_scan_reports_a_stray_import(tmp_path: Path) -> None:
    files = {
        "ei_ai/cli.py": "from ei_ai.vectors.partitions import create_vector_partition\n",
        "ei_ai/vectors/search.py": "from ei_ai.vectors import partitions\n",
        "ei_ai/api/a.py": "from ei_ai.vectors.partitions import create_vector_partition\n",
        "ei_ai/api/b.py": "from ei_ai.vectors import partitions\n",
        "ei_ai/api/c.py": "import ei_ai.vectors.partitions as parts\n",
        "ei_ai/api/d.py": "from ..vectors.partitions import drop_vector_partition\n",
        "ei_ai/api/fine.py": "from ei_ai.vectors.search import nearest\n",
        "ei_ai/seed/cli.py": "from ei_ai.vectors.partitions import partition_name\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert stray_imports(tmp_path) == [
        *(f"ei_ai/api/{name}.py imports {MODULE}; only the CLI and vectors may" for name in "abcd"),
        f"ei_ai/seed/cli.py imports {MODULE}; only the CLI and vectors may",
    ]
