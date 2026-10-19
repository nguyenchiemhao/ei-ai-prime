"""The provisioning package is reachable only from the platform plane (D46, D32).

It takes the Organization id from the Platform Operator's command line. An HTTP route that
imported it could pass a client-sent Organization id, so under ``src`` only the CLI, the demo
seed and the package itself may import it.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PACKAGE = "ei_ai.provisioning"
ALLOWED_PREFIXES = ("ei_ai/provisioning/", "ei_ai/seed/")
ALLOWED_FILES = ("ei_ai/cli.py",)


def _from_module(node: ast.ImportFrom, package: list[str]) -> str:
    """Absolute module of a ``from ... import``; relative imports resolve against ``package``."""
    if node.level == 0:
        return node.module or ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imported_modules(source: str, package: list[str]) -> set[str]:
    """Every module (and ``module.name``) a source imports, relative imports made absolute.

    Dynamic imports (``importlib.import_module``) are invisible to this scan; the boundary is
    a review rule as well, this test catches the ordinary import statements.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _from_module(node, package)
            modules.add(module)
            modules.update(f"{module}.{alias.name}" for alias in node.names)
    return modules


def _imports_provisioning(source: str, package: list[str]) -> bool:
    """True when the source imports the provisioning package or one of its modules."""
    imported = _imported_modules(source, package)
    return any(m == PACKAGE or m.startswith(f"{PACKAGE}.") for m in imported)


def stray_imports(root: Path) -> list[str]:
    """One message per module under ``root`` that imports the provisioning package but may not."""
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        allowed = relative in ALLOWED_FILES or relative.startswith(ALLOWED_PREFIXES)
        package = list(path.relative_to(root).parent.parts)
        source = path.read_text(encoding="utf-8")
        if not allowed and _imports_provisioning(source, package):
            problems.append(f"{relative} imports {PACKAGE}; only the CLI and the seed may")
    return problems


def test_only_cli_and_seed_import_provisioning() -> None:
    assert stray_imports(BACKEND / "src") == []


def test_the_scan_reports_a_stray_import(tmp_path: Path) -> None:
    files = {
        "ei_ai/cli.py": "from ei_ai.provisioning.commands import run_provisioning_command\n",
        "ei_ai/seed/demo.py": "from ei_ai.provisioning import rows\n",
        "ei_ai/provisioning/service.py": "from ei_ai.provisioning.rows import insert_member\n",
        "ei_ai/api/orgs.py": "from ei_ai.provisioning.service import create_organization\n",
        "ei_ai/api/users.py": "import ei_ai.provisioning.service as s\n",
        "ei_ai/api/other.py": "from ei_ai import provisioning\n",
        "ei_ai/api/fine.py": "from ei_ai.db import tenant\n",
        "ei_ai/api/relative.py": "from ..provisioning.service import create_organization\n",
        "ei_ai/api/relative_package.py": "from .. import provisioning\n",
        "ei_ai/api/v1/deep.py": "from ...provisioning import service\n",
        "ei_ai/api/sibling.py": "from . import fine\nfrom .provisioning_like import x\n",
        "ei_ai/seed/relative_ok.py": "from ..provisioning import rows\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert stray_imports(tmp_path) == [
        "ei_ai/api/orgs.py imports ei_ai.provisioning; only the CLI and the seed may",
        "ei_ai/api/other.py imports ei_ai.provisioning; only the CLI and the seed may",
        "ei_ai/api/relative.py imports ei_ai.provisioning; only the CLI and the seed may",
        "ei_ai/api/relative_package.py imports ei_ai.provisioning; only the CLI and the seed may",
        "ei_ai/api/users.py imports ei_ai.provisioning; only the CLI and the seed may",
        "ei_ai/api/v1/deep.py imports ei_ai.provisioning; only the CLI and the seed may",
    ]
