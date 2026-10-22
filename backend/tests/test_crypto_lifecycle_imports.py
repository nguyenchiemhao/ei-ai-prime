"""The key modules take a raw Organization id, so only the platform plane may import them.

Under ``src`` only the crypto package itself, the provisioning service and the demo seed may
import ``ei_ai.crypto.lifecycle``; only the crypto package may import ``ei_ai.crypto.key_rows``
(the SQL that inserts, reads and erases a key row). A route that imported either could pass a
client-sent id.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULE = "ei_ai.crypto.lifecycle"
# fenced module -> (path prefixes under src allowed to import it, the name used in the message)
FENCES = {
    MODULE: (
        ("ei_ai/crypto/", "ei_ai/provisioning/", "ei_ai/seed/"),
        "crypto, provisioning and seed",
    ),
    "ei_ai.crypto.key_rows": (("ei_ai/crypto/",), "crypto"),
}


def _from_module(node: ast.ImportFrom, package: list[str]) -> str:
    if node.level == 0:
        return node.module or ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(source: str, package: list[str], target: str) -> bool:
    parent, _, leaf = target.rpartition(".")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name == target for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = _from_module(node, package)
            if module == target or module.startswith(f"{target}."):
                return True
            if module == parent and any(alias.name == leaf for alias in node.names):
                return True
    return False


def stray_imports(root: Path) -> list[str]:
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        package = list(path.relative_to(root).parent.parts)
        source = path.read_text(encoding="utf-8")
        for target, (allowed, owners) in FENCES.items():
            if not relative.startswith(allowed) and _imports(source, package, target):
                problems.append(f"{relative} imports {target}; only {owners} may")
    return problems


def test_lifecycle_and_key_rows_importers() -> None:
    assert stray_imports(BACKEND / "src") == []


def test_the_scan_reports_a_stray_import(tmp_path: Path) -> None:
    files = {
        "ei_ai/crypto/cipher.py": "from ei_ai.crypto.lifecycle import create_org_key\n",
        "ei_ai/provisioning/service.py": "from ei_ai.crypto.lifecycle import create_org_key\n",
        "ei_ai/seed/demo.py": "from ei_ai.crypto import lifecycle\n",
        "ei_ai/api/a.py": "from ei_ai.crypto.lifecycle import destroy_org_key\n",
        "ei_ai/api/b.py": "from ei_ai.crypto import lifecycle\n",
        "ei_ai/api/c.py": "import ei_ai.crypto.lifecycle as life\n",
        "ei_ai/api/d.py": "from ..crypto.lifecycle import destroy_org_key\n",
        "ei_ai/api/fine.py": "from ei_ai.crypto.cipher import OrgCipher\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert stray_imports(tmp_path) == [
        f"ei_ai/api/{name}.py imports {MODULE}; only crypto, provisioning and seed may"
        for name in "abcd"
    ]


def test_the_scan_reports_a_stray_key_rows_import(tmp_path: Path) -> None:
    files = {
        "ei_ai/crypto/cipher.py": "from ei_ai.crypto.key_rows import read_key_row\n",
        "ei_ai/crypto/lifecycle.py": "from .key_rows import insert_key_row\n",
        "ei_ai/api/a.py": "from ei_ai.crypto.key_rows import mark_key_destroyed\n",
        "ei_ai/api/b.py": "from ei_ai.crypto import key_rows\n",
        "ei_ai/api/c.py": "import ei_ai.crypto.key_rows as rows\n",
        "ei_ai/api/d.py": "from ..crypto.key_rows import insert_key_row\n",
        "ei_ai/provisioning/e.py": "from ei_ai.crypto.key_rows import insert_key_row\n",
        "ei_ai/seed/f.py": "from ei_ai.crypto import key_rows\n",
        "ei_ai/api/fine.py": "from ei_ai.crypto.cipher import OrgCipher\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert stray_imports(tmp_path) == [
        f"{path} imports ei_ai.crypto.key_rows; only crypto may"
        for path in (
            "ei_ai/api/a.py",
            "ei_ai/api/b.py",
            "ei_ai/api/c.py",
            "ei_ai/api/d.py",
            "ei_ai/provisioning/e.py",
            "ei_ai/seed/f.py",
        )
    ]
