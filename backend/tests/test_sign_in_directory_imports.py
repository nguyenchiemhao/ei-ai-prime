"""R42: the sign-in lookup connection is reachable only through ``ei_ai.auth.directory``.

``ei_ai_signin`` reads ``users(id, org_id, email)`` of every Organization: the only cross-tenant
read in the codebase. So under ``src`` only the settings read ``SIGNIN_DATABASE_URL``, only
``main.py`` hands the URL to the directory, only the directory builds an engine from it, and only
the sign-in and password-reset flows (and the app factory and the auth router that wire them)
import it.
Dynamic imports and hand-built URLs are invisible to this scan; the boundary is a review rule as
well, this test catches the ordinary ways in.
"""

import ast
from pathlib import Path

from ei_ai.auth.directory import SignInDirectory

BACKEND = Path(__file__).resolve().parents[1]
MODULE = "ei_ai.auth.directory"
SETTING = "signin_database_url"
ENV_NAMES = ("SIGNIN_DATABASE_URL", "SIGNIN_DB_PASSWORD")
SETTING_FILES = frozenset({"ei_ai/settings.py", "ei_ai/main.py", "ei_ai/auth/directory.py"})
ENV_FILES = frozenset({"ei_ai/settings.py"})
IMPORTERS = frozenset(
    {"ei_ai/main.py", "ei_ai/api/auth.py", "ei_ai/auth/sign_in.py", "ei_ai/auth/password_reset.py"}
)


def _from_module(node: ast.ImportFrom, package: list[str]) -> str:
    """Absolute module of a ``from ... import``; relative imports resolve against ``package``."""
    if node.level == 0:
        return node.module or ""
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports_directory(tree: ast.AST, package: list[str]) -> bool:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _from_module(node, package)
            modules.add(module)
            modules.update(f"{module}.{alias.name}" for alias in node.names)
    return any(m == MODULE or m.startswith(f"{MODULE}.") for m in modules)


def _names_the_setting(tree: ast.AST) -> bool:
    """An attribute, name, argument, keyword or string spelling ``signin_database_url``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == SETTING:
            return True
        if isinstance(node, ast.Name) and node.id == SETTING:
            return True
        if isinstance(node, (ast.arg, ast.keyword)) and node.arg == SETTING:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and SETTING in node.value:
            return True
    return False


def _names_the_env(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(name in node.value for name in ENV_NAMES)
        for node in ast.walk(tree)
    )


def boundary_problems(root: Path) -> list[str]:
    """One message per rule a module under ``root`` breaks."""
    problems = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = list(path.relative_to(root).parent.parts)
        if relative not in ENV_FILES and _names_the_env(tree):
            problems.append(f"{relative} reads the sign-in role's environment; only settings may")
        if relative not in SETTING_FILES and _names_the_setting(tree):
            problems.append(f"{relative} uses {SETTING}; only settings, main and the directory may")
        if relative not in IMPORTERS and _imports_directory(tree, package):
            problems.append(f"{relative} imports {MODULE}; only the sign-in wiring may")
    return problems


def test_only_directory_uses_signin_url() -> None:
    assert boundary_problems(BACKEND / "src") == []


def test_the_scan_reports_every_way_in(tmp_path: Path) -> None:
    files = {
        "ei_ai/settings.py": 'x = env["SIGNIN_DATABASE_URL"]\n',
        "ei_ai/main.py": "from ei_ai.auth.directory import SignInDirectory\n"
        "d = SignInDirectory(settings.signin_database_url)\n",
        "ei_ai/auth/directory.py": "def f(signin_database_url: str) -> None: ...\n",
        "ei_ai/api/auth.py": "from ..auth.directory import SignInDirectory\n",
        "ei_ai/auth/sign_in.py": "from .directory import Account\n",
        "ei_ai/auth/password_reset.py": "from ei_ai.auth import directory\n",
        "ei_ai/api/workspaces.py": "from ei_ai.auth.directory import SignInDirectory\n",
        "ei_ai/api/orgs.py": "import ei_ai.auth.directory as d\n",
        "ei_ai/api/relative.py": "from ..auth import directory\n",
        "ei_ai/db/engine.py": "e = create_async_engine(settings.signin_database_url)\n",
        "ei_ai/db/getattr.py": 'e = getattr(settings, "signin_database_url")\n',
        "ei_ai/db/keyword.py": "s = Settings(signin_database_url=u)\n",
        "ei_ai/cli.py": 'u = os.environ["SIGNIN_DATABASE_URL"]\n',
        "ei_ai/seed/pw.py": 'p = os.environ.get("SIGNIN_DB_PASSWORD")\n',
        "ei_ai/api/fine.py": "from ei_ai.auth import principal\nfrom .directory_like import x\n",
    }
    for relative, source in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(source, encoding="utf-8")

    assert boundary_problems(tmp_path) == [
        "ei_ai/api/orgs.py imports ei_ai.auth.directory; only the sign-in wiring may",
        "ei_ai/api/relative.py imports ei_ai.auth.directory; only the sign-in wiring may",
        "ei_ai/api/workspaces.py imports ei_ai.auth.directory; only the sign-in wiring may",
        "ei_ai/cli.py reads the sign-in role's environment; only settings may",
        "ei_ai/db/engine.py uses signin_database_url; only settings, main and the directory may",
        "ei_ai/db/getattr.py uses signin_database_url; only settings, main and the directory may",
        "ei_ai/db/keyword.py uses signin_database_url; only settings, main and the directory may",
        "ei_ai/seed/pw.py reads the sign-in role's environment; only settings may",
    ]


def test_the_directory_keeps_its_engine_private() -> None:
    # Building the engine does not connect, so no database is needed.
    directory = SignInDirectory("postgresql://ei_ai_signin:pw@db:5432/ei_ai")

    assert [name for name in vars(directory) if not name.startswith("_")] == []
    assert [name for name in dir(SignInDirectory) if not name.startswith("_")] == [
        "dispose",
        "find_accounts",
    ]
