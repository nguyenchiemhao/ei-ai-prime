"""EA-36 fail closed, enforced on the source: no code in ``ei_ai.knowledge.retrieval`` may call
``nearest`` without a permission filter or build a ``VectorFilter`` that means "any collection".

``where=None`` (no filter) and ``collection_ids=None`` (any collection, also the default) are for
the operator ``index search`` only, which lives outside this package.
"""

import ast
from pathlib import Path

import ei_ai.knowledge.retrieval as retrieval_package

PACKAGE = Path(retrieval_package.__file__).parent


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def violations(source: str, filename: str = "<source>") -> list[str]:
    """Every fail-open call in ``source``, as ``file:line reason``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        where = f"{filename}:{node.lineno}"
        if name == "nearest":
            if "where" not in keywords:
                found.append(f"{where} nearest without where=")
            elif _is_none(keywords["where"]):
                found.append(f"{where} nearest(where=None)")
        elif name == "VectorFilter":
            given = node.args[0] if node.args else keywords.get("collection_ids")
            if given is None:
                found.append(f"{where} VectorFilter without collection_ids (defaults to None)")
            elif _is_none(given):
                found.append(f"{where} VectorFilter(collection_ids=None)")
    return found


def test_retrieval_package_never_fails_open() -> None:
    files = sorted(PACKAGE.rglob("*.py"))
    assert any(path.name == "service.py" for path in files)
    found = [
        item for path in files for item in violations(path.read_text(encoding="utf-8"), path.name)
    ]
    assert found == []


def test_the_check_catches_every_fail_open_shape() -> None:
    bad = (
        "nearest(s, t, q, 20, model=m, where=None)\n"
        "nearest(s, t, q, 20, model=m)\n"
        "search.nearest(s, t, q, 20, model=m, where=None)\n"
        "VectorFilter(collection_ids=None, access_levels=('public',))\n"
        "VectorFilter(None)\n"
        "VectorFilter(access_levels=('public',))\n"
    )
    assert len(violations(bad)) == 6
    good = (
        "nearest(s, t, q, 20, model=m, where=permission_filter(p, c, f))\n"
        "VectorFilter(collection_ids=ids, access_levels=levels)\n"
        "VectorFilter(ids, levels)\n"
    )
    assert violations(good) == []
