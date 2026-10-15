"""The verified contexts are built only by the code that verified the identity (D32).

``TenantCache`` takes a ``TenantContext`` or a ``JobContext`` instead of an id, which only keeps
application code from addressing another Organization's keys if nobody can build such a context
from a header or a payload. So under ``src`` only ``require_tenant`` constructs a
``TenantContext`` and only ``run_tenant_job`` constructs a ``JobContext``.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BUILDERS = {
    "TenantContext": "ei_ai/tenancy/context.py",
    "JobContext": "ei_ai/jobs/runner.py",
}


def _constructed(source: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in BUILDERS:
                names.add(name)
    return names


def stray_constructions(root: Path) -> list[str]:
    """One message per module under ``root`` that builds a context it may not."""
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        problems += [
            f"{relative} constructs {name}; only {BUILDERS[name]} may"
            for name in sorted(_constructed(path.read_text(encoding="utf-8")))
            if relative != BUILDERS[name]
        ]
    return problems


def test_only_the_verifying_code_constructs_a_tenant_or_job_context() -> None:
    assert stray_constructions(BACKEND / "src") == []


def test_the_scan_reports_a_context_built_elsewhere(tmp_path: Path) -> None:
    files = {
        "ei_ai/tenancy/context.py": "x = TenantContext(org_id=1, user_id=2)\n",
        "ei_ai/jobs/runner.py": "x = JobContext(org_id=1, session=None)\n",
        "ei_ai/api/header.py": "ctx = TenantContext(org_id=UUID(h), user_id=u)\n",
        "ei_ai/jobs/other.py": "import m\nctx = m.JobContext(org_id=o, session=s)\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert stray_constructions(tmp_path) == [
        "ei_ai/api/header.py constructs TenantContext; only ei_ai/tenancy/context.py may",
        "ei_ai/jobs/other.py constructs JobContext; only ei_ai/jobs/runner.py may",
    ]
