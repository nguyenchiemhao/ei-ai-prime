"""``ei-ai org create`` end to end against the real database (FND-04 AC1, AC2).

Synchronous tests: the CLI runs its own event loop with ``asyncio.run``.
"""

import asyncio
import os
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ei_ai import cli
from ei_ai.auth.set_password import hash_secret
from ei_ai.db.engine import to_sqlalchemy_url
from ei_ai.db.tenant import tenant_transaction
from support.tenants import purge_org_ids

pytestmark = pytest.mark.integration

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
OUTPUT = re.compile(
    rf"^Organization created: ({UUID}) \((.+)\)\n"
    rf"Workspace created: ({UUID}) \(Default\)\n"
    rf"Org Owner created: ({UUID}) \((.+)\)\n"
    r"Set-password link \(valid 24 h, shown once\): http://localhost:3000/set-password#token="
    rf"({UUID})\.([A-Za-z0-9_-]{{43}})\n$"
)


async def _token_hashes(org_id: uuid.UUID) -> list[str]:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn, tenant_transaction(conn, org_id):
            result = await conn.execute(
                text("SELECT token_hash FROM set_password_tokens WHERE org_id = :org"),
                {"org": org_id},
            )
            return list(result.scalars())
    finally:
        await engine.dispose()


async def _purge(*org_ids: uuid.UUID) -> None:
    engine = create_async_engine(to_sqlalchemy_url(os.environ["DATABASE_URL"]))
    try:
        await purge_org_ids(engine, *org_ids)
    finally:
        await engine.dispose()


@pytest.fixture
def admin_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_BASE_URL", raising=False)


@pytest.mark.usefixtures("admin_url_unset")
def test_org_create_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    sfx = uuid.uuid4().hex[:8]
    argv = ["org", "create", "--name", f"  CLI {sfx} ", "--owner", f"Owner.{sfx}@Example.com"]

    code = cli.main(argv)
    out, err = capsys.readouterr()
    match = OUTPUT.match(out)
    assert match is not None, out
    org_id = uuid.UUID(match.group(1))
    try:
        assert (code, err) == (0, "")
        assert match.group(2) == f"CLI {sfx}"
        assert match.group(5) == f"owner.{sfx}@example.com"
        assert match.group(6) == str(org_id)
        assert asyncio.run(_token_hashes(org_id)) == [hash_secret(match.group(7))]
    finally:
        asyncio.run(_purge(org_id))


@pytest.mark.usefixtures("admin_url_unset")
def test_duplicate_org_exits_1_with_clean_error(capsys: pytest.CaptureFixture[str]) -> None:
    sfx = uuid.uuid4().hex[:8]
    assert cli.main(["org", "create", "--name", f"Dup {sfx}", "--owner", "o@example.com"]) == 0
    first = OUTPUT.match(capsys.readouterr().out)
    assert first is not None
    try:
        code = cli.main(["org", "create", "--name", f" DUP {sfx}", "--owner", "p@example.com"])
        out, err = capsys.readouterr()

        assert (code, out) == (1, "")
        assert err == "error: an Organization with this name already exists\n"
        for leak in ("Key (", "INSERT", "SELECT", "postgresql://", "Traceback"):
            assert leak not in err
    finally:
        asyncio.run(_purge(uuid.UUID(first.group(1))))
