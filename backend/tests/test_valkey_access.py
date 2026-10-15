"""AC4 (static side): Valkey is reached only through ``ei_ai.cache.TenantCache``.

This is an accident-catcher, not a barrier against someone who means to get around it: the runtime
scan of Valkey (tests/integration/isolation) is the backstop for what a static scan cannot see.

A module that gets hold of a Valkey client could write a key without the Organization, so under
``src`` only the cache package may import ``redis`` or ``valkey``. The scan also rejects the ways
around that: importing a client name that another module re-exports (``from ei_ai.readiness import
aioredis``), importing anything from ``ei_ai.cache`` that is not its public API, and importing a
client with ``importlib.import_module`` / ``__import__``.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CACHE_PACKAGE = "ei_ai/cache/"
CLIENT_PACKAGES = frozenset({"redis", "valkey"})
CLIENT_NAMES = frozenset({"redis", "valkey", "aioredis", "Redis", "StrictRedis", "from_url"})
# What code outside the cache package may take from it: the wrapper, its client factory, the key
# helpers, the ping. A new public name in ei_ai.cache must be added here (and say why in the PR).
CACHE_PUBLIC_API = frozenset(
    {
        "TenantCache",
        "create_valkey_client",
        "TENANT_KEY_PATTERN",
        "tenant_key",
        "is_tenant_key",
        "check_valkey",
    }
)
DYNAMIC_IMPORTS = frozenset({"import_module", "__import__"})
CACHE_INTERNALS = frozenset({"aioredis", "_client"})


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _names_dunder_import(call: ast.Call) -> bool:
    return (
        len(call.args) >= 2
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "__import__"
    )


def _violations(source: str) -> list[str]:
    """What is wrong with one module outside the cache package (empty means it is fine)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [
                f"imports {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in CLIENT_PACKAGES
            ]
            found += [
                f"imports the cache submodule {alias.name}"
                for alias in node.names
                if alias.name.startswith("ei_ai.cache.")
            ]
        elif isinstance(node, ast.Attribute):
            if node.attr in CACHE_INTERNALS:
                found.append(f"reads the cache internals ({node.attr})")
            elif (
                node.attr == "modules"
                and isinstance(node.value, ast.Name)
                and node.value.id == "sys"
            ):
                found.append("reads sys.modules")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module = node.module
            names = [alias.name for alias in node.names]
            if module.split(".")[0] in CLIENT_PACKAGES:
                found.append(f"imports from {module}")
            elif module == "ei_ai.cache" or module.startswith("ei_ai.cache."):
                found += [f"imports {n} from {module}" for n in names if n not in CACHE_PUBLIC_API]
            else:
                found += [
                    f"imports the client name {n} from {module}" for n in names if n in CLIENT_NAMES
                ]
        elif (
            isinstance(node, ast.Call)
            and _call_name(node) == "getattr"
            and _names_dunder_import(node)
        ):
            found.append("reaches __import__ with getattr")
        elif isinstance(node, ast.Call) and _call_name(node) in DYNAMIC_IMPORTS:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                found.append("imports a module dynamically with a name that cannot be checked")
            elif first.value.split(".")[0] in CLIENT_PACKAGES:
                found.append(f"imports {first.value} dynamically")
    return found


def valkey_importers(root: Path) -> list[str]:
    """One message per module under ``root`` that reaches Valkey around the cache package."""
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(CACHE_PACKAGE):
            continue
        module = relative.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        problems += [
            f"{module} talks to Valkey directly ({violation}); use ei_ai.cache.TenantCache"
            for violation in _violations(path.read_text(encoding="utf-8"))
        ]
    return problems


def test_only_the_cache_package_talks_to_valkey() -> None:
    assert valkey_importers(BACKEND / "src") == []


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, source in files.items():
        path = tmp_path / "ei_ai" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def test_the_scanner_ignores_the_cache_package_and_the_public_api(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "cache/tenant_cache.py": "from redis import asyncio as aioredis\n",
            "cache/ping.py": "import redis\n",
            "api/fine.py": "import json, importlib\nfrom ei_ai.cache import TenantCache\n",
            "api/client.py": "from ei_ai.cache import create_valkey_client\n",
            "readiness.py": "from ei_ai.cache.ping import check_valkey\n",
            "api/keys.py": "from ei_ai.cache.keys import tenant_key\n",
            "api/dynamic_ok.py": "import importlib\nimportlib.import_module('json')\n",
        },
    )

    assert valkey_importers(root) == []


def test_the_scanner_reports_every_way_around_the_cache_package(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "api/sneaky.py": "from redis import asyncio as aioredis\n",
            "jobs/direct.py": "import redis\n",
            "jobs/other.py": "import valkey.asyncio\n",
            "readiness.py": "from redis import asyncio as aioredis\n",
            "api/reexport.py": "from ei_ai.readiness import aioredis\n",
            "api/private.py": "from ei_ai.cache.tenant_cache import aioredis\n",
            "api/importlib_literal.py": "import importlib\nimportlib.import_module('redis.aio')\n",
            "api/dunder.py": "client = __import__('redis')\n",
            "api/dynamic.py": "import importlib\nimportlib.import_module(name)\n",
            "api/submodule.py": "import ei_ai.cache.tenant_cache as t\nt.aioredis\n",
            "api/internal.py": "from ei_ai.cache import TenantCache\nTenantCache(x, y)._client\n",
            "api/modules.py": "import sys\nclient = sys.modules['redis.asyncio']\n",
            "api/getattr_import.py": "import builtins\nf = getattr(builtins, '__import__')\n",
        },
    )

    reported: dict[str, str] = {}
    for line in valkey_importers(root):
        module = line.split(" talks")[0]
        reported[module] = f"{reported.get(module, '')} | {line}"

    assert sorted(reported) == [
        "ei_ai.api.dunder",
        "ei_ai.api.dynamic",
        "ei_ai.api.getattr_import",
        "ei_ai.api.importlib_literal",
        "ei_ai.api.internal",
        "ei_ai.api.modules",
        "ei_ai.api.private",
        "ei_ai.api.reexport",
        "ei_ai.api.sneaky",
        "ei_ai.api.submodule",
        "ei_ai.jobs.direct",
        "ei_ai.jobs.other",
        "ei_ai.readiness",
    ]
    assert all("use ei_ai.cache.TenantCache" in line for line in reported.values())
    assert "client name aioredis from ei_ai.readiness" in reported["ei_ai.api.reexport"]
    assert "aioredis from ei_ai.cache.tenant_cache" in reported["ei_ai.api.private"]
    assert "redis.aio dynamically" in reported["ei_ai.api.importlib_literal"]
    assert "cannot be checked" in reported["ei_ai.api.dynamic"]
    assert "imports the cache submodule" in reported["ei_ai.api.submodule"]
    assert "reads the cache internals" in reported["ei_ai.api.internal"]
    assert "sys.modules" in reported["ei_ai.api.modules"]
    assert "__import__ with getattr" in reported["ei_ai.api.getattr_import"]
